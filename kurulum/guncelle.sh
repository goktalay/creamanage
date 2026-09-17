#!/usr/bin/env bash
# Dosyaları siz güncelledikten sonra (kopyalama, git pull vb. sizin tercihiniz) servisi yeniler:
#   sudo bash kurulum/guncelle.sh
set -euo pipefail
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KULLANICI=creamanage
[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }
VERI=$(grep -oP '^CREAMANAGE_VERITABANI=\K.*' /etc/creamanage/creamanage.env 2>/dev/null | xargs -r dirname || true)
VERI="${VERI:-/var/lib/creamanage}"
# Servis kullanıcısı uygulama klasörüne ulaşabilmeli: üst dizinlere yalnız "geçiş" (x) izni.
erisim_ver() {
  local d="$1"
  while [ "$d" != "/" ]; do
    if ! sudo -u "$KULLANICI" test -x "$d" 2>/dev/null; then
      if command -v setfacl >/dev/null 2>&1; then setfacl -m "u:$KULLANICI:--x" "$d"; else chmod o+x "$d"; fi
    fi
    d="$(dirname "$d")"
  done
}
# Ev dizini altındaysa ProtectHome servisi engeller (203/EXEC): salt okunur erişime çevir.
servis_yaz() {
  sed -e "s#/opt/creamanage#$KOK#g" -e "s#/var/lib/creamanage#$VERI#g" "$KOK/kurulum/creamanage.service" > /etc/systemd/system/creamanage.service
  case "$KOK" in /home/*|/root/*) sed -i "s/^ProtectHome=.*/ProtectHome=read-only/" /etc/systemd/system/creamanage.service ;; esac
  chmod 644 /etc/systemd/system/creamanage.service
}

"$KOK/venv/bin/pip" install -q -r "$KOK/requirements.txt"
chmod -R a+rX "$KOK"
find "$KOK" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
erisim_ver "$KOK"
servis_yaz
systemctl daemon-reload
systemctl restart creamanage
sleep 2
systemctl --no-pager --lines=5 status creamanage
