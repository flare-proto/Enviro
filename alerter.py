import logging,pika,json,datetime,pytz
from dateutil import parser
testSrv = pika.URLParameters("amqp://alert:alert@10.0.0.41")

urgent_alerts = {
    "tornado",
    "severe thunderstorm",
    "blizzard",
    "extreme cold",
    "heat"
}

PDS = {
    "tornado",
    "blizzard"
}

issu = {
    "cap-pac@canada.ca":"Enviroment Canada"
}
directions = {
    "tornado":"""Take shelter immediately, preferably in the lower level of a sturdy building, Idealy in a basement or interior roof far from windows.
    If caught outdoors with no shelter available, lie flat in a ditch, ravine or other low-lying area and shield your head with your arms.
    If you see a tornado, and it does not appear to be moving, it is likely either moving straight away from you or straight towards you.
    There is not a strong correlation between the physical size of a tornado and its maximum wind speed. All tornadoes, regardless of appearance, are potentially lethal threats.""",
    "severe thunderstorm":"""When thunder roars, GO INDOORS. If you cannot find a sturdy, fully enclosed building with wiring and plumbing, get into a metal-roofed vehicle. Stay inside for 30 minutes after the last rumble of thunder.
Once indoors, stay away from electrical appliances and equipment, doors, windows, fireplaces, and anything else that will conduct electricity, such as sinks, tubs and showers. Avoid using a telephone connected to a landline.
If you are in your car during lightning, do not park under tall objects that could fall, and do not get out if there are fallen power lines nearby.
If you are caught outside, do not stand near tall objects or anything made of metal, and avoid open water. Take shelter in a low-lying area.
If caught on the water in a small boat with no cabin during thunder and lightning, quickly get to shore. Boats with cabins offer a safer environment, but it is still not ideal.
Remember that there is no safe place outdoors during a thunderstorm. Once in a safe location, remain there for 30 minutes after the last rumble of thunder you hear before resuming your outdoor activities."""
}

template = """ENVIROTRON ALERT
At {Time}, {Issu} issued a {alert} warning
{directions}
{description}"""

connection = pika.BlockingConnection(testSrv)
channel = connection.channel()

result = channel.queue_declare(queue='', exclusive=True)
channel.queue_bind(exchange='alert',
                   queue=result.method.queue)

print(' [*] Waiting for logs. To exit press CTRL+C')

def convert(dte, fromZone, toZone):
    fromZone, toZone = pytz.timezone(fromZone), pytz.timezone(toZone)
    return fromZone.localize(dte, is_dst=True).astimezone(toZone)

def callback(ch, method, properties, body):
    b = body.decode()
    #print(f" [x] {body}")
    dat = json.loads(b)
    if dat["type"] == "Alert":
        if dat["alert"]["type"] in urgent_alerts:
            time = parser.isoparse(dat["alert"]["effective"]).replace(tzinfo=datetime.timezone.utc).astimezone(pytz.timezone("US/Mountain"))
            alertText = template.format(
                PDS=str(dat["alert"]["type"] in PDS),
                Time=time.strftime("%H:%M"),
                Issu=issu.get(dat["alert"]["sender"],"Enviroment Canada, or other external body"),
                alert=dat["alert"]["type"],
                directions = directions.get(dat["alert"]["type"],""),
                description=dat["alert"]["description"]
            )
            print(alertText)
            channel.basic_publish(exchange='alerting', routing_key='', body=alertText)

channel.basic_consume(
    queue=result.method.queue, on_message_callback=callback, auto_ack=True)

channel.start_consuming()