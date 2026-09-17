#!/bin/bash
# 80-bot-webhook.sh — секрет вебхука + реєстрація вебхука в Telegram.
# Запускати на pve під root. Секрет генерується тут і не друкується.
set -euo pipefail
umask 077

TOKEN_FILE=/root/.telegram-logbook-token
HOOK_URL="https://n8n-hooks.rotes.ca/webhook/fleet-bot"
SECRET_FILE=/root/.telegram-webhook-secret

[ -f "$TOKEN_FILE" ] || { echo "ПОМИЛКА: немає $TOKEN_FILE"; exit 1; }
TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")

if [ -f "$SECRET_FILE" ]; then
    SECRET=$(tr -d '[:space:]' < "$SECRET_FILE")
else
    SECRET=$(openssl rand -hex 24)
    printf '%s\n' "$SECRET" > "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
fi

echo "[1/3] креди вебхука в n8n"
T=$(mktemp /root/.hs.XXXXXX.json)
printf '[{"id":"fleettgsecret001","name":"Telegram Webhook Secret","type":"httpHeaderAuth","data":{"name":"X-Telegram-Bot-Api-Secret-Token","value":"%s"}}]' "$SECRET" > "$T"
pct push 411 "$T" /tmp/hs.json --perms 600
shred -u "$T"
pct exec 411 -- bash -c '
set -e
docker cp /tmp/hs.json n8n:/tmp/hs.json
docker exec -u 0 n8n chmod 0644 /tmp/hs.json
docker exec n8n n8n import:credentials --input=/tmp/hs.json
docker exec -u 0 n8n rm -f /tmp/hs.json
shred -u /tmp/hs.json
'

echo "[2/3] реєструю вебхук у Telegram"
B=$(mktemp /root/.wh.XXXXXX.json)
printf '{"url":"%s","secret_token":"%s","allowed_updates":["message","edited_message","callback_query"],"drop_pending_updates":false,"max_connections":10}' "$HOOK_URL" "$SECRET" > "$B"
RESP=$(curl -s -m 25 -H 'Content-Type: application/json' --data @"$B" "https://api.telegram.org/bot${TOKEN}/setWebhook")
shred -u "$B"
echo "$RESP" | grep -q '"ok":true' || { echo "ПОМИЛКА setWebhook: $RESP"; exit 1; }
echo "      зареєстровано"

echo "[3/3] стан вебхука"
curl -s -m 20 "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -c "
import sys,json
d=json.load(sys.stdin).get('result',{})
print('      url                 :', d.get('url'))
print('      очікує оновлень     :', d.get('pending_update_count'))
print('      секрет встановлено  :', bool(d.get('has_custom_certificate') is not None and d.get('url')))
if d.get('last_error_message'):
    print('      остання помилка     :', d.get('last_error_message'))
print('      типи оновлень       :', d.get('allowed_updates'))
"
echo "BOT_WEBHOOK_DONE"
