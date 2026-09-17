#!/usr/bin/env bash
# Servis neden başlamıyor? Servis kullanıcısının gözünden erişim ve içe aktarma denetimi.
#   sudo bash kurulum/tani.sh
set -u
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KULLANICI=creamanage
echo "Uygulama klasörü: $KOK"
echo; echo "== Dizin izinleri (namei)"; namei -l "$KOK/creamanage/__init__.py" 2>&1 | tail -n 8
echo; echo "== ACL: $(getfacl -p "$(dirname "$KOK")" 2>/dev/null | grep -E "^user:$KULLANICI" || echo "yok")"
echo; echo "== Servis kullanıcısıyla okuma"
for y in "$KOK/main.py" "$KOK/creamanage/__init__.py" "$KOK/creamanage/ayarlar.py" "$KOK/web/index.html" "$KOK/venv/bin/python"; do
  if sudo -u "$KULLANICI" test -r "$y"; then echo "  OK   $y"; else echo "  YOK  $y"; fi
done
echo; echo "== Servis kullanıcısıyla içe aktarma"
sudo -u "$KULLANICI" env PYTHONPATH="$KOK" "$KOK/venv/bin/python" -c "import sys; sys.path.insert(0, '$KOK'); import creamanage, aiohttp; print('  OK   creamanage', creamanage.__file__); print('  OK   aiohttp', aiohttp.__version__)" 2>&1 | sed 's/^/  /'
echo; echo "== Servis tanımı"; grep -E "^(User|WorkingDirectory|ExecStart|Environment|ProtectHome|ProtectSystem|ReadWritePaths)" /etc/systemd/system/creamanage.service 2>/dev/null
echo; echo "== Son günlük"; journalctl -u creamanage -n 15 --no-pager 2>/dev/null
