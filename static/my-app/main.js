import './style.css';
import Feature from 'ol/Feature.js';
import {Map, View} from 'ol';
import {Vector,TileWMS} from 'ol/source.js';
import {Icon,Style,Stroke} from 'ol/style.js';
import {Tile as TileLayer, Vector as VectorLayer} from 'ol/layer.js';
import {DEVICE_PIXEL_RATIO} from 'ol/has.js';
import OSM from 'ol/source/OSM';
import Overlay from "ol/Overlay"
import {Point,LineString} from 'ol/geom';
import {fromLonLat,useGeographic} from 'ol/proj.js';
import VectorImageLayer from 'ol/layer/VectorImage.js';
//import VectorLayer from 'ol/layer/Vector.js';
import VectorSource from 'ol/source/Vector.js';
import GeoJSON from 'ol/format/GeoJSON.js';
import Fill from 'ol/style/Fill.js'; //TODO REMOVE ME

const pixelRatio = DEVICE_PIXEL_RATIO;

let container = document.getElementById("popup");
let content_element = document.getElementById("popup-content");
let viewInfo = document.getElementById("viewInfo");
let selectedInfo = document.getElementById("selectedInfo");
let closer = document.getElementById("popup-closer");
let activeAlert = 1;

var saturation = 100
var brightness = 100

//region main
let warnsls = document.getElementById("warns");
//eel.expose(prompt_alerts);
function prompt_alerts(description) {
  alert(description);
}



//eel.expose(alerts_warn);
/*function alerts_warn(type,id,title) {
  let a = document.createElement("div")
  a.classList.add(type)
  a.id = id
  a.innerHTML = `<h3>${title}</h3>`
  document.getElementById(`${type}`).appendChild(a)
}*/

//eel.expose(temps);
function temps(stat,wind) {
  sc.innerText = `${stat}°C`;
  wc.innerText = `${wind}°C`;
}
//eel.expose(winds);
function winds(speed,hddn) {
  wnd.innerText = `${speed} km/h @ ${hddn}°`;
}
//eel.expose(refr);
function refr(description) {
  document.getElementById("cntr").innerHTML = "<img "
}
var timeDisplay = document.getElementById("time");
var dateDisplay = document.getElementById("date");
var timeDisplayL = document.getElementById("timeLocal");
var dateDisplayL = document.getElementById("dateLocal");

function refreshTime() {
  var d= new Date();
  var dateString = new Date().toLocaleString("en-US",);
  var formattedString = dateString.replace(", ", " - ");
  formattedString = `${d.toLocaleTimeString("en-CA",{hour12: false,second: '2-digit',hour: '2-digit', minute:'2-digit',timeZone: 'UTC'})}Z`
  timeDisplay.innerHTML = formattedString;
  dateDisplay.innerHTML = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
  dateDisplayL.innerHTML = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  timeDisplayL.innerHTML = `${d.toLocaleTimeString("en-CA",{hour12: false,hour: '2-digit', minute:'2-digit',second: '2-digit'})}`
}

setInterval(refreshTime, 1000);

function httpGet(theUrl)
{
    var xmlHttp = new XMLHttpRequest();
    xmlHttp.open( "GET", theUrl, false ); // false for synchronous request
    xmlHttp.send( null );
    return xmlHttp.responseText;
}

var cntr = document.getElementById("cntr");
function update(url) {
  cntr.innerHTML = httpGet(url)
}
//endregion

//region alerts

let sc = document.getElementById("temps");
let wc = document.getElementById("temps_wind");
let cnd = document.getElementById("cond");
let wnd = document.getElementById("wind");
var warns = {
    "TSTORM":" ",
    "TORNADO":" 󰼸",
    "HEAT":" ",
    "SNOW":"󰼩",
    "COLD":""
}
var watch = {
    "TSTORM":"󰼯 ",
    "TORNADO":"󰼯 󰼸",
}

//TODO REMOVE ME
var prioritys = [
    "warns.TORNADO",
    "watch.TORNADO",
    "warns.SNOW",
    "warns.TSTORM",
    "watch.TSTORM",
    "warns.HEAT",
    "warns.COLD",
    "test"
]
var alerts= {
    "NONE": {
        "bg":"#333",
    },
    "test":{
        "bg":"#119911",
        "symbols": ' ',
        "text":"TEST",
        "class":"test",
        "color":"#FFFFFF"
    }
}
for (const key in warns) {
    const element = warns[key];
    
    alerts[`warns.${key}`]={
        "class":"warnings",
        "bg":"red",
        "symbols": element,
        "text":key,
        "color":"#FFFFFF"
    }
}
for (const key in watch) {
    const element = watch[key];
    
    alerts[`watch.${key}`]={
        "class":"watches",
        "bg":"yellow",
        "symbols": element,
        "text":key,
        "color":"#333"
    }
}

const weatherTypes = {
  cloudy: "󰖐",
  fog:"󰖑",
  hail:"󰖒",
  lightning:"󰖓",
  pouring:"󰖖",
  raining:"󰖗",
  snowing:"󰖘",
  clear:"󰖙",
  tornado:"󰼸",
  windy:"󰖝",
  snowwind:"󰜗󰖝",
  thunderstorm:"󰙾",
  partlyCloudy:"󰖕",
  snowrain:"󰙿",
  partcloud:"󰖕",
  err:"󰼯",
  moonclear:"󰖔"
}

var top_alert = document.getElementById("topWarn");
var alertIcon = document.getElementById("warn");
var alertType = document.getElementById("warnType");
var curAlert = "NONE"
var prev = alerts[curAlert]
var alertData = alerts[curAlert]
function setAlertLayout() {
    var intr = 0;
    intr = setInterval(() => {
        top_alert.style.setProperty("--prev",alertData.bg)
        top_alert.style.setProperty("--side","left")
        clearInterval(intr)
    },501)
}

function setAlert(alert) {
    prev = alerts[curAlert]
    alertData = alerts[alert]
    top_alert.style.setProperty("--side","right")
    if (alert == "NONE") {
        
        top_alert.setAttribute("type","NONE")
        top_alert.style.setProperty("--prev",prev.bg)
        top_alert.style.setProperty("--cur",alertData.bg)
        top_alert.style.setProperty("--col","#FFFFFF")
        alertIcon.innerText = ""
        alertType.innerText = ""
    } else {
        
        //top_alert.style.background = "linear-gradient(to left, yellow 50%, red 50%) right"
        
        
        top_alert.setAttribute("type","")
        top_alert.style.setProperty("--prev",prev.bg)
        top_alert.style.setProperty("--cur",alertData.bg)
        top_alert.style.setProperty("--col",alertData.color)

        //top_alert.class = `${alertData.class} twoLineData`
        //top_alert.classList[0] = alertData.class
        alertIcon.innerText = alertData.symbols
        alertType.innerText = alertData.text
        
    }
    setAlertLayout();

    curAlert = alert
}


var active = new Set();
var types = [
    "warnings",
    "watches",
    "advisories",
    "statements",
    "endings"
]
function alerts_warn(type,id,title) {
    let a = document.createElement("div")
    a.classList.add(type)
    a.id = id
    a.innerHTML = `<h3>${alerts[id]["symbols"]} ${title}</h3>`
    document.getElementById(`${type}`).appendChild(a)
  }

var qrhTbl =document.getElementById("qrhTbl")
for (var element in weatherTypes) {
  var icon = weatherTypes[element]
  qrhTbl.innerHTML += `<tr><td>${icon}</td><td>${element.toUpperCase()}</td></tr>`
}

//endregion

//region datapane

var checks = document.getElementById('checks')
function makeBind(name) {
    var elem = document.getElementById(name)
    var data = document.createElement("p");
    var check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !elem.hidden;
    data.innerText = name;
    //data.appendChild(check);
    data.insertAdjacentElement("afterbegin",check)
    checks.appendChild(data)
    

    check.addEventListener('change', (event) => {
        elem.hidden = !event.currentTarget.checked
      })
}
makeBind("shear")
makeBind("MUCAPE")
makeBind("VORT")
makeBind("DEW")
makeBind("MOIST")
makeBind("DIVERG")
//endregion



async function getRadarStartEndTime() {
  let response = await fetch('https://geo.weather.gc.ca/geomet/?lang=en&service=WMS&request=GetCapabilities&version=1.3.0&LAYERS=RADAR_1KM_RRAI&t=' + new Date().getTime())
  let data = await response.text().then(
    data => {
      let xml = parser.parseFromString(data, 'text/xml');
      let [start, end] = xml.getElementsByTagName('Dimension')[0].innerHTML.split('/');
      let default_ = xml.getElementsByTagName('Dimension')[0].getAttribute('default');
      return [start, end, default_];
    }
  )
  return [new Date(data[0]), new Date(data[1]), new Date(data[2])];
}

const vectorLayer = new VectorImageLayer({
  background: '#00000000',
  imageRatio: 2,
  source: new VectorSource({
    url: 'https://api.weather.gc.ca/collections/public-standard-forecast-zones/items?f=json',
    format: new GeoJSON(),
  }),
  style: {
    'stroke-color': "#000000",
    'stroke-width': 0.5,
  }
});

const warnTextShow = [
  "snowfall",
  "blowing snow advisory",
  "winter storm",
  "blizzard",
  "snow squall",
  "waterspout",
  "tornado"
]

const watch_alert = [
  "squall",
  "blowing snow advisory",
  "weather"
]

const warnColors = {
  "snowfall":"#00ffff",
  "blowing snow advisory":"#008fbb",
  
  "winter storm":"#67c9bc",
  
  "blizzard":"#3f92d1",
  "snow squall":"#00e5ff",
  "squall":"#33e5ff",
  
  "arctic outflow":"#03c2fc",
  "extreme cold":"#0004ff",

  "freezing rain":"#332dbf",
  "fog":"#80a1ba",
  "rainfall":"#00ff00",
  
  

  "weather":"#595959",
  "wind":"#ffa200",
  "waterspout":"#F03500",
  "special marine":"#D06018",

  "thunderstorm":"#ffee00",
  "tornado":"#FF0000",
  "air quality":"#CCCCCC"

}

function makeStyle() {
  var legend =document.getElementById("legend")
  var s = []
  for (var element in warnColors) {
    var col = warnColors[element]
    legend.innerHTML += `<tr><td style="background-color: ${col};">~</td><td>${element.toUpperCase()}</td></tr>`
    s.push({
      filter: ['==', ['get', 'warn'],element],
      style: {
        //"fill-color":"#03c2fc55",
        'stroke-color': col,
        'stroke-width': 1.5,
      }
    })
  }
  s.push({
    else:true,
    style: {
      "fill-color":"#FFFFFFF1",
      'stroke-color': "#00000077",
      'stroke-width': 5,
    }
  })
  return s
}
makeStyle()

function createPatternFill(text,color,nf) {
  const canvas = document.createElement('canvas');
  canvas.width = 250;
  canvas.height = 250;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = color
  ctx.font = "20px NerdSpace"
  if (warnTextShow.includes(text) || nf) {
    ctx.fillText(text,5,125)
  }

  const pattern = ctx.createPattern(canvas, 'repeat');

  return new Fill({
    color: pattern
  });
}

function style_feature_alert(feature, resolution) {
  const text = feature.get('warn') || 'Region'; // Or any other attribute
  var wc = warnColors[text];
  var fill = "rgba(0,0,0,0)"
  var nf = false;
  if (!wc) {
    fill = "#FFFFFFFF",
    wc = "#AAAAAA"
    nf = true
  }
  var stroke;
  if (watch_alert.includes(text)) {
    stroke = new Stroke({
      color: wc,
      width: 1.5,
      lineDash: [5, 3,5]  // ← This creates the dashed effect
    })
  } else {
    stroke = new Stroke({ color: wc, width: 1.5 })
  }
  return new Style({
    fill: createPatternFill(text,wc,nf),//new Fill({ color: fill }),
    stroke: stroke,
    
  });
}

const alerts_layer = new VectorImageLayer({
  background: '#00000000',
  imageRatio: 2,
  source: new VectorSource({
    url: '/api/geojson',
    format: new GeoJSON(),
  }),
  style: style_feature_alert
});

const alertsO_layer = new TileLayer({
  opacity: 0.4,
  source: new TileWMS({
    url: 'https://geo.weather.gc.ca/geomet/',
    params: {'LAYERS': 'ALERTS', 'TILED': true},
    transition: 0
  })
})
const radar_layer = new TileLayer({
  opacity: 0.4,
  source: new TileWMS({
    url: 'https://geo.weather.gc.ca/geomet/',
    params: {'LAYERS': 'RADAR_1KM_RRAI', 'TILED': true},
    transition: 0
  })
})

function styleFunction(feature) {
  const severity = feature.get('metobject')?.severity?.value;

  let fillColor = 'gray'; // default
  let strokeColor = 'gray'; // default
  if (severity === 'extreme') {
    fillColor = '#FF000088';
    strokeColor = '#FF0000';
  }else if (severity === 'high') {
    fillColor = '#FFAA0088';
    strokeColor = '#FFAA00';
  } else if (severity === 'moderate') {
    fillColor = '#FFFF0088';
    strokeColor = '#FFFF00';
  } else if (severity === 'minor') {
    fillColor = '#00FF0088';
    strokeColor = '#00FF00';
  }

  return new Style({
    stroke: new Stroke({
      color: strokeColor,
      width: 3,
    }),
    fill: new Fill({
      color: fillColor,
    }),
  });
}

const outlook_layer = new VectorImageLayer({
  opacity: 1,
  source: new VectorSource({
    url: '/api/outlook',
    format: new GeoJSON(),
  }),
  style: styleFunction
})

radar_layer.getSource().on("imageloaderror", () => {
  getRadarStartEndTime().then(data => {
    currentTime = startTime = data[0];
    endTime = data[1];
    defaultTime = data[2];
    updateLayers();
    updateInfo();
    updateButtons();
  })
});




function updateLayers() {
  radar_layer.getSource().updateParams({'TIME': currentTime.toISOString().split('.')[0]+"Z"});
  //radar_layer.getSource().updateParams({'TIME': currentTime.toISOString().split('.')[0]+"Z"});
}


/**
 * Create an overlay to anchor the popup to the map.
 */
let overlay = new Overlay({
  element: container,
  autoPan: true,
  autoPanAnimation: {
    duration: 250
  }
});


var lpings = document.getElementById("locPing");

const tile = new TileLayer({
  source: new OSM()
});
tile.on('prerender', (evt) => {
  // return
  if (evt.context) {
    const context = evt.context;
    context.filter = `invert(100%) hue-rotate(180deg) saturate(${saturation}%) brightness(${brightness}%)`;
    context.globalCompositeOperation = 'source-over';
  }
});

tile.on('postrender', (evt) => {
  if (evt.context) {
    const context = evt.context;
    context.filter = 'none';
  }
});

//useGeographic()
const map = new Map({
  target: 'map',
  layers: [
    tile,
    vectorLayer,
    alerts_layer,
    alertsO_layer,
    radar_layer,
    outlook_layer
    
  ],
  overlays: [overlay],
  view: new View({
    center: fromLonLat([-114, 51]),
    zoom: 12
  })
});

var checks = document.getElementById('checks_map')
function makeBindLyr(name,o) {
    var data = document.createElement("p");
    var check = document.createElement("input");
    check.type = "checkbox";
    data.innerText = name;
    //data.appendChild(check);
    check.checked = o.getVisible()
    data.insertAdjacentElement("afterbegin",check)
    checks.appendChild(data)
    

    check.addEventListener('change', (event) => {
        o.setVisible(check.checked);
      })
    return function(vis) {
      o.setVisible(vis);
      check.checked = vis
    }
}
function makesat(name) {
  var data = document.createElement("p");
  var check = document.createElement("input");
  check.type = "checkbox";
  data.innerText = name;
  //data.appendChild(check);
  check.checked = false;
  data.insertAdjacentElement("afterbegin",check)
  checks.appendChild(data)
  

  check.addEventListener('change', (event) => {
      if (check.checked) {
        saturation = 5;
        brightness = 35;
      } else {
        saturation = 100;
        brightness = 100;
      }
    })
}
makeBindLyr("Alerts",alerts_layer)
makeBindLyr("ECCC Alerts",alertsO_layer)(false)
makeBindLyr("Bounds",vectorLayer)(false)
makeBindLyr("Radar",radar_layer)
makeBindLyr("Outlook",outlook_layer)
makesat("Desaturate")





/**
 * Add a click handler to hide the popup.
 * @return {boolean} Don't follow the href.
 */
closer.onclick = function () {
  overlay.setPosition(undefined);
  closer.blur();
  return false;
};

const selOpt = document.getElementById("selection")

map.on("singleclick", function (evt) {
  // reset state
  //nav.style.display = 'none'
  if (selOpt.value == "Alerts") {
    activeAlert = 1
    overlay.setPosition(undefined);
    // get coordinates
    let coordinate = evt.coordinate;
    let viewResolution = map.getView().getResolution();
    let wms_source = alertsO_layer.getSource();
    let url = wms_source.getFeatureInfoUrl(
      coordinate,
      viewResolution,
      "EPSG:3857", {
      INFO_FORMAT: "application/json",
      FEATURE_COUNT: 10
    }
    );
    console.log(url)
    if (url) {
      fetch(url)
        .then(function (response) {
          return response.json();
        })
        .then(function (json) {
          if (json.features.length > 0) {
            overlay.setPosition(evt.coordinate);
            let alerts = json.features.map((e, i) => {
              let alert_area = e.properties.area;
              let alert_headline = e.properties.headline;
              let alert_type = e.properties.alert_type;
              let alert_description = e.properties.descrip_en;
              let effective_datetime = e.properties.effective
              let expires_datetime = (e.properties.expires)
              return `
              <div id=alert-${i + 1} ${i > 0 ? "style='display: none;'" : ""}>
                <b>${alert_area}</b><br>
                <b><span style="text-transform: capitalize;">${alert_headline}<span></b><br><br>
                Alert type: <span style="text-transform: capitalize;">${alert_type}</span><br>
                Effective: ${effective_datetime}<br>
                Expires: ${expires_datetime}<br>
                <br>
                <div class="alert-descrip"><b>Description:</b> <br> ${alert_description}</div>
            </div>
            `;
            });
            if (json.features.length > 1) {
              navText.innerText = `${activeAlert} of ${json.features.length}`
              nav.style.display = 'flex';
              nav.style.justifyContent = 'center';
              nav.style.flexDirection = 'column';
              nav.style.alignItems = 'center';
            }
            let alerts_join = alerts.join("");
            content_element.innerHTML = alerts_join;
          }
        });
    }
  } else {
    var feature = map.forEachFeatureAtPixel(evt.pixel,
      function(feature, layer) {
        if (layer == outlook_layer) {
          return feature;
        }
      });
    if (feature) {
        var geometry = feature.getGeometry();
        var coord = geometry.getCoordinates();
        if (!viewInfo.classList.contains("visible")) {
          viewInfo.classList.toggle("visible")
        }
        var content = '<h3>' + feature.get('product_class') + ' Outlook</h3>';
        var tbl = document.createElement("table")
        
        tbl.innerHTML += '<tr><td>severity</td><td>' + feature.get('metobject').severity.value + '</td></tr>';
        tbl.innerHTML += '<tr><td>Thunderstorms</td><td>' + feature.get('metobject').thunderstorm.value + '</td></tr>';
        tbl.innerHTML += '<tr><td>rain</td><td>' + feature.get('metobject').rain.value +" "+feature.get('metobject').rain.unit+ '</td></tr>';
        tbl.innerHTML += '<tr><td>Hail</td><td>' + feature.get('metobject').hail.value +" "+feature.get('metobject').hail.unit+ '</td></tr>';
        tbl.innerHTML += '<tr><td>Gust</td><td>' + feature.get('metobject').gust.value +" "+feature.get('metobject').gust.unit+ '</td></tr>';
        
        selectedInfo.innerHTML = content;
        selectedInfo.appendChild(tbl)
        
        console.info(feature.getProperties());
    }
  }
});



var irtrv = () => {
  fetch("/api/alerts/top")
      .then((response) => response.json())
      .then((json) => {
          setAlert(json.mapped)
      });
      fetch("/api/conditions")
      .then((response) => response.json())
      .then((json) => {
          sc.innerText = `${json["temperature"]}°C`;
          if (json["wind_chill"]) {
            wc.innerText = `${json["wind_chill"]}°C`;
          }
          cnd.innerText = `${weatherTypes[json["icon_code"]]}`
          fetch("/api/conditions/bft")
              .then((rs) => rs.json())
              .then((bft) => {
                  wnd.innerText = `[ ${bft["icon"]} ] ${json["wind_speed"]} km/h at ${json["wind_bearing"]}°`
              })
      });
      fetch("/api/alerts")
        .then((response) => response.json())
        .then((json) => {
          for (const type of types) {
              document.getElementById(`${type}`).innerHTML = ""
          }
          if (json.length > 0) {
              for (const element of json) {
                  alerts_warn(element.class,element.mapped,element.title)
              }
          }

        });
}
setInterval(irtrv,15000)
irtrv()
setInterval(() => {
  alerts_layer.getSource().refresh()
  radar_layer.getSource().refresh()
},1000*5*60)


const ticker = document.getElementById('ticker');
const queue = [];

const currentconds = document.getElementById("currentconds")

const SCROLL_DURATION = 20000; // in milliseconds (10s = slower, longer scroll)

const socket = new WebSocket('/apiws/alertsws');

socket.addEventListener('open', () => {
  console.log('[WebSocket] Connected');
});

socket.addEventListener('message', (event) => {
  queue.push(event.data);
  if (!ticker.isScrolling) startScroll(); // Start if not already scrolling
});

function startScroll() {
  if (queue.length === 0) {
    queue.push(currentconds.innerHTML);
  }

  const message = queue.shift();
  ticker.textContent = message;

  // Reset animation
  ticker.style.animation = 'none';
  ticker.offsetHeight; // trigger reflow
  ticker.style.animation = `scroll ${SCROLL_DURATION}ms linear`;

  ticker.isScrolling = true;

  // Wait for scroll to finish before showing next
  setTimeout(() => {
    startScroll();
  }, SCROLL_DURATION);
}