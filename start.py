import server
import threading
import time

import alertExchange
import downloader
import outlook

dataSync = threading.Condition()

server.startServer(dataSync)

dataSync.wait()

threading.Thread(target=alertExchange.start_cap_topic_relay, daemon=True).start()
threading.Thread(target=downloader.downloader, daemon=True).start()
threading.Thread(target=outlook.start_outlook_watcher, daemon=True).start()

