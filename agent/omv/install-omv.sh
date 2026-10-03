#!/bin/sh
# Jednorazova priprava OMV (spustit ako root na OMV). Idempotentne.
set -e
mkdir -p /var/www/pc-agent/releases /var/www/pc-agent/incoming
printf '{"error":"not found"}\n' > /var/www/pc-agent/404.json; chmod 644 /var/www/pc-agent/404.json
install -m 755 "$(dirname "$0")/pc-agent-publish.py" /usr/local/bin/pc-agent-publish
install -m 644 "$(dirname "$0")/pc-agent.conf" /etc/nginx/openmediavault-webgui.d/pc-agent.conf
if [ ! -s /root/.pc-agent-update.key ]; then
  openssl rand -hex 32 > /root/.pc-agent-update.key
  chmod 600 /root/.pc-agent-update.key
  echo "vytvoreny novy podpisovy kluc /root/.pc-agent-update.key - ten isty treba dat do config.json na PC ako UpdateKey"
fi
nginx -t && systemctl reload nginx
echo "OK: http://$(hostname -I | awk '{print $1}')/pc-agent/"
