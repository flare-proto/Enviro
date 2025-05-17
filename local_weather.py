import asyncio
import configparser
import datetime
import json
import logging
import threading
import time

from env_canada import ec_weather

import coloredlogs
import pika
import pika.channel
import pika.frame
import pika.spec
import requests
from bs4 import BeautifulSoup

import connLog

config = configparser.ConfigParser()
config.read("config.ini")

def run():
    logger = logging.Logger("WX")
    testSrv = pika.URLParameters(config["downloader"]["amqp"])
    connParam = pika.ConnectionParameters(testSrv.host,testSrv.port,credentials=testSrv.credentials,heartbeat=0)

    connection = pika.BlockingConnection(connParam)
    channel = connection.channel()
    chnd = connLog.ConnHandler(channel)
    formatter = coloredlogs.ColoredFormatter('WX - %(asctime)s - %(levelname)s - %(message)s')
    chnd.setFormatter(formatter)
    logger.addHandler(chnd)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    def callback(ch:pika.channel.Channel, method:pika.spec.Basic.Deliver, properties:pika.spec.BasicProperties, body):
        #TODO get data
        ch.basic_publish(exchange='',
                     routing_key=properties.reply_to,
                     properties=pika.BasicProperties(correlation_id = \
                                                         properties.correlation_id),
                     body=str(""))
        ch.basic_ack(delivery_tag=method.delivery_tag)
    
    channel.queue_declare(queue='rpc_local_weather',exclusive=True)
    channel.queue_bind(exchange='feed',
                    queue="rpc_local_weather",routing_key="conditions.local.rpc.ca")
    
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='rpc_local_weather', on_message_callback=callback)