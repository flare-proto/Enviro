from bdb import effective
import configparser
import hashlib
import json,sqlite3
import os
import time
import threading
from datetime import datetime
from urllib.parse import urljoin

import pika
import requests
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

CONFIG_FILE = 'config.ini'
CHECK_INTERVAL = 1800  # 30 minutes
LAST_HASH_FILE = 'last_outlook_hash.txt'
BASE_URL = 'https://dd.alpha.weather.gc.ca/thunderstorm-outlooks/'

def get_amqp_url():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config.get('outlook', 'amqp')

def get_json_files():
    response = requests.get(BASE_URL)
    response.raise_for_status()
    files = []
    for line in response.text.splitlines():
        if 'href="' in line and '.json' in line:
            start = line.find('href="') + 6
            end = line.find('"', start)
            link = line[start:end]
            if link.endswith('.json'):
                files.append(link)
    return sorted(files)

def download_file(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def compute_hash(content):
    return hashlib.sha256(content).hexdigest()

def read_last_hash():
    if os.path.exists(LAST_HASH_FILE):
        with open(LAST_HASH_FILE, 'r') as f:
            return f.read().strip()
    return None

def write_last_hash(hash_val):
    with open(LAST_HASH_FILE, 'w') as f:
        f.write(hash_val)

def send_to_amqp(amqp_url, message):
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    
    channel = connection.channel()
    channel.basic_publish(exchange='outlook', routing_key='', body=message)
    print(f"Sent outlook to AMQP ({len(message)} bytes)")
    connection.close()

def check_for_updates(amqp_url):
    print(f"[{datetime.now()}] Checking for new JSON outlooks...")
    try:
        json_files = get_json_files()
        if not json_files:
            print("No JSON files found.")
            return

        latest_file = json_files[-1]
        full_url = urljoin(BASE_URL, latest_file)
        content = download_file(full_url)

        new_hash = compute_hash(content)
        last_hash = read_last_hash()

        if new_hash != last_hash:
            print(f"New outlook found: {latest_file}")
            send_to_amqp(amqp_url, content)
            write_last_hash(new_hash)
        else:
            print("No new outlook.")
    except Exception as e:
        print(f"Error checking outlooks: {e}")

def start_monitoring():
    time.sleep(10)
    
    amqp_url = get_amqp_url()
    check_for_updates(amqp_url)

    def loop():
        while True:
            time.sleep(CHECK_INTERVAL)
            check_for_updates(amqp_url)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")


