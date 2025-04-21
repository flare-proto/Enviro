import collections
import configparser
import datetime
import json
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET

import coloredlogs
import pika
import pika.spec
from dateutil import parser
from schema import And, Optional, Schema, SchemaError, Use
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

import connLog
import merge as mg

config = configparser.ConfigParser()
config.read("config.ini")

alerts_in_effect = {}
def DataHandler():
    logger = logging.Logger("DH")

    testSrv = pika.URLParameters(config["DataHandler"]["amqp"])

    connection = pika.BlockingConnection(testSrv)
    channel = connection.channel()
    chnd = connLog.ConnHandler(channel)
    formatter = coloredlogs.ColoredFormatter('DH - %(asctime)s - %(levelname)s - %(message)s')
    chnd.setFormatter(formatter)
    chnd.setLevel(logging.INFO)
    logger.addHandler(chnd)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    schema = Schema(
        {
                "typ": And(str, len),
                "data": And(str, len),
        }
    )
    
    def anounceAlert(alert: dict,id: str):
        channel.basic_publish(exchange='alert', routing_key='', body=json.dumps({
            "status":"Actual",
            "type":"Alert",
            "id":id,
            "alert":alert
        }))
    def replaceAlert(old_id,id):
        channel.basic_publish(exchange='alert', routing_key='', body=json.dumps({
            "status":"Actual",
            "type":"Update",
            "old_id":old_id,
            "id":id
        }))
    def endAlert(id):
        channel.basic_publish(exchange='alert', routing_key='', body=json.dumps({
            "status":"Actual",
            "type":"Cancel",
            "id":id
        }))

    def extract_urns(data: str):
        """
        Extract all `urn:oid` patterns from the given string.

        Args:
            data (str): The input string containing `urn:oid` patterns.

        Returns:
            list: A list of all `urn:oid` patterns found in the string.
        """
        # Regular expression to match `urn:oid` patterns
        urn_pattern = r"urn:oid:[\w\d\.\-]+"
        return re.findall(urn_pattern, data)

    def parse_cap(content: str) -> dict:
        """
        Parse a CAP file and extract relevant information, removing alerts referenced in `references`.

        Args:
            file_path (str): The path to the CAP XML file.

        Returns:
            dict: A dictionary containing alert information if the alert is valid and not referenced, otherwise None.
        """
        try:
            # Read the file with error handling for encoding issues
            
            
            # Parse the XML content
            root = ET.fromstring(content)
            
            # CAP namespace handling
            ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
            
            # Extract relevant fields
            status = root.find('cap:status', ns).text  # Example: "Actual"
            msgType = root.find('cap:msgType', ns).text
            expires = root.find('cap:info/cap:expires', ns).text  # Example: "2024-12-21T12:00:00-00:00"
            response_type = root.find('cap:info/cap:responseType', ns)
            response_type = response_type.text if response_type is not None else None
            urgency = root.find('cap:info/cap:urgency', ns).text

            # Effective time is optional
            effective_element = root.find('cap:info/cap:effective', ns)
            effective_time = (
                parser.isoparse(effective_element.text).replace(tzinfo=datetime.timezone.utc)
                if effective_element is not None
                else None
            )

            # Expiry time
            expires_time = parser.isoparse(expires).replace(tzinfo=datetime.timezone.utc)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            # Extract the alert identifier and references
            identifier = root.find('cap:identifier', ns).text
            event = root.find('cap:info/cap:event', ns).text
            references_element = root.find('cap:references', ns)

            # Extract OIDs from references (the second element in each reference entry)
            reference_ids = extract_urns(references_element.text or "")
            
            areas = []
            for area in root.findall('.//cap:area', ns):
                # If the area is a polygon
                polygon_element = area.find('cap:polygon', ns)
                if polygon_element is not None:
                    polygon_coords = polygon_element.text.strip().split()
                    # Convert to list of tuples
                    coordinates = [(tuple(map(float, coord.split(','))))[::-1] for coord in polygon_coords]
                    polygon = Polygon(coordinates)
                    if polygon.is_valid:
                        areas.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [list(polygon.exterior.coords)]
                            },
                            "properties": {"warn":event,"id":identifier}
                        })
                        
            #FIXME temp
            try:
                areas = mg.merge_polygons_by_warn({
                            "type": "FeatureCollection",
                            "features": areas
                })["features"]
            except KeyError as e:
                logger.warning(f"Alert {identifier} has no area")
                areas = []
            # Check if the alert is in effect
            if current_time >= expires_time:
                logger.info(f"Alert {identifier} expired at {expires_time}, current time: {current_time}")

                return
            elif effective_time is not None and effective_time >= current_time:
                logger.info(f"Alert {identifier} is upcoming, starts in {effective_time - current_time}")
                return
            elif status == "Actual":# and (effective_time is None or effective_time <= current_time) and current_time <= expires_time:
                return {
                    "status": status,
                    "effective": effective_element.text if effective_element is not None else None,
                    "expires": expires,
                    "identifier": identifier,
                    "sender": root.find('cap:sender', ns).text,
                    "responseType": response_type,
                    "references": reference_ids,
                    "headline": root.find('cap:info/cap:headline', ns).text,
                    "description": root.find('cap:info/cap:description', ns).text,
                    "areas":areas,
                    "msgType":msgType,
                    "type":event,
                    "urgency": urgency,
                }
            else:
                logger.warning(f"{status} {identifier}")
            
        except ET.ParseError as e:
            logging.error(f"XML parsing error in: {e}")
        #except Exception as e:
        #    print(f"Error parsing: {e}")
        return None

    def parseAlert(dat):
        conn = sqlite3.connect("alert.db")
        cur = conn.cursor()
        alert = parse_cap(dat)
        if alert:
            alert_id = alert["identifier"]
            # Handle updates
            if alert_id in alerts_in_effect:
                # If the new alert has "AllClear", remove the previous alert
                
                if alert.get("responseType") == "AllClear" or alert.get("urgency") == "Past":
                    for r in alert.get("references"):
                        if r in alerts_in_effect:
                            logger.debug(f"removing {r}")
                            cur.execute("DELETE FROM formattedAlert WHERE id = ?;",(r,))
                            del alerts_in_effect[r]
                            endAlert(r)
                    cur.execute("DELETE FROM formattedAlert WHERE id = ?;",(alert_id,))
                    del alerts_in_effect[alert_id]
                    endAlert(alert_id)
                else:
                    # Otherwise, replace the old alert with the new one
                    cur.execute("INSERT or replace INTO formattedAlert (id,begins,ends,urgency,msgType,type) VALUES (?,?,?,?,?,?)",
                                (alert_id,alert["effective"],alert["expires"],alert["urgency"],alert["msgType"],alert["type"]))
                    alerts_in_effect[alert_id] = alert
                    anounceAlert(alert,alert_id)
            else:
                # Add the new alert if it's not already tracked
                anounceAlert(alert,alert_id)
                alerts_in_effect[alert_id] = alert
                cur.execute("INSERT or replace INTO formattedAlert (id,begins,ends,urgency,[references],msgType,type,desc,areas) VALUES (?,?,?,?,?,?,?,?,?)",
                                (alert_id,alert["effective"],alert["expires"],alert["urgency"],json.dumps(alert["references"]),alert["msgType"],alert["type"],alert["description"],json.dumps(alert["areas"])))
                for r in alert.get("references"):
                    if r in alerts_in_effect:
                        logger.info(f"removing {r}")
                        cur.execute("DELETE FROM formattedAlert WHERE id = ?;",(r,))
                        del alerts_in_effect[r]
                        replaceAlert(r,alert_id)
        else:
            logger.debug("bad alert")
        conn.commit()
        conn.close()

    alerts = []
    merged = {
                        "type": "FeatureCollection",
                        "features": []
                    }
    
    def cleanup():
        deleteAlerts = []
        current_time = datetime.datetime.now(datetime.timezone.utc)
        for k,v in alerts_in_effect.items():
            expires_time = parser.isoparse(v['expires']).replace(tzinfo=datetime.timezone.utc)
            if current_time >= expires_time:
                logger.info(f"Alert {k} expired at {expires_time}, current time: {current_time}")
                deleteAlerts.append(k)
                endAlert(k)
        for d in deleteAlerts:
            del alerts_in_effect[d]
            
    def merge():
        logger.info("Merging...")
        areas = []
        
        cleanup()
        
        for k,a in alerts_in_effect.items():
            logger.debug(f"{k} type={a['type']} responseType={a['responseType']} urgency={a['urgency']}")
            for A in a["areas"]:
                areas.append(A)
        try:
            merged = mg.merge_polygons_by_warn({
                "type": "FeatureCollection",
                "features": areas
            })
            
            logger.info("Merging complete")
        except KeyError as e:
            logger.error(f"failed to merge {type(e)} {e}")
            merged = {
                "type": "FeatureCollection",
                "features": areas
            }
        except Exception as e:
            logger.error(f"failed to merge {type(e)} {e}")
            merged = {
                "type": "FeatureCollection",
                "features": areas
            }
        except:
            logger.critical("THIS SHOULD NEVER HAPPEN")
        merged = {
                "type": "FeatureCollection",
                "features": areas
            }
        
        channel.basic_publish("","merged",json.dumps(merged),pika.BasicProperties(content_type='text/json',
                                    delivery_mode=pika.DeliveryMode.Transient))
        #alerts_in_effect = {}
    
    def callback(ch, method:pika.spec.Basic.Deliver, properties, body):
        global  alerts_in_effect
        dat =json.loads(body.decode())
        if not schema.is_valid(dat):
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.warning("Invalid")
            return
        d = schema.validate(dat)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        match d["typ"]:
            case "dat":
                parseAlert(d["data"])
            case "merge":
                merge()
                
                
                    
    channel.basic_consume(queue="alert_cap", on_message_callback=callback)

    try:
        logger.info("Data Handling ready")
        channel.start_consuming()
    except Exception as e:
        logger.warning(f"Data Handling stopping {type(e)} {e}")
        print("Stopping...")
        connection.close()