#!/usr/bin/env bash
# Sunucu için GitHub deploy key (SSH) kurulumu — parola/belirteç gerekmeden `git pull`.
#   sudo bash kurulum/deploy_key.sh
# 1) /etc/creamanage/deploy_key (ed25519) üretir  2) bu depo için SSH yapılandırır
# 3) remote'u SSH adresine çevirir  4) GitHub'a eklenecek açık anahtarı yazdırır
set -euo pipefail
KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "Lütfen sudo ile çalıştırın."; exit 1; }
ANAHTAR=/etc/creamanage/deploy_key
mkdir -p /etc/creamanage
if [ ! -f "$ANAHTAR" ]; then
  ssh-keygen -t ed25519 -N "" -C "creamanage-deploy@$(hostname)" -f "$ANAHTAR" >/dev/null
  chmod 600 "$ANAHTAR"
fi
# GitHub sunucu anahtarı (ilk bağlantıda soru sormasın)
mkdir -p /root/.ssh && chmod 700 /root/.ssh
ssh-keyscan -t ed25519 github.com 2>/dev/null >> /root/.ssh/known_hosts
sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts
# Bu depo yalnız bu anahtarı kullansın
git -C "$KOK" config core.sshCommand "ssh -i $ANAHTAR -o IdentitiesOnly=yes"
git config --global --add safe.directory "$KOK" 2>/dev/null || true
URL=$(git -C "$KOK" remote get-url origin)
if [[ "$URL" == https://github.com/* ]]; then
  git -C "$KOK" remote set-url origin "git@github.com:${URL#https://github.com/}"
fi
echo
echo "Aşağıdaki AÇIK anahtarı GitHub'a ekleyin:"
echo "  https://github.com/goktalay/creamanage/settings/keys  →  Add deploy key"
echo "  Title: $(hostname)   ·   Key: (aşağıdaki satır)   ·   Allow write access: KAPALI"
echo "------------------------------------------------------------------"
cat "$ANAHTAR.pub"
echo "------------------------------------------------------------------"
echo "Ekledikten sonra deneyin:  cd $KOK && sudo git pull"
