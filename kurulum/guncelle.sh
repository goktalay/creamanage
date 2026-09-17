#!/usr/bin/env bash
# Dosyaları siz güncelledikten sonra (kopyalama, git pull vb. sizin tercihiniz) servisi yeniler:
#   sudo bash kurulum/guncelle.sh
set -euo pipefail
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }
"$KOK/venv/bin/pip" install -q -r "$KOK/requirements.txt"
chmod -R a+rX "$KOK"
find "$KOK" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
VERI=$(grep -oP '^CREAMANAGE_VERITABANI=\K.*' /etc/creamanage/creamanage.env 2>/dev/null | xargs -r dirname || echo /var/lib/creamanage)
sed -e "s#/opt/creamanage#$KOK#g" -e "s#/var/lib/creamanage#${VERI:-/var/lib/creamanage}#g" \
    "$KOK/kurulum/creamanage.service" > /etc/systemd/system/creamanage.service
systemctl daemon-reload
systemctl restart creamanage
sleep 2
systemctl --no-pager --lines=5 status creamanage
