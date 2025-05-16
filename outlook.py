import configparser
import hashlib
import json
import os
import sqlite3
import threading
import time
from bdb import effective
from datetime import datetime, timedelta
from urllib.parse import urljoin

import pika
import requests
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

CONFIG_FILE = 'config.ini'

config = configparser.ConfigParser()
config.read("config.ini")

BASE_URL = 'https://dd.alpha.weather.gc.ca/thunderstorm-outlooks/'
HASH_DIR = 'outlook_hashes'
CHECK_INTERVAL = 1800  # 30 minutes
testSrv = pika.URLParameters(config["outlook"]["amqp"])

def ensure_hash_dir():
    os.makedirs(HASH_DIR, exist_ok=True)

def list_json_files():
    resp = requests.get(BASE_URL)
    resp.raise_for_status()
    files = []
    for line in resp.text.splitlines():
        if 'href="' in line and '.json' in line:
            start = line.find('href="') + 6
            end = line.find('"', start)
            href = line[start:end]
            if href.endswith('.json'):
                files.append(href)
    return files

def download(url):
    return requests.get(urljoin(BASE_URL, url)).content

def hash_content(data):
    return hashlib.sha256(data).hexdigest()

def get_hash_path(filename):
    return os.path.join(HASH_DIR, filename.replace('/', '_') + '.hash')

def read_stored_hash(filename):
    path = get_hash_path(filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return None

def write_stored_hash(filename, h):
    with open(get_hash_path(filename), 'w') as f:
        f.write(h)

nws = [
    ("day1otlk_torn.lyr.geojson","d1_torn")
]

BASE_URL_NWS = "https://www.spc.noaa.gov/products/outlook/"

def NWS(channel):
    for file,rte in nws:
        content = requests.get(urljoin(BASE_URL_NWS, file)).content
        content_hash = hash_content(content)
        stored_hash = read_stored_hash(file)
        jsonDat = json.loads(content)
        if content_hash != stored_hash:
            print(f"New NWS outlook: {file}")
            channel.basic_publish(
                exchange='outlook',
                routing_key=f'outlook.NWS.{rte}',
                body=json.dumps({
                    "ver":"v1",
                    "cont":jsonDat
                })
            )
            write_stored_hash(file, content_hash)

def check_and_publish():
    
    ensure_hash_dir()
    connection = pika.BlockingConnection(testSrv)
    
    channel = connection.channel()
    print(f"[{datetime.now()}] Checking thunderstorm outlooks...")
    try:
        NWS(channel)
        for file in list_json_files():
            print(f"downloading {file}")
            content = download(file)
            
            ver = str(file).removesuffix(".json")[-2:]
            
            content_hash = hash_content(content)
            stored_hash = read_stored_hash(file)
            jsonDat = json.loads(content)
            if content_hash != stored_hash:
                print(f"New outlook: {file}")
                channel.basic_publish(
                    exchange='outlook',
                    routing_key='outlook.ECCC',
                    body=json.dumps({
                        "ver":ver,
                        "cont":jsonDat
                    })
                )
                write_stored_hash(file, content_hash)
            else:
                print(f"No change: {file}")
    except Exception as e:
        print(f"[ERROR] {e}")
    connection.close()

def start_outlook_watcher():
    check_and_publish()
    while True:
        time.sleep(CHECK_INTERVAL)
        check_and_publish()

if __name__ == "__main__":
    start_outlook_watcher()