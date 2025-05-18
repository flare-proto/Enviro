import asyncio
import configparser
import datetime
import json
import logging
import sqlite3
import threading
import time

import coloredlogs
import pika
import requests
from bs4 import BeautifulSoup

import connLog

config = configparser.ConfigParser()
config.read("config.ini")

lookback = 24

logger = logging.Logger("DL")
testSrv = pika.URLParameters(config["downloader"]["amqp"])
connParam = pika.ConnectionParameters(testSrv.host,testSrv.port,credentials=testSrv.credentials,heartbeat=0)

connection = pika.BlockingConnection(connParam)
channel = connection.channel()
chnd = connLog.ConnHandler(channel)
formatter = coloredlogs.ColoredFormatter('DL - %(asctime)s - %(levelname)s - %(message)s')
chnd.setFormatter(formatter)
logger.addHandler(chnd)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

amqp_url = "amqps://anonymous:anonymous@dd.weather.gc.ca/"
exchange = "q_anonymous.sr_subscribe.cap-xml_conf.flare_envirotron"
routing_key = "v02.post.*.WXO-DD.alerts.cap.#"
# Establish connection
params = pika.URLParameters(amqp_url)
connection_env = pika.BlockingConnection(params)
channel_env = connection_env.channel()

newCapDownloaded = 0

issu = ("CWNT","CWWG","CWVR","CWHX","CWUL","LAND","CWTO")

def setup():
    c = sqlite3.connect("alert.db")
    c.execute("CREATE TABLE if not exists  `Alerts` (`key` INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE, `id` TEXT UNIQUE, `data` TEXT)")
    c.execute("CREATE TABLE if not exists  `formattedAlert` (`id` TEXT PRIMARY KEY UNIQUE, `begins` TEXT, `ends` TEXT, `areas` TEXT, `urgency` TEXT, `references` TEXT, `msgType` TEXT, `type` TEXT)")
    c.close()
    logger.info("PCAP setup")

def get_url_paths(url, ext='', params={}):
    response = requests.get(url, params=params)
    if response.ok:
        response_text = response.text
    else:
        return []
    soup = BeautifulSoup(response_text, 'html.parser')
    parent = [(url + node.get('href'),node.get('href')) for node in soup.find_all('a') if node.get('href').endswith(ext)]
    return parent

def cache(sql:sqlite3.Cursor,url):
    global newCapDownloaded
    
    sql.execute("SELECT EXISTS(SELECT 1 FROM Alerts WHERE id=?)",(url,))
    fth =  sql.fetchone()
    if not fth[0]:
        logger.info(url)
        R = requests.get(url)
        newCapDownloaded+=1
        sql.execute("INSERT or replace INTO Alerts (id,data) VALUES (?,?)",(url,R.text))
        return R.text,True
    else:
        sql.execute("SELECT data FROM Alerts WHERE id=?",(url,))
        fth =  sql.fetchone()
        return fth[0],False

def fetch():
    global lookback,newCapDownloaded
    t = datetime.datetime.now(datetime.timezone.utc)
    dat = []
    newCapDownloaded = 0
    for i in range(lookback,0,-1):
        T = datetime.timedelta(hours=i)
        d = t-T
        #print(f"{d.day} -> {d.hour}")
        
        for iss in issu:
            conn = sqlite3.connect("alert.db")
            try:
                cur = conn.cursor()
                url = f'https://dd.weather.gc.ca/{d.year}{d.month:>02}{d.day:>02}/WXO-DD/alerts/cap/{d.year}{d.month:>02}{d.day:>02}/{iss}/{d.hour:>02}/'
                result: list[str] = get_url_paths(url, "cap")
                #for p in prov:
                #    print(f"{d.year}{d.month}{d.day}/CWNT/{d.hour}/T_{p}CN")
                for r,name in result:
                    R,n = cache(cur,r)
                    dat.append(R)
                    channel.basic_publish("alerts","cap",json.dumps({
                        "typ":"dat",
                        "data":R
                    }),pika.BasicProperties(content_type='text/json',
                                            delivery_mode=pika.DeliveryMode.Transient))
            except BaseException as e:
                logger.warning(f"Failed to download {e}")
            conn.commit()
            conn.close()
    lookback = 1

    logger.info(f"Downloaded {newCapDownloaded} alerts")
def callback(ch, method, properties, body):
    conn = sqlite3.connect("alert.db")
    cur = conn.cursor()
    
    b:str = body.decode()
    A,dd,path =b.split(" ")
    
    logger.info(f"Received alert over AMQP {A}, Downloading")
    try:
        R,n = cache(cur,dd+path)
        channel.basic_publish("alerts","cap",json.dumps({
            "typ":"dat",
            "data":R
        }),pika.BasicProperties(content_type='text/json',
                                delivery_mode=pika.DeliveryMode.Transient))
    except BaseException as e:
        logger.warning(f"Failed to download {e}")
    conn.commit()
    conn.close()
def run():
    try:
        logger.info("downloading data, please wait...")
        fetch()
        result = channel_env.queue_declare(exchange)#'q_anonymous_flare')
        queue_name = result.method.queue
        print(queue_name)
        channel_env.queue_bind(queue_name,"xpublic",routing_key )
        channel_env.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
        channel_env.start_consuming()
        while True:
            for i in range(10):
                time.sleep(30)
                
                channel.basic_publish("","hb","HEARTBEAT")
                channel.basic_get("hb",True)
    except BaseException as e:
        if not isinstance(e,KeyboardInterrupt):
            logger.critical(f"{type(e)} {e}")
        logger.warning("DL auto offline")
def downloader():
    try:
        logger.info("downloading data, please wait...")
        fetch()
        result = channel_env.queue_declare(exchange)#'q_anonymous_flare')
        queue_name = result.method.queue
        print(queue_name)
        channel_env.queue_bind(queue_name,"xpublic",routing_key )
        channel_env.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
        threading.Thread(target=run,daemon=True).start()
        while True:
            for i in range(10):
                time.sleep(30)
            channel.basic_publish("alerts","cap",json.dumps({
                    "typ":"merge",
                    "data":"..."
                }),pika.BasicProperties(content_type='text/json',
                                           delivery_mode=pika.DeliveryMode.Transient))
    except BaseException as e:
        if not isinstance(e,KeyboardInterrupt):
            logger.critical(f"{type(e)} {e}")
        logger.warning("DL offline")
        connection.close()
        connection_env.close()
        
