import logging

import pika
import pika.connection

class ConnHandler(logging.Handler):
    def __init__(self, ch):
        super().__init__()
        self.ch = ch

    def emit(self, record):
        log_entry = self.format(record)
        self.ch.basic_publish("","log",log_entry,pika.BasicProperties(content_type='text/plain',
                                           delivery_mode=pika.DeliveryMode.Transient))