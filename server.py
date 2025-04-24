import asyncio
import collections
import configparser
import logging
import struct
import threading,queue
from datetime import datetime, timedelta, timezone
from time import sleep

import ansi2html
import ansi2html.style
import coloredlogs
import pika
from cachetools import TTLCache, cached
from env_canada import ECWeather
from flask import (Flask, Response, json, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, url_for)
from flask_cors import CORS, cross_origin
from flask_sock import Server, Sock
from gevent.pywsgi import WSGIServer
from sqlalchemy.dialects.postgresql import insert

import dbschema
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
        dt = datetime.strptime(feature["properties"]["expiration_datetime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        vdt = feature["properties"]["metobject"].get("validity_datetime", "")
        if vdt:
            edt = datetime.strptime(vdt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            print(feature["properties"]["metobject"])
            edt = datetime.now(timezone.utc)

        stmt = insert(dbschema.Outlook).values(
            outlook_id=feature["id"],
            feature=json.dumps(feature),
            expires_at=dt,
            effective_at=edt
        )

        # On conflict with outlook_id, update the feature, expires_at, and effective_at
        stmt = stmt.on_conflict_do_update(
            index_elements=['outlook_id'],
            set_={
                "feature": stmt.excluded.feature,
                "expires_at": stmt.excluded.expires_at,
                "effective_at": stmt.excluded.effective_at,
            }
        )

        session.execute(stmt)
    
def callback_outlook(ch, method, properties, body):
    """Handle incoming RabbitMQ messages."""
    try:
        message = json.loads(body.decode())
        for i,f in enumerate(message["features"]):
            f["id"] = f"{f["id"]}_{i}"
            saveFeature(f)
    except Exception as e:
        logging.exception(e)
    
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

    result = channel.queue_declare(queue='', exclusive=True)
    channel.queue_bind(exchange='outlook',
                    queue=result.method.queue)
    
    channel.queue_declare(queue='weather-alerts', exclusive=True)
    channel.queue_bind(exchange='alerts', queue='weather-alerts', routing_key='alerts.*.*.*')
    
    channel.queue_declare(queue='live-feed', exclusive=True)
    channel.queue_bind(exchange='feed', queue='live-feed', routing_key='*.*')
    
    channel.basic_consume(queue='weather-alerts', on_message_callback=callback_nerv_alert, auto_ack=True)
    
    channel.basic_consume(queue='live-feed', on_message_callback=callback_feed, auto_ack=True)
    
    channel.basic_consume(queue=result.method.queue, on_message_callback=callback_outlook, auto_ack=True)
    
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
    broadcast(brief)
    
    return weather

@sockets.route('/apiws/alertsws')
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
    alertsDat = []
    
    session = dbschema.Session()
    with session.begin():
        valid_tokens = dbschema.get_active_alert_polygons(session)
        jsonDat = {	
            "type":"FeatureCollection",
            "features":[t.geometry_geojson for t in valid_tokens]
        }
    session.close()
    
    return jsonify(jsonDat)

@app.route("/api/alerts/all")
def alertsall():
    alertsDat = []
    
    session = dbschema.Session()
    with session.begin():
        valid_tokens = dbschema.get_alert(session)
        jsonDat = [i.properties for i in valid_tokens]
    session.close()
    
    return jsonify(jsonDat)

@app.route("/api/alerts")
def alerts_og():
    global weather
    weather = update()
    return jsonify(weather["alerts"])

@app.route("/api/outlook")
def outlook():
    session = dbschema.Session()
    with session.begin():
        valid_tokens = session.query(dbschema.Outlook).filter(dbschema.Outlook.expires_at > datetime.utcnow()).filter(dbschema.Outlook.effective_at < datetime.utcnow()).all()
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

def utf8_integer_to_unicode(n):
    #s= hex(n)
    #if len(s) % 2:
    #    s= '0'+s
    #return s.decode('hex').decode('utf-8')
    return struct.pack(">H",n)

@app.route("/api/conditions/bft")
def conditionsbft():
    for i,b in enumerate(windLevels):
        if b["max"] > weather["cond"].get("wind_speed",0)+0.1:
            return jsonify({"scale":i,"icon":chr(0xe3af+i)})

@app.route("/api/tso")
def tso():
    pass


@app.route('/bar')
def bar():
    return render_template('bar.html')

@app.route('/')
def main():
    return send_from_directory("static/my-app/dist/","index.html")

@app.route('/assets/<path:key>')
def assets(key):
    return send_from_directory("static/my-app/dist/assets/",key)


if __name__ == '__main__':
    threading.Thread(target=consume_messages, daemon=True,name="AMQP SERVER RECV").start()

    app.run("0.0.0.0")