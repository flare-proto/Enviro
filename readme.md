# Envirotron
Really its just a better environment canada alert map, with different colors

THIS ONLY WORKS IN CANADA

## Usage

1. Setup a RabbitMQ server
    - create an alert fanout exchange
    - create an alert_cap queue
    - create a log queue
    - create a merged queue
    - create a outlook queue
2. Configure Server
    - set amqp urls in config.ini as required
    - set station_id in config.ini
        - [Station IDs can be found here](https://dd.weather.gc.ca/citypage_weather/docs/site_list_towns_en.csv)
        - Current station id is Calgary Alberta
3. Cd into static/my-app and run `npm run build`
4. Run start.py