#!/usr/bin/env bash
# CreaManage'i Ubuntu (20.04+/22.04/24.04) üzerinde systemd servisi olarak kurar.
#   sudo bash kurulum/ubuntu_kur.sh                 # depodan (git clone ile) kurar
#   sudo bash kurulum/ubuntu_kur.sh --yerel         # bu klasördeki kopyayı /opt/creamanage'e kopyalar
# Yeniden çalıştırmak güvenlidir (idempotent): kodu ve bağımlılıkları günceller, veriye dokunmaz.
set -euo pipefail

DEPO="https://github.com/goktalay/creamanage.git"
HEDEF=/opt/creamanage
VERI=/var/lib/creamanage
AYAR=/etc/creamanage
KULLANICI=creamanage
PORT="${CREAMANAGE_PORT:-8090}"
BURASI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }

echo "1) Paketler"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git >/dev/null

echo "2) Servis kullanıcısı ve dizinler"
id -u "$KULLANICI" >/dev/null 2>&1 || useradd --system --home "$VERI" --shell /usr/sbin/nologin "$KULLANICI"
mkdir -p "$VERI/telemetri" "$AYAR"
chown -R "$KULLANICI:$KULLANICI" "$VERI"
chmod 750 "$VERI"

echo "3) Kod → $HEDEF"
if [ "${1:-}" = "--yerel" ]; then
  mkdir -p "$HEDEF"
  rsync -a --delete --exclude venv --exclude '.git' --exclude '__pycache__' --exclude '*.sqlite*' --exclude '*_telemetri' "$BURASI/" "$HEDEF/"
elif [ -d "$HEDEF/.git" ]; then
  git -C "$HEDEF" pull --ff-only
else
  git clone "$DEPO" "$HEDEF"
fi

echo "4) Python sanal ortamı ve bağımlılıklar"
[ -d "$HEDEF/venv" ] || python3 -m venv "$HEDEF/venv"
"$HEDEF/venv/bin/pip" install -q --upgrade pip
"$HEDEF/venv/bin/pip" install -q -r "$HEDEF/requirements.txt"
chown -R root:root "$HEDEF"
chmod -R a+rX "$HEDEF"

echo "5) Ayar dosyası"
if [ ! -f "$AYAR/creamanage.env" ]; then
  sed "s/^CREAMANAGE_PORT=.*/CREAMANAGE_PORT=$PORT/" "$HEDEF/kurulum/creamanage.env.ornek" > "$AYAR/creamanage.env"
  chmod 640 "$AYAR/creamanage.env"; chown root:"$KULLANICI" "$AYAR/creamanage.env"
  echo "   yazıldı: $AYAR/creamanage.env"
else
  echo "   mevcut $AYAR/creamanage.env korundu"
fi

echo "6) systemd servisi"
install -m 644 "$HEDEF/kurulum/creamanage.service" /etc/systemd/system/creamanage.service
systemctl daemon-reload
systemctl enable creamanage >/dev/null
systemctl restart creamanage
sleep 2
if systemctl is-active --quiet creamanage; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "CreaManage çalışıyor: http://${IP:-<sunucu-ip>}:$(grep -oP '^CREAMANAGE_PORT=\K.*' "$AYAR/creamanage.env")/"
  echo "İlk açılışta tarayıcı, ilk Sistem Yöneticisi hesabını oluşturmanızı ister."
  echo "Günlük: journalctl -u creamanage -f   |   Durum: systemctl status creamanage"
else
  echo "Servis başlamadı. Günlük:"; journalctl -u creamanage -n 30 --no-pager; exit 1
fi
