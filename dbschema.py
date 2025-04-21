from sqlalchemy import Column, Integer, String, DateTime, create_engine,ForeignKey,Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker,relationship
from datetime import datetime

Base = declarative_base()

from sqlalchemy import (
    create_engine, Column, String, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timedelta
import uuid

Base = declarative_base()

# --- SQLAlchemy Models ---
class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sender = Column(String)
    event = Column(String)
    msg_type = Column(String)  # e.g., "alert", "update", "cancel", "expire"
    references = Column(String, ForeignKey("alerts.id"), nullable=True)
    effective_at = Column(DateTime)
    expires_at = Column(DateTime)
    properties = Column(JSON)

    referenced_alert = relationship("Alert", remote_side=[id])
    polygons = relationship("AlertPolygon", back_populates="alert")


class AlertPolygon(Base):
    __tablename__ = 'alert_polygons'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id = Column(String, ForeignKey('alerts.id'), nullable=False)
    geometry_geojson = Column(JSON, nullable=False)
    cancelled_by_id = Column(String, ForeignKey('alert_polygons.id'), nullable=True)

    alert = relationship("Alert", back_populates="polygons")
    cancelled_by = relationship("AlertPolygon", remote_side=[id])


# --- Store Alert Function ---
def store_alert(session, alert_dict: dict) -> str:
    # Helper: parse ISO time safely
    def parse_time(ts):
        return datetime.fromisoformat(ts) if ts else None

    msg_type = alert_dict.get("msg_type", "alert")
    references = alert_dict.get("references")

    alert_id = str(uuid.uuid4())
    alert = Alert(
        id=alert_id,
        sender=alert_dict.get("sender", "CAP-INGEST"),
        event=alert_dict["event"],
        msg_type=msg_type,
        effective_at=parse_time(alert_dict.get("effective_at")),
        expires_at=parse_time(alert_dict.get("expires_at")),
        references=references,
        properties={
            "urgency": alert_dict["urgency"],
            "severity": alert_dict["severity"],
            "certainty": alert_dict["certainty"],
            "areaDesc": alert_dict["areaDesc"]
        }
    )
    session.add(alert)

    # Add new polygons if any
    for geom in alert_dict.get("geojson_polygons", []):
        polygon = AlertPolygon(
            id=str(uuid.uuid4()),
            alert_id=alert_id,
            geometry_geojson=geom
        )
        session.add(polygon)

    # If this alert refers to a previous one, handle update/cancel
    if references:
        referenced_alert = session.get(Alert, references)

        if referenced_alert:
            if msg_type == "cancel":
                # Cancel all polygons from the referenced alert
                for old_polygon in referenced_alert.polygons:
                    old_polygon.cancelled_by_id = alert.polygons[0].id if alert.polygons else None
                    session.add(old_polygon)

            elif msg_type == "update":
                # Expire previous alert immediately
                if referenced_alert.expires_at is None or referenced_alert.expires_at > datetime.utcnow():
                    referenced_alert.expires_at = datetime.utcnow()
                    session.add(referenced_alert)

            elif msg_type == "expire":
                # Manually expire the referenced alert
                referenced_alert.expires_at = datetime.utcnow()
                session.add(referenced_alert)

    session.commit()
    return alert_id


# --- Get Active Alert Polygons ---
def get_active_alert_polygons(session) -> list:
    # Query for polygons from active alerts (not expired and not cancelled)
    active_polygons = session.query(AlertPolygon).join(Alert).filter(
        Alert.expires_at > datetime.utcnow(), 
        AlertPolygon.cancelled_by_id == None
    ).all()
    
    return active_polygons




alert_references = Table(
    'alert_references', Base.metadata,
    Column('alert_id', Integer, ForeignKey('alerts.id'), primary_key=True),
    Column('referenced_alert_id', Integer, ForeignKey('alerts.id'), primary_key=True)
)

class Outlook(Base):
    __tablename__ = 'outlooks'

    outlook_id = Column(String, primary_key=True)
    feature = Column(String, nullable=False)
    effective_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    def is_in_effect(self):
        return datetime.utcnow() >= self.expires_at and datetime.utcnow() <= self.effective_at


# --- Example setup below ---

# Create a SQLite database file
DATABASE_URL = 'sqlite:///outlook.db'  # Use a file-based SQLite database
engine = create_engine(DATABASE_URL, echo=True)
Session = sessionmaker(bind=engine)

# Create tables
Base.metadata.create_all(engine)