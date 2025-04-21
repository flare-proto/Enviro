import os,logging,re,json,sqlite3
import merge as mg
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient
import xml.etree.ElementTree as ET
from dateutil import parser
logging.basicConfig(level=logging.INFO)


import datetime,requests
from bs4 import BeautifulSoup

issu = ("CWNT","CWWG","CWVR")

alerts_in_effect = {}
lookback = 24

def setup():
    c = sqlite3.connect("alert.db")
    c.execute("CREATE TABLE if not exists  `Alerts` (`key` INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE, `id` TEXT UNIQUE, `data` TEXT)")
    c.execute("CREATE TABLE if not exists  `formattedAlert` (`id` TEXT PRIMARY KEY UNIQUE, `begins` TEXT, `ends` TEXT, `areas` TEXT, `urgency` TEXT, `references` TEXT, `msgType` TEXT, `type` TEXT,`desc` TEXT)")
    c.close()
    logging.info("PCAP setup")

def get_url_paths(url, ext='', params={}):
    response = requests.get(url, params=params)
    if response.ok:
        response_text = response.text
    else:
        return []
    soup = BeautifulSoup(response_text, 'html.parser')
    parent = [(url + node.get('href'),node.get('href')) for node in soup.find_all('a') if node.get('href').endswith(ext)]
    return parent

types = {
    "snowfall":      0b00000001,
    "blizzard":      0b00000010,
    "tornado":       0b00000100,
    "blowing snow":  0b00001000,
    "freezing rain": 0b00010000,
    "fog":           0b00100000,
    "wind":          0b01000000,
    "arctic outflow":0b10000000
}

def extract_urns(data: str):
    """
    Extract all `urn:oid` patterns from the given string.

    Args:
        data (str): The input string containing `urn:oid` patterns.

    Returns:
        list: A list of all `urn:oid` patterns found in the string.
    """
    # Regular expression to match `urn:oid` patterns
    urn_pattern = r"urn:oid:[\w\d\.\-]+"
    return re.findall(urn_pattern, data)


def parse_cap(content: str) -> dict:
    """
    Parse a CAP file and extract relevant information, removing alerts referenced in `references`.

    Args:
        file_path (str): The path to the CAP XML file.

    Returns:
        dict: A dictionary containing alert information if the alert is valid and not referenced, otherwise None.
    """
    try:
        # Read the file with error handling for encoding issues
        
        
        # Parse the XML content
        root = ET.fromstring(content)
        
        # CAP namespace handling
        ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
        
        # Extract relevant fields
        status = root.find('cap:status', ns).text  # Example: "Actual"
        msgType = root.find('cap:msgType', ns).text
        expires = root.find('cap:info/cap:expires', ns).text  # Example: "2024-12-21T12:00:00-00:00"
        response_type = root.find('cap:info/cap:responseType', ns)
        response_type = response_type.text if response_type is not None else None

        # Effective time is optional
        effective_element = root.find('cap:info/cap:effective', ns)
        effective_time = (
            parser.isoparse(effective_element.text).replace(tzinfo=datetime.timezone.utc)
            if effective_element is not None
            else None
        )

        # Expiry time
        expires_time = parser.isoparse(expires).replace(tzinfo=datetime.timezone.utc)
        current_time = datetime.datetime.now(datetime.timezone.utc)
        
        # Extract the alert identifier and references
        identifier = root.find('cap:identifier', ns).text
        event = root.find('cap:info/cap:event', ns).text
        references_element = root.find('cap:references', ns)

        # Extract OIDs from references (the second element in each reference entry)
        reference_ids = extract_urns(references_element.text or "")
        
        areas = []
        for area in root.findall('.//cap:area', ns):
            # If the area is a polygon
            polygon_element = area.find('cap:polygon', ns)
            if polygon_element is not None:
                polygon_coords = polygon_element.text.strip().split()
                # Convert to list of tuples
                coordinates = [(tuple(map(float, coord.split(','))))[::-1] for coord in polygon_coords]
                polygon = Polygon(coordinates)
                if polygon.is_valid:
                    areas.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [list(polygon.exterior.coords)]
                        },
                        "properties": {"warn":event}
                    })
        # Check if the alert is in effect
        if current_time >= expires_time:
            logging.info(f"Alert {identifier} expired at {expires_time}, current time: {current_time}")

            return
        elif effective_time is not None and effective_time >= current_time:
            logging.info(f"Alert {identifier} is upcoming, starts in {effective_time - current_time}")
            return
        elif status == "Actual":# and (effective_time is None or effective_time <= current_time) and current_time <= expires_time:
            return {
                "status": status,
                "effective": effective_element.text if effective_element is not None else None,
                "expires": expires,
                "identifier": identifier,
                "sender": root.find('cap:sender', ns).text,
                "responseType": response_type,
                "references": reference_ids,
                "headline": root.find('cap:info/cap:headline', ns).text,
                "description": root.find('cap:info/cap:description', ns).text,
                "areas":areas,
                "msgType":msgType,
                "type":event,
                "urgency": root.find('cap:info/cap:urgency', ns).text,
            }
        
    except ET.ParseError as e:
        logging.error(f"XML parsing error in: {e}")
    #except Exception as e:
    #    print(f"Error parsing: {e}")
    return None


def filter_referenced_alerts(alerts: list[dict]) -> list[dict]:
    """
    Filter out alerts that are referenced by other alerts based on OID in references.

    Args:
        alerts (list[dict]): A list of parsed CAP alerts.

    Returns:
        list[dict]: Alerts excluding those with identifiers in references.
    """
    # Collect all referenced OIDs from the alerts
    referenced_ids = {(ref for ref in alert.get("references", [])) for alert in alerts}
    
    # Filter alerts that are not referenced
    return [alert for alert in alerts if alert["identifier"] not in referenced_ids]

def get_in_effect_alerts(cap_folder: str) -> list:
    """
    Get all alerts in effect from CAP XML files in a given folder.

    Args:
        cap_folder (str): The path to the folder containing CAP XML files.

    Returns:
        list: A list of dictionaries containing "in effect" alerts, with updates handled correctly.
    """
    alerts_in_effect = {}
    
    for file_name in os.listdir(cap_folder):
        file_path = os.path.join(cap_folder, file_name)
        if file_name.endswith('.cap'):
            logging.debug(f"found {file_name}")
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                alert = parse_cap(content)
                if alert:
                    alert_id = alert["identifier"]
                    
                    # Handle updates
                    if alert_id in alerts_in_effect:
                        # If the new alert has "AllClear", remove the previous alert
                        
                        if alert.get("responseType") == "AllClear":
                            for r in alert.get("references"):
                                del alerts_in_effect[r]
                            del alerts_in_effect[alert_id]
                        else:
                            # Otherwise, replace the old alert with the new one
                            alerts_in_effect[alert_id] = alert
                            for r in alert.get("references"):
                                del alerts_in_effect[r]#["expires"] = alert["expires"]
                            logging.debug(f"updated {alert_id}")
                    else:
                        # Add the new alert if it's not already tracked
                        alerts_in_effect[alert_id] = alert
                        for r in alert.get("references"):
                            del alerts_in_effect[r]#["expires"] = alert["expires"]
    
    
    return list(alerts_in_effect.values())

def get_in_effect_alerts_web(cap: list[str]) -> list:
    """
    Get all alerts in effect from CAP XML files in a given folder.

    Args:
        cap_folder (str): The path to the folder containing CAP XML files.

    Returns:
        list: A list of dictionaries containing "in effect" alerts, with updates handled correctly.
    """
    for dat in cap:
        conn = sqlite3.connect("alert.db")
        cur = conn.cursor()
        alert = parse_cap(dat)
        if alert:
            alert_id = alert["identifier"]
            
            # Handle updates
            if alert_id in alerts_in_effect:
                # If the new alert has "AllClear", remove the previous alert
                
                if alert.get("responseType") == "AllClear":
                    for r in alert.get("references"):
                        try:
                            del alerts_in_effect[r]
                        except: pass
                    del alerts_in_effect[alert_id]
                else:
                    # Otherwise, replace the old alert with the new one
                    cur.execute("INSERT or replace INTO formattedAlert (id,begins,ends,urgency,msgType,type) VALUES (?,?,?,?,?,?)",
                                (alert_id,alert["effective"],alert["expires"],alert["urgency"],alert["msgType"],alert["type"]))
                    alerts_in_effect[alert_id] = alert
            else:
                # Add the new alert if it's not already tracked
                alerts_in_effect[alert_id] = alert
                cur.execute("INSERT or replace INTO formattedAlert (id,begins,ends,urgency,[references],msgType,type) VALUES (?,?,?,?,?,?,?)",
                                (alert_id,alert["effective"],alert["expires"],alert["urgency"],json.dumps(alert["references"]),alert["msgType"],alert["type"]))
            conn.commit()
            conn.close()
    with open("OUT.json","w") as f:
        json.dump(list(alerts_in_effect.values()),f)
    return list(alerts_in_effect.values())
def cache(sql:sqlite3.Cursor,url):
    sql.execute("SELECT EXISTS(SELECT 1 FROM Alerts WHERE id=?)",(url,))
    fth =  sql.fetchone()
    if not fth[0]:
        logging.info(url)
        R = requests.get(url)
        sql.execute("INSERT or replace INTO Alerts (id,data) VALUES (?,?)",(url,R.text))
        return R.text
    else:
        sql.execute("SELECT data FROM Alerts WHERE id=?",(url,))
        fth =  sql.fetchone()
        return fth[0]
def fetch():
    global lookback
    t = datetime.datetime.now(datetime.timezone.utc)
    dat = []
    for i in range(lookback,0,-1):
        T = datetime.timedelta(hours=i)
        d = t-T
        #print(f"{d.day} -> {d.hour}")
        
        for iss in issu:
            conn = sqlite3.connect("alert.db")
            cur = conn.cursor()
            url = f'https://dd.weather.gc.ca/{d.year}{d.month:>02}{d.day:>02}/WXO-DD/alerts/cap/{d.year}{d.month:>02}{d.day:>02}/{iss}/{d.hour:>02}/'
            result: list[str] = get_url_paths(url, "cap")
            #for p in prov:
            #    print(f"{d.year}{d.month}{d.day}/CWNT/{d.hour}/T_{p}CN")
            for r,name in result:
                R = cache(cur,r)
                dat.append(R)
            conn.commit()
            conn.close()
    lookback = 1
    d = get_in_effect_alerts_web(dat)
    
    return d
def merge(alerts):
    areas = []
    for a in alerts:
        for A in a["areas"]:
            areas.append(A)
    print(areas)
    return mg.merge_polygons_by_warn({
        "type": "FeatureCollection",
        "features": areas
    })
## Example usage
#cap_folder = "cap/"  # Replace with the actual path
#alerts = get_in_effect_alerts(cap_folder)
#
#for alert in alerts:
#    print(alert)
