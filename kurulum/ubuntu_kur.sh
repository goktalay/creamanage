#!/usr/bin/env bash
# CreaManage'i BU KLASÖRDEN, olduğu yerde systemd servisi olarak kurar. İnternetten kod çekmez.
#   sudo bash kurulum/ubuntu_kur.sh
# Yeniden çalıştırmak güvenlidir: bağımlılıkları günceller, servis dosyasını tazeler, yeniden başlatır.
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # depo/uygulama klasörü
VERI="${CREAMANAGE_VERI:-/var/lib/creamanage}"
AYAR=/etc/creamanage
KULLANICI=creamanage
PORT="${CREAMANAGE_PORT:-8090}"

[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }
[ -f "$KOK/main.py" ] || { echo "main.py bulunamadı: $KOK"; exit 1; }

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

echo "1) Paketler"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip acl >/dev/null

echo "2) Servis kullanıcısı ve veri dizini ($VERI)"
id -u "$KULLANICI" >/dev/null 2>&1 || useradd --system --home "$VERI" --shell /usr/sbin/nologin "$KULLANICI"
mkdir -p "$VERI/telemetri" "$AYAR"
chown -R "$KULLANICI:$KULLANICI" "$VERI"
chmod 750 "$VERI"

echo "3) Python sanal ortamı ($KOK/venv)"
# Klasör taşındıysa venv içindeki mutlak yollar bozulur: çalışmıyorsa sıfırdan kur
if ! "$KOK/venv/bin/python" -c "import sys" >/dev/null 2>&1 || ! grep -q "^home = " "$KOK/venv/pyvenv.cfg" 2>/dev/null; then
  rm -rf "$KOK/venv"; python3 -m venv "$KOK/venv"
fi
"$KOK/venv/bin/python" -m pip install -q --upgrade pip
"$KOK/venv/bin/python" -m pip install -q -r "$KOK/requirements.txt"
# Servis kullanıcısı uygulama dosyalarını okuyabilmeli (yazmaz)
chmod -R a+rX "$KOK"
find "$KOK" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
erisim_ver "$KOK"

echo "4) Ayar dosyası ($AYAR/creamanage.env)"
if [ ! -f "$AYAR/creamanage.env" ]; then
  sed -e "s/^CREAMANAGE_PORT=.*/CREAMANAGE_PORT=$PORT/" -e "s#/var/lib/creamanage#$VERI#g" \
      "$KOK/kurulum/creamanage.env.ornek" > "$AYAR/creamanage.env"
  chmod 640 "$AYAR/creamanage.env"; chown root:"$KULLANICI" "$AYAR/creamanage.env"
  echo "   yazıldı"
else
  echo "   mevcut dosya korundu"
fi

echo "5) systemd servisi (WorkingDirectory=$KOK)"
servis_yaz
systemctl daemon-reload
systemctl enable creamanage >/dev/null
systemctl restart creamanage
sleep 2
if systemctl is-active --quiet creamanage; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "CreaManage çalışıyor: http://${IP:-<sunucu-ip>}:$(grep -oP '^CREAMANAGE_PORT=\K.*' "$AYAR/creamanage.env")/"
  echo "Uygulama: $KOK   Veri: $VERI   Ayar: $AYAR/creamanage.env"
  echo "Günlük: journalctl -u creamanage -f   |   Durum: systemctl status creamanage"
else
  echo "Servis başlamadı. Günlük:"; journalctl -u creamanage -n 30 --no-pager; exit 1
fi
