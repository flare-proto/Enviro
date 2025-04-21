import server
import threading
import time

import alertExchange
import downloader
import outlook

dataSync = threading.Condition()

threading.Thread(target=server.startServer, daemon=True,args=(dataSync,)).start()

dataSync.wait()

threading.Thread(target=alertExchange.start_cap_topic_relay, daemon=True).start()
threading.Thread(target=downloader.downloader, daemon=True).start()
threading.Thread(target=outlook.start_outlook_watcher, daemon=True).start()

