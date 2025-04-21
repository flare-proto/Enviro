import subprocess
import threading

import alertExchange
import downloader
import outlook

ans = subprocess.Popen(["python","server.py"])
threading.Thread(target=alertExchange.start_cap_topic_relay, daemon=True).start()
threading.Thread(target=downloader.downloader, daemon=True).start()
threading.Thread(target=outlook.start_outlook_watcher, daemon=True).start()
ans.wait()
