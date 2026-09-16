#!/bin/bash
# 70-telegram-credential.sh — створює в n8n креди бота ROTES Logbook.
# Запускати на pve під root після того, як токен покладено у
# /root/.telegram-logbook-token (chmod 600). Токен не друкується.
set -euo pipefail
umask 077

TOKEN_FILE=/root/.telegram-logbook-token
[ -f "$TOKEN_FILE" ] || { echo "ПОМИЛКА: немає $TOKEN_FILE"; exit 1; }
TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")
[ -n "$TOKEN" ] || { echo "ПОМИЛКА: файл токена порожній"; exit 1; }

# перевірити токен до того, як щось конфігурувати
BOT=$(curl -s -m 20 "https://api.telegram.org/bot${TOKEN}/getMe")
echo "$BOT" | grep -q '"ok":true' || { echo "ПОМИЛКА: Telegram відхилив токен"; exit 1; }
echo "бот: $(echo "$BOT" | grep -oP '"username":"\K[^"]+')"

T=$(mktemp /root/.tg.XXXXXX.json)
printf '[{"id":"fleettelegrambot1","name":"ROTES Logbook Bot","type":"telegramApi","data":{"accessToken":"%s","baseUrl":"https://api.telegram.org"}}]' "$TOKEN" > "$T"
pct push 411 "$T" /tmp/tg.json --perms 600
shred -u "$T"
pct exec 411 -- bash -c '
set -e
docker cp /tmp/tg.json n8n:/tmp/tg.json
docker exec -u 0 n8n chmod 0644 /tmp/tg.json
docker exec n8n n8n import:credentials --input=/tmp/tg.json
docker exec -u 0 n8n rm -f /tmp/tg.json
shred -u /tmp/tg.json
'
echo "TELEGRAM_CREDENTIAL_DONE"
