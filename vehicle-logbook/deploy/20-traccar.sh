#!/bin/bash
# 20-traccar.sh — встановлення і конфігурація Traccar у LXC 426.
# Запускати на хості pve під root, ПІСЛЯ 10-database.sh
# (потребує /root/.traccar-db-pw).
set -euo pipefail
umask 077

CT=426
DB_HOST=192.168.2.25
PW_FILE=/root/.traccar-db-pw

[ -f "$PW_FILE" ] || { echo "ПОМИЛКА: немає $PW_FILE — спершу 10-database.sh"; exit 1; }
PW=$(cat "$PW_FILE")

echo "[1/4] визначення актуальної версії Traccar"
VER=$(curl -fsSL https://api.github.com/repos/traccar/traccar/releases/latest \
      | grep -oP '"tag_name"\s*:\s*"v\K[0-9.]+' | head -1)
[ -n "$VER" ] || { echo "ПОМИЛКА: не вдалося визначити версію"; exit 1; }
echo "      версія: $VER"

echo "[2/4] завантаження і встановлення"
pct exec "$CT" -- bash -c "cd /tmp && curl -fsSLO https://github.com/traccar/traccar/releases/download/v${VER}/traccar-linux-64-${VER}.zip && unzip -oq traccar-linux-64-${VER}.zip && ./traccar.run && rm -f traccar-linux-64-${VER}.zip traccar.run README.txt"

echo "[3/4] конфігурація"
TMP=$(mktemp /root/.traccar.XXXXXX.xml)
cat > "$TMP" <<XML
<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<properties>
    <entry key='config.default'>./conf/default.xml</entry>

    <entry key='database.driver'>org.postgresql.Driver</entry>
    <entry key='database.url'>jdbc:postgresql://${DB_HOST}:5432/traccar?ssl=true&amp;sslmode=require</entry>
    <entry key='database.user'>traccar</entry>
    <entry key='database.password'>${PW}</entry>

    <entry key='web.port'>8082</entry>
    <entry key='web.address'>0.0.0.0</entry>

    <!-- реєстрація закрита: користувачів заводить адміністратор -->
    <entry key='web.registration'>false</entry>

    <!-- зворотне геокодування: адреса підставляється сама -->
    <entry key='geocoder.enable'>true</entry>
    <entry key='geocoder.type'>nominatim</entry>
    <entry key='geocoder.url'>https://nominatim.openstreetmap.org/reverse</entry>
    <entry key='geocoder.onRequest'>false</entry>
    <entry key='geocoder.processInvalidPositions'>false</entry>
    <entry key='geocoder.reuseDistance'>50</entry>

    <!-- нарізка поїздок під логбук -->
    <entry key='report.trip.minimalTripDistance'>300</entry>
    <entry key='report.trip.minimalTripDuration'>120</entry>
    <entry key='report.trip.minimalParkingDuration'>60</entry>
    <!-- useIgnition=false обовʼязково. Telefon-міст (osmand) не передає
         ignition, і при true Traccar вважає пристрій вічно зупиненим:
         /api/reports/trips мовчки повертає [] — жодної поїздки, жодної
         помилки. Teltonika FMM003 шле і ignition, і motion, тому motion
         лишається спільним знаменником для обох джерел. -->
    <entry key='report.trip.useIgnition'>false</entry>

    <!-- фільтри: сміттєві точки не мають потрапляти в податковий облік -->
    <entry key='filter.enable'>true</entry>
    <entry key='filter.invalid'>true</entry>
    <entry key='filter.zero'>true</entry>
    <entry key='filter.duplicate'>true</entry>
    <!-- filter.distance НЕ вмикати: він відкидає стаціонарні точки, з яких
         Traccar розпізнає стоянку, і поїздки перестають нарізатися. -->
    <entry key='filter.skipLimit'>10000</entry>

    <entry key='event.enable'>true</entry>
    <entry key='event.ignoreDuplicateAlerts'>true</entry>

    <!-- зберігати позиції довго: логбук тримається 7 років -->
    <entry key='database.positionsHistoryDays'>0</entry>
</properties>
XML
pct push "$CT" "$TMP" /opt/traccar/conf/traccar.xml --perms 640
shred -u "$TMP"
pct exec "$CT" -- chown root:traccar /opt/traccar/conf/traccar.xml 2>/dev/null || true

echo "[4/4] запуск"
pct exec "$CT" -- systemctl enable traccar >/dev/null 2>&1 || true
pct exec "$CT" -- systemctl restart traccar
sleep 20
pct exec "$CT" -- systemctl is-active traccar
echo "TRACCAR_SETUP_DONE version=$VER"
