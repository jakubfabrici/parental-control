#!/bin/sh
# Vyda novu verziu PC agenta: nahra windows-remote-control/ na OMV a publikuje.
# Pouzitie:  ./release.sh            (verzia z windows-remote-control/VERSION)
#            ./release.sh 1.2.0      (zaroven zapise VERSION)
# Predpoklad: ssh root@192.168.1.185 funguje (klucom) a OMV je pripravene (omv/install-omv.sh).
set -e
cd "$(dirname "$0")"
OMV=${OMV:-root@192.168.1.185}
SRC=windows-remote-control
if [ -n "$1" ]; then echo "$1" > "$SRC/VERSION"; fi
VER=$(tr -d ' \r\n' < "$SRC/VERSION")
[ -n "$VER" ] || { echo "prazdna VERSION"; exit 1; }
echo "verzia $VER -> $OMV"
ssh "$OMV" "rm -rf /var/www/pc-agent/incoming/$VER && mkdir -p /var/www/pc-agent/incoming/$VER"
tar -C "$SRC" --exclude='config.json' --exclude='*.log' --exclude='*.bak*' --exclude='*.b64' -cf - . | ssh "$OMV" "tar -C /var/www/pc-agent/incoming/$VER -xf -"
ssh "$OMV" "pc-agent-publish $VER /var/www/pc-agent/incoming/$VER && rm -rf /var/www/pc-agent/incoming/$VER"
