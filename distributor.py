import configparser
import json
import sched
import time
from datetime import datetime
from threading import Thread

import pika

config = configparser.ConfigParser()
config.read("config.ini")

# Global scheduler
scheduler = sched.scheduler(timefunc=time.time, delayfunc=time.sleep)

def issue(alert_data, channel):
    """Send the alert to the 'alerts.out' queue."""
    channel.basic_publish(
        exchange='feed',
        routing_key=f"BRODCAST.active.{alert_data.get('event')}",
        body=json.dumps(alert_data)
    )
    print(f"[{datetime.now().isoformat()}] Issued alert: {alert_data.get('event')}")

def handle_alert(ch, method, properties, body):
    """Process an incoming alert message."""
    try:
        alert = json.loads(body)
        urgency = alert.get("urgency", "immediate").lower()
        effective_str = alert.get("effective_time")
        if not effective_str:
            raise ValueError("Missing effective_time in alert")

        effective_time = datetime.fromisoformat(effective_str)

        if urgency == "immediate" or effective_time <= datetime.now():
            issue(alert, ch)
        else:
            delay = (effective_time - datetime.now()).total_seconds()
            scheduler.enter(delay, 1, issue, argument=(alert, ch))
            print(f"[{datetime.now().isoformat()}] Scheduled alert: {alert.get('event')} at {effective_time.isoformat()}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Failed to process alert: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_scheduler():
    """Run the scheduler loop in a separate thread."""
    def run():
        while True:
            scheduler.run(blocking=False)
            time.sleep(1)
    Thread(target=run, daemon=True).start()

def main():
    """Main AMQP setup and consumer start."""
    connection = pika.BlockingConnection(pika.URLParameters(config["feed"]["amqp"]))
    channel = connection.channel()

    # Declare queues
    channel.queue_declare(queue='BRODCAST.intake', durable=True,exclusive=True)
    channel.queue_bind(queue='BRODCAST.intake',exchange="feed",routing_key="*.queue.*")

    start_scheduler()

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='BRODCAST.intake', on_message_callback=handle_alert)

    print(" [*] Waiting for alerts. Press Ctrl+C to exit.")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Shutting down...")
        channel.stop_consuming()
        connection.close()

if __name__ == "__main__":
    main()
