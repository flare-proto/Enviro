import configparser
import json
import logging
import xml.etree.ElementTree as ET

import coloredlogs
import pika
from dateutil.parser import parse as parse_datetime

import connLog

config = configparser.ConfigParser()
config.read("config.ini")
logger = logging.Logger("AX")
logger.level = logging.DEBUG

def parse_cap_for_alert_exchange(cap_xml):
    ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
    root = ET.fromstring(cap_xml)
    info = root.find('cap:info', namespaces=ns)
    if info is None:
        raise ValueError("No <info> section in CAP message")

    # Core fields
    id = root.findtext('cap:identifier', default='', namespaces=ns)
    event = info.findtext('cap:event', default='', namespaces=ns)
    urgency = info.findtext('cap:urgency', default='', namespaces=ns)
    severity = info.findtext('cap:severity', default='', namespaces=ns)
    certainty = info.findtext('cap:certainty', default='', namespaces=ns)
    areaDesc = info.findtext('cap:area/cap:areaDesc', default='', namespaces=ns)
    references = root.findtext('cap:references', default='', namespaces=ns)
    description = info.findtext('cap:description', default='', namespaces=ns)
    
    broadcast_message = ""

    for param in root.findall('parameter'):
        value_name = param.findtext('valueName')
        if value_name == 'layer:SOREM:1.0:Broadcast_Text':
            value = param.findtext('value')
            if value:
                broadcast_message = value
                break

    # Timestamps
    effective = info.findtext('cap:effective', default='', namespaces=ns)
    expires = info.findtext('cap:expires', default='', namespaces=ns)

    # Optionally normalize timestamps
    effective_at = parse_datetime(effective).isoformat() if effective else None
    expires_at = parse_datetime(expires).isoformat() if expires else None

    # Polygons
    geojson_polygons = []
    for poly in info.findall('cap:area/cap:polygon', namespaces=ns):
        coords = [
            [float(lon), float(lat)]
            for lat, lon in (pair.split(',') for pair in poly.text.strip().split())
        ]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        geojson_polygons.append({
            "type":"Feature",
            
            "geometry":{
                'type': 'Polygon',
                'coordinates': [coords],
            },
            "properties":{
                "warn":event,
                "id":id,
            }
            })

    return {
        "id":id,
        'event': event.lower().replace(" ", "_"),
        'urgency': urgency.lower(),
        'severity': severity.lower(),
        'certainty': certainty.lower(),
        'areaDesc': areaDesc,
        'references': references,
        'effective_at': effective,
        'expires_at': expires,
        'description':description,
        'broadcast_message':broadcast_message,
        'geojson_polygons': geojson_polygons
    }


def build_routing_key(alert):
    # Example: alerts.weather.tornado.extreme.likely
    event = alert['event'] or 'unknown'
    urgency = alert['urgency'] or 'unknown'
    certainty = alert['certainty'] or 'unknown'
    return f"alerts.{event}.{urgency}.{certainty}"

def on_message(ch, method, properties, body, alert_channel):
    try:
        json_data = json.loads(body.decode('utf-8'))
        if json_data["typ"] != "dat":
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        cap_xml = json_data["data"]
        alert = parse_cap_for_alert_exchange(cap_xml)
        routing_key = build_routing_key(alert)

        alert_channel.basic_publish(
            exchange='alerts',
            routing_key=routing_key,
            body=json.dumps(alert),
            properties=pika.BasicProperties(content_type='application/json')
        )
        logger.debug(alert)
        if alert["broadcast_message"]:
            logger.debug(alert["broadcast_message"])
            alert_channel.basic_publish(
                exchange='feed',
                routing_key=f"AX.{alert['event']}",
                body=alert["broadcast_message"]
            )
            logger.info(f"Published alert bulletin: {alert['event']}")

        logger.info(f"Published alert: {alert['event']} → {routing_key}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logger.error(f"Error: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_cap_topic_relay(source_queue='alert_cap', exchange='alerts'):
    
    
    connection = pika.BlockingConnection(pika.URLParameters(config["DataHandler"]["amqp"]))
    channel = connection.channel()
    
    chnd = connLog.ConnHandler(channel)
    formatter = coloredlogs.ColoredFormatter('AX - %(asctime)s - %(levelname)s - %(message)s')
    chnd.setFormatter(formatter)
    chnd.setLevel(logging.DEBUG)
    logger.addHandler(chnd)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    alert_channel = connection.channel()
    
    channel.queue_declare(queue='alert-cap-ax', exclusive=True)
    channel.queue_bind(exchange='alerts',
                    queue="alert-cap-ax",routing_key="cap")
    
    alert_channel.exchange_declare(exchange=exchange, exchange_type='topic', durable=True)

    channel.basic_qos(prefetch_count=1)
    
    

    def callback(ch, method, properties, body):
        on_message(ch, method, properties, body, alert_channel)

    channel.basic_consume(queue="alert-cap-ax", on_message_callback=callback)
    logger.info(f"Listening on 'alert-cap-ax' and publishing to topic exchange '{exchange}'")
    channel.start_consuming()

if __name__ == "__main__":
    start_cap_topic_relay()