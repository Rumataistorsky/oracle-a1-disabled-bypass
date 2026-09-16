#!/bin/bash
# 10-database.sh — ролі, бази і схема fleet на LXC 415 (rotes-db).
# Запускати на хості pve під root.
#
# Паролі генеруються тут і НІКОЛИ не друкуються в stdout.
# Вони лягають у /root/fleet-credentials.txt (chmod 600) на pve —
# звідти їх треба перенести у Vaultwarden і файл видалити.
set -euo pipefail
umask 077

DB_CT=415
DB_HOST=192.168.2.25
TRACCAR_IP=192.168.2.66
N8N_IP=192.168.2.20
METABASE_IP=192.168.2.38
PG_VER=17
CRED=/root/fleet-credentials.txt
SCHEMA=/root/fleet-schema.sql

gen() { openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32; }

[ -f "$SCHEMA" ] || { echo "ПОМИЛКА: немає $SCHEMA"; exit 1; }

if [ -f "$CRED" ]; then
    echo "ПОМИЛКА: $CRED уже існує. Прибери його, якщо це повторний прогін."
    exit 1
fi

PW_TRACCAR=$(gen); PW_RW=$(gen); PW_RO=$(gen)

echo "[1/5] ролі та база traccar"
TMP=$(mktemp /root/.roles.XXXXXX.sql)
{
  printf "CREATE ROLE traccar  LOGIN PASSWORD '%s';\n" "$PW_TRACCAR"
  printf "CREATE ROLE fleet_rw LOGIN PASSWORD '%s';\n" "$PW_RW"
  printf "CREATE ROLE fleet_ro LOGIN PASSWORD '%s';\n" "$PW_RO"
  printf "CREATE DATABASE traccar OWNER traccar;\n"
} > "$TMP"
pct push "$DB_CT" "$TMP" /tmp/roles.sql --perms 600
shred -u "$TMP"
pct exec "$DB_CT" -- bash -c "chown postgres /tmp/roles.sql && su postgres -c 'psql -v ON_ERROR_STOP=1 -f /tmp/roles.sql' >/dev/null && shred -u /tmp/roles.sql"

echo "[2/5] схема fleet у rotes_construction"
pct push "$DB_CT" "$SCHEMA" /tmp/fleet-schema.sql --perms 644
pct exec "$DB_CT" -- bash -c "chown postgres /tmp/fleet-schema.sql && su postgres -c 'psql -v ON_ERROR_STOP=1 -q -d rotes_construction -f /tmp/fleet-schema.sql' && rm -f /tmp/fleet-schema.sql"

echo "[3/5] права"
pct exec "$DB_CT" -- su postgres -c "psql -v ON_ERROR_STOP=1 -q -d rotes_construction -c \"
GRANT USAGE ON SCHEMA fleet TO fleet_rw, fleet_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fleet TO fleet_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA fleet TO fleet_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA fleet TO fleet_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA fleet GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fleet_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA fleet GRANT USAGE, SELECT ON SEQUENCES TO fleet_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA fleet GRANT SELECT ON TABLES TO fleet_ro;\""

echo "[4/5] pg_hba"
HBA=/etc/postgresql/${PG_VER}/main/pg_hba.conf
pct exec "$DB_CT" -- bash -c "grep -q 'fleet_rw' $HBA || printf '%s\n' \
  'hostssl traccar            traccar   ${TRACCAR_IP}/32   scram-sha-256' \
  'hostssl rotes_construction fleet_rw  ${N8N_IP}/32   scram-sha-256' \
  'hostssl rotes_construction fleet_ro  ${METABASE_IP}/32   scram-sha-256' >> $HBA"
pct exec "$DB_CT" -- systemctl reload postgresql

echo "[5/5] запис облікових даних"
{
  echo "# Vehicle logbook — облікові дані БД. Створено $(date -Is)."
  echo "# ПЕРЕНЕСТИ У VAULTWARDEN І ВИДАЛИТИ ЦЕЙ ФАЙЛ."
  echo "host=${DB_HOST} port=5432 sslmode=require"
  echo
  echo "db=traccar             user=traccar  password=${PW_TRACCAR}"
  echo "db=rotes_construction  user=fleet_rw password=${PW_RW}   # n8n"
  echo "db=rotes_construction  user=fleet_ro password=${PW_RO}   # metabase"
} > "$CRED"
chmod 600 "$CRED"

# пароль traccar одразу в конфіг застосунку, повз транскрипт
echo "$PW_TRACCAR" > /root/.traccar-db-pw
chmod 600 /root/.traccar-db-pw

echo "DB_SETUP_DONE — облікові дані у $CRED"
