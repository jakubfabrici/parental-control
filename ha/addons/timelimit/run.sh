#!/bin/sh
# Start add-onu: options.json -> env premenne servera, Mailpit vedla neho,
# cakanie na MariaDB. Image nema bashio ani jq, tak options cita node.
set -eu

OPTIONS=/data/options.json
opt() {
    node -e 'const o=require(process.argv[1]);const v=o[process.argv[2]];process.stdout.write(v==null?"":String(v))' "$OPTIONS" "$1"
}
yesno() {
    if [ "$(opt "$1")" = "true" ]; then echo yes; else echo no; fi
}

DB_HOST="$(opt db_host)"
DB_PORT="$(opt db_port)"
DB_NAME="$(opt db_name)"
DB_USER="$(opt db_user)"
DB_PASS="$(opt db_password)"
MAILPIT_MAX="$(opt mailpit_max_messages)"

if [ -z "$DB_PASS" ]; then
    echo "[timelimit] db_password nie je nastavene - dopln ho v konfiguracii add-onu" >&2
    exit 1
fi

export NODE_ENV=production
export PORT=8080
# v1.17.0 necita DATABASE_URL, ale samostatne DB_* premenne; bez DB_DRIVER
# ticho spadne na sqlite://test.db.
export DB_DRIVER=mariadb DB_HOST DB_PORT DB_NAME DB_USER DB_PASS
export MAIL_SENDER="$(opt mail_sender)"
export MAIL_TRANSPORT='{"host":"127.0.0.1","port":1025,"secure":false,"ignoreTLS":true}'
export ALWAYS_PRO="$(yesno always_pro)"
export DISABLE_SIGNUP="$(yesno disable_signup)"

echo "[timelimit] cakam na MariaDB ${DB_HOST}:${DB_PORT}"
i=0
until nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 90 ]; then
        echo "[timelimit] MariaDB sa neozvala do 3 minut" >&2
        exit 1
    fi
    sleep 2
done

echo "[timelimit] startujem Mailpit (web :8025, SMTP 127.0.0.1:1025)"
mailpit --listen 0.0.0.0:8025 --smtp 127.0.0.1:1025 \
    --database /data/mailpit.db --max "$MAILPIT_MAX" &
MP=$!

echo "[timelimit] startujem TimeLimit server (:8080)"
cd /usr/src/app
node ./build/index.js &
TL=$!

# busybox wait nepozna -n: ked jeden z dvoch procesov spadne, zhodime aj druhy
# a kontajner skonci - Supervisor (watchdog) ho potom restartuje.
trap 'kill $MP $TL 2>/dev/null' TERM INT
while kill -0 "$MP" 2>/dev/null && kill -0 "$TL" 2>/dev/null; do
    sleep 5
done
kill "$MP" "$TL" 2>/dev/null || true
wait || true
echo "[timelimit] jeden z procesov skoncil, koncim" >&2
exit 1
