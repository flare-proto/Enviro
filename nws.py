import requests
import time
import json
import pika

def fetch_alerts(area=None, limit=10):
    url = "https://api.weather.gov/alerts"
    params = {
        'status': 'actual',
        'limit': limit,
        'sort': 'sent',
    }
    if area:
        params['area'] = area

    headers = {
        'User-Agent': 'MyWeatherApp (youremail@example.com)',
        'Accept': 'application/ld+json'
    }

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    return response.json().get('features', [])

def connect_to_amqp(host='localhost', queue='nws_alerts'):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host))
    channel = connection.channel()
    channel.queue_declare(queue=queue, durable=True)
    return connection, channel

def publish_alert(channel, queue, alert):
    payload = {
        'id': alert['id'],
        'event': alert['properties']['event'],
        'urgency': alert['properties']['urgency'],
        'severity': alert['properties']['severity'],
        'certainty': alert['properties']['certainty'],
        'areaDesc': alert['properties']['areaDesc'],
        'effective': alert['properties']['effective'],
        'expires': alert['properties']['expires'],
        'headline': alert['properties']['headline'],
        'description': alert['properties']['description'],
        'instruction': alert['properties']['instruction'],
    }

    channel.basic_publish(
        exchange='',
        routing_key=queue,
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            delivery_mode=2,  # make message persistent
        )
    )
    print(f"[>] Published alert to AMQP: {payload['event']}")

def poll_alerts_to_amqp(area=None, poll_interval=60, amqp_host='localhost', amqp_queue='nws_alerts'):
    seen_ids = set()
    conn, channel = connect_to_amqp(host=amqp_host, queue=amqp_queue)

    while True:
        try:
            alerts = fetch_alerts(area=area, limit=20)
            new_alerts = [a for a in alerts if a['id'] not in seen_ids]

            for alert in new_alerts:
                seen_ids.add(alert['id'])
                publish_alert(channel, amqp_queue, alert)

            time.sleep(poll_interval)
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(poll_interval)

# Example usage:
if __name__ == "__main__":
    poll_alerts_to_amqp(area='CA', poll_interval=60, amqp_host='localhost', amqp_queue='nws_alerts')
