import eventlet

eventlet.monkey_patch()

import subprocess
import threading
import time

import alertExchange
import downloader
import outlook

ans = subprocess.Popen(["python","server.py"])
time.sleep(5)
threading.Thread(name="AX",target=alertExchange.start_cap_topic_relay, daemon=True).start()
threading.Thread(name="DL",target=downloader.downloader, daemon=True).start()
threading.Thread(name="TO",target=outlook.start_outlook_watcher, daemon=True).start()
ans.wait()
