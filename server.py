import asyncio
import collections
import configparser
import logging
import queue
import struct
import threading
from datetime import datetime, timedelta, timezone
from time import sleep

import ansi2html
import ansi2html.style
import coloredlogs
import pika
import pika.frame
import pika.spec
from cachetools import TTLCache, cached
from env_canada import ECWeather
from flasgger import Swagger
from flask import (Flask, Response, json, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, url_for)
from flask_cors import CORS, cross_origin
from flask_sock import Server, Sock
from gevent.pywsgi import WSGIServer
from sqlalchemy import desc
from sqlalchemy.dialects.postgresql import insert

import dbschema
import merge
import pcap

# Example usage

logging.basicConfig(level=logging.DEBUG)

config = configparser.ConfigParser()
config.read("config.ini")


ansi2html.style.SCHEME["ansi2html"] = (
        "#555555",
        "#aa0000",
        "#00aa00",
        "#aa5500",
        "#0000aa",
        "#E850A8",
        "#00aaaa",
        "#F5F1DE",
        "#7f7f7f",
        "#ff0000",
        "#00ff00",
        "#ffff00",
        "#5c5cff",
        "#ff00ff",
        "#00ffff",
        "#ffffff",
    )
logSync = threading.Lock()
class ListHandler(logging.Handler):
    def __init__(self, log_list):
        super().__init__()
        self.log_list = log_list

    def emit(self, record):
        log_entry = self.format(record)
        logSync.acquire()
        self.log_list.append(log_entry)
        logSync.release()


log_messages = collections.deque(maxlen= 1000)
net_log_messages = collections.deque(maxlen= 1000)
list_handler = ListHandler(log_messages)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
list_handler.setFormatter(formatter)

logger = logging.getLogger()
formatter = coloredlogs.ColoredFormatter('SV - %(asctime)s - %(levelname)s - %(message)s')
list_handler.setFormatter(formatter)
list_handler.setLevel(logging.INFO)
logger.addHandler(list_handler)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
pcap.setup()

app = Flask(__name__)
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
app.config['SQLALCHEMY_ECHO'] =False
sockets = Sock(app)
swagger = Swagger(app)


CORS(app,resources=r'/api/*')
ec_en = ECWeather(station_id=config["server"]["station_id"], language='english')
types = [
    "warnings",
    "watches",
    "advisories",
    "statements",
    "endings"
]
conditionTypes = [
    "temperature",
    "dewpoint",
    "wind_speed",
    "wind_chill",
    "wind_bearing"
]

windLevels = [
    {"max":1},
    {"max":5},
    {"max":11},
    {"max":19},
    {"max":28},
    {"max":38},
    {"max":49},
    {"max":61},
    {"max":74},
    {"max":88},
    {"max":102},
    {"max":117},
    {"max":133},
]

weather = {
    "alerts" :[],
    "cond":{}
}
mapings = {
    "Tornado Warning":             "warns.TORNADO",
    "Tornado Watch":               "watch.TORNADO",
    "SEVERE THUNDERSTORM WARNING": "warns.TSTORM",
    "SEVERE THUNDERSTORM WATCH":   "watch.TSTORM",
    "Snowfall Warning": "warns.SNOW",
    "Extreme Cold Warning" : "warns.COLD"
}
iconBindings = {
    "01":"clear",
    "02":"partcloud",
    "03":"partcloud",
    "04":"cloudy",
    "05":"partcloud",
    "06":"clear",
    "07":"raining",
    "08":"snowrain",
    "09":"snowing",
    "10":"thunderstorm",
    "11":"cloudy",
    "12":"raining",
    "13":"raining",
    "14":"hail",
    "15":"snowing",
    "16":"snowing",
    "17":"snowing",
    "18":"snowing",
    "26":"partcloud",
    "27":"partcloud",
    "28":"cloudy",
    "30":"moonclear",
    "31":"raining",
    "32":"snowrain",
    "33":"snowing",
    "34":"thunderstorm",
    "35":"snowwind",
    "36":"windy",
    
}
wsocketsConned:set[queue.Queue] = set()
alertsMap = {}
lock = threading.Lock()

def broadcast(message, sender=None):
    with lock:
        for client in list(wsocketsConned):
            if client != sender:  # Optional: don't echo back to sender
                #logging.info(message)
                client.put(message)

RABBITMQ_HOST = pika.URLParameters(config["server"]["amqp"])

messages = []  # Store received messages in a list for demonstration

def callback_log(ch, method, properties, body):
    """Handle incoming RabbitMQ messages."""
    message = body.decode()
    logSync.acquire()
    list_handler.log_list.append(message)  # Store the message
    net_log_messages.append(message)
    logSync.release()
    
def saveFeature(feature):
    session = dbschema.Session()
    with session.begin():
        dt = datetime.fromisoformat((feature["properties"]["expiration_datetime"]).replace('Z', '+00:00'))
        vdt = feature["properties"].get("validity_datetime", "")
        if vdt:
            edt = datetime.fromisoformat(vdt.replace('Z', '+00:00'))
        else:
            #print(feature["properties"]["metobject"])
            logger.warning(f"{feature["id"]} No Time")
            edt = datetime.now(timezone.utc)

        stmt = insert(dbschema.Outlook).values(
            outlook_id=feature["id"],
            feature=json.dumps(feature),
            expires_at=dt,
            effective_at=edt,
            ver=feature["ver"]
        )

        # On conflict with outlook_id, update the feature, expires_at, and effective_at
        stmt = stmt.on_conflict_do_update(
            index_elements=['outlook_id'],
            set_={
                "feature": stmt.excluded.feature,
                "expires_at": stmt.excluded.expires_at,
                "effective_at": stmt.excluded.effective_at,
                "ver": stmt.excluded.ver,
            }
        )

        session.execute(stmt)
    
def callback_outlook(ch, method, properties, body):
    """Handle incoming RabbitMQ messages."""
    try:
        message = json.loads(body.decode())
        logger.info(f"RECV OUTLOOK {message["ver"]}")
        for i,f in enumerate(message["cont"]["features"]):
            f["id"] = f"{f["id"]}_{i}"
            f['ver'] = message["ver"]
            saveFeature(f)
    except Exception as e:
        logging.exception(e)
        
def callback_nws_outlook(ch, method:pika.spec.Basic.Deliver, properties:pika.frame.Header, body):
    """Handle incoming RabbitMQ messages."""

    try:
        message = json.loads(body.decode())
        logger.info(f"RECV NWS OUTLOOK {method.routing_key}")
        for i,feature in enumerate(message["cont"]["features"]):
            session = dbschema.Session()
            with session.begin():
                logger.info(f"NWS OUTLOOK {method.routing_key} #{i}")
                dt = datetime.strptime(feature["properties"]["EXPIRE"], "%Y%m%d%H%M")
                edt =datetime.strptime(feature["properties"]["VALID"], "%Y%m%d%H%M")
                o = dbschema.NWSOutlook(
                    feature=json.dumps(feature),
                    expires_at=dt,
                    effective_at=edt,
                    route=method.routing_key
                )
                session.add(o)
    except Exception as e:
        logger.exception(e)
    
def callback_nerv_alert(ch, method, properties, body):
    """Handle incoming RabbitMQ messages."""
    message = json.loads(body.decode())
    
    #broadcast(message["broadcast_message"])
    
    session = dbschema.Session()
    dbschema.store_alert(session,message)
    session.commit()
    session.close()

def callback_feed(ch, method, properties, body):
    """Handle incoming RabbitMQ messages."""
    message = body.decode()
    broadcast(message)
    
def consume_messages():
    """Start consuming messages from RabbitMQ."""
    connection = pika.BlockingConnection(RABBITMQ_HOST)
    channel = connection.channel()

    channel.basic_consume(queue="log", on_message_callback=callback_log, auto_ack=True)

    result = channel.queue_declare(queue='outlooks-feed', exclusive=True)
    channel.queue_bind(exchange='outlook',
                    queue="outlooks-feed",routing_key="outlook.ECCC")
    
    result = channel.queue_declare(queue='outlooks-feed-nws', exclusive=True)
    channel.queue_bind(exchange='outlook',
                    queue="outlooks-feed-nws",routing_key="outlook.NWS.*")
    
    channel.queue_declare(queue='weather-alerts', exclusive=True)
    channel.queue_bind(exchange='alerts', queue='weather-alerts', routing_key='alerts.*.*.*')
    
    channel.queue_declare(queue='live-feed', exclusive=True)
    channel.queue_bind(exchange='feed', queue='live-feed', routing_key='*.*')
    
    channel.basic_consume(queue='weather-alerts', on_message_callback=callback_nerv_alert, auto_ack=True)
    
    channel.basic_consume(queue='live-feed', on_message_callback=callback_feed, auto_ack=True)
    
    channel.basic_consume(queue="outlooks-feed", on_message_callback=callback_outlook, auto_ack=True)
    
    channel.basic_consume(queue="outlooks-feed-nws", on_message_callback=callback_nws_outlook, auto_ack=True)
    
    print("Waiting for messages...")
    channel.start_consuming()  # Blocking call

async def alertMap():
    global alertsMap
    alertsMap = pcap.fetch()
    
@cached(cache=TTLCache(maxsize=1024, ttl=60))
def update():
    weather = {
        "alerts" :[
        ],
        "cond":{},
        "icon_code":None
    }
    try:
        print("up")
        asyncio.run(ec_en.update())
    except:
        pass
    for c in types:
        if ec_en.alerts[c]["value"]:
            for i in ec_en.alerts[c]["value"]:
                weather["alerts"].append({
                    "mapped":mapings.get(i['title'],"NONE"),
                    "title":i['title'],
                    "class":c
                })
    for c in conditionTypes:
        weather["cond"][c] = ec_en.conditions[c]["value"]
    weather["cond"]["ECicon_code"] = ec_en.conditions["icon_code"]["value"]
    weather["cond"]["icon_code"] = iconBindings.get(weather["cond"]["ECicon_code"],"err")
    
    icon = "?"
    for i,b in enumerate(windLevels):
        if b["max"] > weather["cond"].get("wind_speed",0)+0.1:
            icon=chr(0xe3af+i)
            break
    
    brief = f"{weather["cond"]["temperature"]}°C | {weather["cond"]["wind_speed"]} km/h @ {weather['cond']["wind_bearing"]}° {icon}"
    
    return weather

@sockets.route('/apiws/alerts')
def echo_socket(ws:Server):
    logging.info("Socket Connected")
    #ws.receive()
    q = queue.Queue()
    wsocketsConned.add(q)
    ws.send("Envirotron WEB")
    icon = "?"
    for i,b in enumerate(windLevels):
        if b["max"] > weather["cond"].get("wind_speed",0)+0.1:
            icon=chr(0xe3af+i)
            break
    ws.send(f"{weather["cond"]["temperature"]}°C | {weather["cond"]["wind_speed"]} km/h @ {weather['cond']["wind_bearing"]}° {icon}")
    while True:
        message=q.get()
        try:
            
            ws.send(message)
        except Exception as e:
            logging.info(f"Socket Disconected {e}")
            wsocketsConned.remove(q)



@app.route("/api/geojson")
def alerts():
    """Active Canadian alerts
    ---
    responses:
      200:
        description: Geojson
    """
    alertsDat = []
    
    session = dbschema.Session()
    with session.begin():
        valid_tokens = dbschema.get_active_alert_polygons(session)
        jsonDat = {	
            "type":"FeatureCollection",
            "features":[t.geometry_geojson for t in valid_tokens]
        }
    session.close()
    jsonDat =merge.merge_polygons_by_warn(jsonDat)
    return jsonify(jsonDat)

@app.route("/api/alerts")
def alerts_og():
    """Local Alerts
    TODO result
    ---
    responses:
      200:
        description: Json List with active alerts
        examples:
          result: ['red', 'green', 'blue']
    """
    global weather
    weather = update()
    return jsonify(weather["alerts"])

@app.route("/api/outlook/<ver>")
def outlook(ver):
    """Active Canadian thunderstorm outlooks
    parameters:
      - name: version
        in: path
        type: string
        enum: ['V1', 'V2', 'V3']
        required: true
        default: all
      - name: offset
        in: query
        type: string
        enum: ['-12','0', '+12', '+24']
        required: false
        default: all
        description: Time Offset in hours
    ---
    responses:
      200:
        description: Geojson
    """
    offsetH = int(request.args.get("offset","0"))
    now  = datetime.utcnow()
    now += timedelta(hours=offsetH)
    session = dbschema.Session()
    with session.begin():
        valid_tokens = session.query(dbschema.Outlook).filter(
            dbschema.Outlook.ver ==ver,
          
            dbschema.Outlook.expires_at > now,
            dbschema.Outlook.effective_at < now).all()

        jsonDat = {	
            "type":"FeatureCollection",
            "features":[json.loads(t.feature) for t in valid_tokens]
        }
    session.close()
    return jsonify(jsonDat)

@app.route("/api/nws/outlook/<route>")
def NWSoutlook(route):
    """Active NWS outlooks
    parameters:
      - name: route
        in: path
        type: string
        enum: ['outlook.NWS.d1_torn', 'outlook.NWS.d1_cat']
        required: true
        default: all
      - name: offset
        in: query
        type: string
        enum: ['-12','0', '+12', '+24']
        required: false
        default: all
        description: Time Offset in hours
      - name: sortLatest
        in: query
        type: string
        enum: ['False','True']
        required: false
        default: all
        description: Only get latest by effective time
        
    ---
    responses:
      200:
        description: Geojson
    """
    offsetH = int(request.args.get("offset","0"))
    now  = datetime.utcnow()
    now += timedelta(hours=offsetH)
    session = dbschema.Session()
    with session.begin():
        q = session.query(dbschema.NWSOutlook).filter(
            dbschema.NWSOutlook.route == route)
        
        if not bool(request.args.get("notime",False)):
            q=q.filter(
                dbschema.NWSOutlook.expires_at > now,
                dbschema.NWSOutlook.effective_at < now)
            
        if bool(request.args.get("sortLatest",False)):
            q=q.order_by(desc(dbschema.NWSOutlook.effective_at))
            latest_effective_at = q.limit(1).one().effective_at
            q = session.query(dbschema.NWSOutlook).filter(
                dbschema.NWSOutlook.route == route)
            q=q.filter(
                dbschema.NWSOutlook.expires_at > now,
                dbschema.NWSOutlook.effective_at == latest_effective_at
            )
            
        valid_tokens = q.all()

        jsonDat = {	
            "type":"FeatureCollection",
            "features":[json.loads(t.feature) for t in valid_tokens]
        }
    session.close()
    return jsonify(jsonDat)

@app.route("/api/alerts/top")
def top_alert():
    if len(weather["alerts"]):
        return json.dumps(weather["alerts"][0])
    return json.dumps( {
            "mapped":"NONE",
            "title":"test",
            "class":"warnings"
        })
    
@app.route("/api/conditions")
def conditions():
    """Local Condtions
    ---
    responses:
      200:
        description: Successful response with local weather data
        content:
            application/json:
              schema:
                type: object
                properties:
                  ECicon_code:
                    type: string
                    example: "10"
                  dewpoint:
                    type: number
                    format: float
                    example: 4.7
                  icon_code:
                    type: string
                    example: "thunderstorm"
                  temperature:
                    type: number
                    format: float
                    example: 8.5
                  wind_bearing:
                    type: integer
                    example: 170
                  wind_chill:
                    type: number
                    format: float
                    nullable: true
                    example: null
                  wind_speed:
                    type: number
                    format: float
                    example: 13
                required:
                  - ECicon_code
                  - dewpoint
                  - icon_code
                  - temperature
                  - wind_bearing
                  - wind_chill
                  - wind_speed
    """
    return jsonify(weather["cond"])

@app.route("/log")
def outLog():
    def streamLog():
        conv = ansi2html.Ansi2HTMLConverter()
        m = ""
        logSync.acquire()
        for i in log_messages:
            m += f"{conv.convert(i)}"
        logSync.release()
        return m
        
    return streamLog()

@app.route("/log/net")
def outNetLog():
    def streamLog():
        conv = ansi2html.Ansi2HTMLConverter()
        m = ""
        logSync.acquire()
        for i in net_log_messages:
            m += f"{conv.convert(i)}"
        logSync.release()
        return m
        
    return streamLog()

@app.route("/api/conditions/bft")
def conditionsbft():
    """Get wind icon and Beaufort scale
    ---
    responses:
        '200':
          description: Successful response with wind data
          content:
            application/json:
              schema:
                type: object
                properties:
                  icon:
                    type: string
                    description: Unicode character representing wind icon
                    example: "\ue3b2"
                  scale:
                    type: integer
                    description: Wind strength on the Beaufort scale (0–12)
                    minimum: 0
                    maximum: 12
                    example: 3
                required:
                  - icon
                  - scale
    """
    for i,b in enumerate(windLevels):
        if b["max"] > weather["cond"].get("wind_speed",0)+0.1:
            return jsonify({"scale":i,"icon":chr(0xe3af+i)})

@app.route('/')
def main():
    return send_from_directory("static/my-app/dist/","index.html")

@app.route('/assets/<path:key>')
def assets(key):
    return send_from_directory("static/my-app/dist/assets/",key)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory("static/favicon.ico")

if __name__ == '__main__':
    threading.Thread(target=consume_messages, daemon=True,name="AMQP SERVER RECV").start()

    app.run("0.0.0.0")