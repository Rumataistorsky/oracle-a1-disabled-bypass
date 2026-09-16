#!/bin/bash
# 45-driver-chatid.sh — переносить Telegram chat_id Романа з наявного воркфлоу
# у fleet.drivers, щоб воркфлоу логбука не хардкодили його вдруге.
# Запускати на pve під root. Значення не друкується.
set -euo pipefail

SRC_WF=xcZbjHIEgKkwALO6   # ROTES Construction — Nightly Invoice Ninja Sync

pct exec 411 -- bash -c "docker exec n8n n8n export:workflow --id=${SRC_WF} --output=/tmp/src.json >/dev/null 2>&1"
CHAT=$(pct exec 411 -- bash -c "docker exec n8n sh -c 'grep -oE \"\\\"chat_id\\\"[^0-9-]*(-?[0-9]+)\" /tmp/src.json | grep -oE \"(-?[0-9]+)\$\" | head -1'" | tr -d '[:space:]')
pct exec 411 -- bash -c "docker exec n8n rm -f /tmp/src.json" || true

if [ -z "$CHAT" ]; then
    echo "chat_id у воркфлоу ${SRC_WF} не знайдено — заповнити fleet.drivers.chat_id вручну."
    exit 0
fi

pct exec 415 -- su postgres -c "psql -q -d rotes_construction -c \"UPDATE fleet.drivers SET chat_id='${CHAT}' WHERE label='Roman';\""
echo "CHATID_SET len=${#CHAT}"
