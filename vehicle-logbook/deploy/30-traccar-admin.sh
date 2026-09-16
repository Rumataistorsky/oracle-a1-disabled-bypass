#!/bin/bash
# 30-traccar-admin.sh — створює адміністратора Traccar.
# Запускати на pve під root. Пароль генерується тут, у stdout не потрапляє,
# дописується у /root/fleet-credentials.txt.
set -euo pipefail
umask 077

CT=426
HOST=192.168.2.66:8082
EMAIL="${1:-roman.tesla.ca@gmail.com}"
NAME="${2:-Roman}"
CFG=/opt/traccar/conf/traccar.xml
CRED=/root/fleet-credentials.txt

restore_registration() {
    pct exec "$CT" -- sed -i "s|<entry key='web.registration'>true</entry>|<entry key='web.registration'>false</entry>|" "$CFG" || true
    pct exec "$CT" -- systemctl restart traccar || true
}
trap restore_registration EXIT

EXISTING=$(pct exec 415 -- su postgres -c "psql -d traccar -tAc 'SELECT count(*) FROM tc_users;'" | tr -d '[:space:]')
if [ "$EXISTING" != "0" ]; then
    echo "Користувачі вже існують ($EXISTING) — нічого не роблю."
    exit 0
fi

PW=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 24)

echo "[1/4] тимчасово вмикаю реєстрацію"
pct exec "$CT" -- sed -i "s|<entry key='web.registration'>false</entry>|<entry key='web.registration'>true</entry>|" "$CFG"
pct exec "$CT" -- systemctl restart traccar
for i in $(seq 1 30); do
    curl -sf -o /dev/null "http://${HOST}/" && break
    sleep 3
done

echo "[2/4] створюю користувача"
# administrator:true через API відхиляється, доки жодного адміна не існує
# (PermissionsService.checkAdmin падає на NULL) — тому створюємо звичайного
# користувача, а права піднімаємо прямо в БД.
BODY=$(mktemp /root/.tcuser.XXXXXX.json)
printf '{"name":"%s","email":"%s","password":"%s"}\n' "$NAME" "$EMAIL" "$PW" > "$BODY"
RESP=$(curl -s -X POST "http://${HOST}/api/users" -H 'Content-Type: application/json' --data @"$BODY")
shred -u "$BODY"
echo "$RESP" | grep -q '"id"' || { echo "ПОМИЛКА створення користувача: $RESP" | head -3; exit 1; }
echo "      створено: $(echo "$RESP" | grep -oP '"email"\s*:\s*"\K[^"]+')"

echo "[2b/4] піднімаю права до адміністратора"
pct exec 415 -- su postgres -c "psql -v ON_ERROR_STOP=1 -q -d traccar -c \"UPDATE tc_users SET administrator = true WHERE email = '${EMAIL}';\""

echo "[3/4] вимикаю реєстрацію назад"
pct exec "$CT" -- sed -i "s|<entry key='web.registration'>true</entry>|<entry key='web.registration'>false</entry>|" "$CFG"
pct exec "$CT" -- systemctl restart traccar

echo "[4/4] дописую у $CRED"
{
  echo
  echo "traccar web https://fleet.rotes.ca  user=${EMAIL} password=${PW}"
} >> "$CRED"
chmod 600 "$CRED"

for i in $(seq 1 30); do curl -sf -o /dev/null "http://${HOST}/" && break; sleep 3; done
echo "ADMIN_SETUP_DONE"
