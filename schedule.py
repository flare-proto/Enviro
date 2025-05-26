from apscheduler.schedulers.background import BackgroundScheduler
import dbschema

def on_alert_goes_into_effect(alert:dbschema.Alert):
    alert_channel.basic_publish(
        exchange='feed',
        routing_key=f"SH.{alert['event']}",
        body=alert["broadcast_message"]
    )

def schedule_alert(alert):
    run_time = alert.effective_at
    scheduler.add_job(on_alert_goes_into_effect, 'date', run_date=run_time, args=[alert])

# After creating a new alert:
schedule_alert(new_alert)