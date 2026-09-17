#!/usr/bin/env bash
# Kurulu servisi depodan günceller ve yeniden başlatır:  sudo bash /opt/creamanage/kurulum/guncelle.sh
set -euo pipefail
HEDEF=/opt/creamanage
[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }
git -C "$HEDEF" pull --ff-only
"$HEDEF/venv/bin/pip" install -q -r "$HEDEF/requirements.txt"
install -m 644 "$HEDEF/kurulum/creamanage.service" /etc/systemd/system/creamanage.service
systemctl daemon-reload
systemctl restart creamanage
sleep 2
systemctl --no-pager --lines=5 status creamanage
