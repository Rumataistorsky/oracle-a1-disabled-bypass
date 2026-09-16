#!/bin/bash
# 40-n8n-credentials.sh — створює в n8n (LXC 411) креди для логбука.
# Запускати на pve під root. Читає паролі з /root/fleet-credentials.txt,
# у stdout нічого секретного не друкує.
set -euo pipefail
umask 077

N8N_CT=411
DB_HOST=192.168.2.25
CRED=/root/fleet-credentials.txt

[ -f "$CRED" ] || { echo "ПОМИЛКА: немає $CRED (вже перенесено у Vaultwarden?)"; exit 1; }

PW_RW=$(grep -oP 'user=fleet_rw password=\K\S+'  "$CRED" | head -1)
TC_USER=$(grep -oP 'traccar web \S+\s+user=\K\S+' "$CRED" | head -1)
TC_PW=$(grep -oP 'traccar web .*password=\K\S+'   "$CRED" | head -1)

[ -n "$PW_RW" ]  || { echo "ПОМИЛКА: не знайдено пароль fleet_rw"; exit 1; }
[ -n "$TC_PW" ]  || { echo "ПОМИЛКА: не знайдено пароль Traccar"; exit 1; }

TMP=$(mktemp -d /root/.n8ncred.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/creds.json" <<JSON
[
  {
    "id": "fleetdbfleetrw01",
    "name": "Fleet DB (fleet_rw)",
    "type": "postgres",
    "data": {
      "host": "${DB_HOST}",
      "port": 5432,
      "database": "rotes_construction",
      "user": "fleet_rw",
      "password": "${PW_RW}",
      "ssl": "require",
      "allowUnauthorizedCerts": true,
      "maxConnections": 10
    }
  },
  {
    "id": "fleettraccarapi1",
    "name": "Traccar API (fleet)",
    "type": "httpBasicAuth",
    "data": {
      "user": "${TC_USER}",
      "password": "${TC_PW}"
    }
  }
]
JSON

pct push "$N8N_CT" "$TMP/creds.json" /tmp/fleet-creds.json --perms 600
pct exec "$N8N_CT" -- bash -c 'docker cp /tmp/fleet-creds.json n8n:/tmp/fleet-creds.json && docker exec n8n n8n import:credentials --input=/tmp/fleet-creds.json && docker exec n8n rm -f /tmp/fleet-creds.json; shred -u /tmp/fleet-creds.json'

echo "N8N_CREDENTIALS_DONE"
