import logging
import uuid
from datetime import datetime, timedelta

import sqlalchemy
import sqlalchemy.orm
from sqlalchemy import (JSON, Column, DateTime, ForeignKey, Integer, String,
                        Table, create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import aliased, backref, relationship, sessionmaker

Base = declarative_base()

# --- SQLAlchemy Models ---

alert_references = Table(
    'alert_references', Base.metadata,
    Column('referencer_id', String, ForeignKey('alerts.id'), primary_key=True),  # Alert that references another
    Column('referencee_id', String, ForeignKey('alerts.id'), primary_key=True)   # Alert being referenced
)

class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sender = Column(String)
    event = Column(String)
    msg_type = Column(String)  # e.g., "alert", "update", "cancel", "expire"
    urgency = Column(String)
    references_str = Column(String, nullable=True)
    effective_at = Column(DateTime)
    expires_at = Column(DateTime)
    properties = Column(JSON)
    

    references = relationship(
        'Alert',
        secondary=alert_references,
        primaryjoin=id==alert_references.c.referencer_id,
        secondaryjoin=id==alert_references.c.referencee_id,
        backref=backref('referenced_by', lazy='dynamic')
    )
    polygons = relationship("AlertPolygon", back_populates="alert")




class AlertPolygon(Base):
    __tablename__ = 'alert_polygons'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id = Column(String, ForeignKey('alerts.id'), nullable=False)
    geometry_geojson = Column(JSON, nullable=False)
    cancelled_by_id = Column(String, ForeignKey('alert_polygons.id'), nullable=True)

    alert = relationship("Alert", back_populates="polygons")
    cancelled_by = relationship("AlertPolygon", remote_side=[id])


def parse_time(ts):
        return datetime.fromisoformat(ts) if ts else None
    
def add_reference_if_exists(session:sqlalchemy.orm.Session, referencer, referencee_id: int):
    referencee = session.get(Alert, referencee_id)


    if referencee not in referencer.references:
        referencer.references.append(referencee)
        session.commit()


# --- Store Alert Function ---
def store_alert(session:sqlalchemy.orm.Session, alert_dict: dict) -> str:
    alert_id = str(alert_dict.get("id"))
    msg_type = alert_dict.get("msg_type", "alert")
    references_raw = alert_dict.get("references", "")

    # Parse references in CAP format: "sender1,id1,time1 sender2,id2,time2"
    referenced_ids = []
    for ref_str in references_raw.strip().split():
        parts = ref_str.split(",")
        if len(parts) == 3:
            _, ref_id, _ = parts
            referenced_ids.append(ref_id)

    # Create Alert instance
    alert = Alert(
        id=alert_id,
        sender=alert_dict.get("sender", "CAP-INGEST"),
        event=alert_dict["event"],
        msg_type=msg_type,
        effective_at=parse_time(alert_dict.get("effective_at")),
        expires_at=parse_time(alert_dict.get("expires_at")),
        urgency=alert_dict["urgency"],
        properties={
            "severity": alert_dict["severity"],
            "certainty": alert_dict["certainty"],
            "areaDesc": alert_dict["areaDesc"],
            "broadcast_message": alert_dict["broadcast_message"]
        }
    )

    # Add alert to session first
    try:
        session.add(alert)
        session.flush()  # Assigns alert.id so polygons can reference it
    except Exception as e:
        session.rollback()
        #raise RuntimeError(f"Failed to store alert {alert_id}: {e}")

    # Add references and apply logic
    polygons = []
    for ref_id in referenced_ids:
        ref_alert = session.get(Alert, ref_id)
        if ref_alert:
            alert.references.append(ref_alert)

            if msg_type == "cancel":
                for old_polygon in ref_alert.polygons:
                    old_polygon.cancelled_by_id = None  # Will set later
                    session.add(old_polygon)

            elif msg_type == "update":
                if ref_alert.expires_at is None or ref_alert.expires_at > datetime.utcnow():
                    print(f"[INFO] Expiring referenced alert {ref_id}")
                    ref_alert.expires_at = datetime.utcnow()
                    session.add(ref_alert)

                if alert_dict["urgency"] == "Past":
                    alert.expires_at = datetime.utcnow()

            elif msg_type == "expire":
                ref_alert.expires_at = datetime.utcnow()
                session.add(ref_alert)
        else:
            print(f"[WARN] Referenced alert {ref_id} not found")

    # Add polygons
    for geom in alert_dict.get("geojson_polygons", []):
        polygon = AlertPolygon(
            id=str(uuid.uuid4()),
            alert_id=alert_id,
            geometry_geojson=geom
        )
        polygons.append(polygon)
        session.add(polygon)

    # Now update cancelled_by_id (if cancel/update/expire)
    if msg_type in ("cancel", "expire") and polygons:
        first_polygon_id = polygons[0].id
        for ref_id in referenced_ids:
            ref_alert = session.get(Alert, ref_id)
            if ref_alert:
                for old_polygon in ref_alert.polygons:
                    old_polygon.cancelled_by_id = first_polygon_id
                    session.add(old_polygon)

    session.commit()
    return alert_id


# --- Get Active Alert Polygons ---
def get_active_alert_polygons(session) -> list:
    # Query for polygons from active alerts (not expired and not cancelled)
    Referenced = aliased(Alert)
    active_polygons = session.query(AlertPolygon).join(Alert).filter(
        Alert.expires_at > datetime.utcnow(), 
        Alert.urgency != "past",
        AlertPolygon.cancelled_by_id == None,
        
    ).all()
    
    return active_polygons

def get_alert(session) -> list:
    # Query for polygons from active alerts (not expired and not cancelled)
    active_polygons = session.query(Alert).filter(
        Alert.expires_at > datetime.utcnow(), 
    ).all()
    
    return active_polygons





class Outlook(Base):
    __tablename__ = 'outlooks'

    outlook_id = Column(String, primary_key=True)
    feature = Column(String, nullable=False)
    effective_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    ver = Column(String, nullable=False)

    def is_in_effect(self):
        return datetime.utcnow() >= self.expires_at and datetime.utcnow() <= self.effective_at
    
class NWSOutlook(Base):
    __tablename__ = 'NWSoutlooks'

    outlook_id = Column(Integer, primary_key=True,autoincrement=True)
    feature = Column(String, nullable=False)
    effective_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    route = Column(String, nullable=False)

    def is_in_effect(self):
        return datetime.utcnow() >= self.expires_at and datetime.utcnow() <= self.effective_at


# --- Example setup below ---

# Create a SQLite database file
DATABASE_URL = 'sqlite:///outlook.db'  # Use a file-based SQLite database
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# Create tables
Base.metadata.create_all(engine)