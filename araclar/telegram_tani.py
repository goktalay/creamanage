#!/usr/bin/env python3
"""Telegram bot tanı aracı — sunucuda çalıştırılır, internet ve bot durumunu gösterir.

Kullanım:
  python3 araclar/telegram_tani.py <BOT_BELIRTECI>                 # durum + sohbetler
  python3 araclar/telegram_tani.py <BOT_BELIRTECI> --gonder <ID>   # o sohbete test mesajı
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org"


def cagir(token: str, yontem: str, veri: dict | None = None) -> dict:
    istek = urllib.request.Request(f"{API}/bot{token}/{yontem}",
                                   data=json.dumps(veri or {}).encode(),
                                   headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(istek, timeout=15) as y:
            return json.loads(y.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except ValueError:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"ok": False, "description": f"AĞ HATASI: {e.reason}"}


def ana(argv=None) -> int:
    p = argparse.ArgumentParser(description="CreaManage Telegram tanı aracı")
    p.add_argument("token", help="BotFather'ın verdiği belirteç (123456:AA…)")
    p.add_argument("--gonder", metavar="SOHBET_ID", help="bu sohbete test mesajı gönder")
    n = p.parse_args(argv)
    token = n.token.strip()

    print("1) İnternet ve belirteç denetimi (getMe)…")
    me = cagir(token, "getMe")
    if not me.get("ok"):
        print("   HATA:", me.get("description"))
        if "AĞ HATASI" in str(me.get("description")):
            print("   → Bu makine api.telegram.org adresine ulaşamıyor. İnternet/vekil ayarını kontrol edin.")
        elif "Unauthorized" in str(me.get("description")):
            print("   → Belirteç yanlış ya da iptal edilmiş. BotFather'da /token ile yenisini alın.")
        return 1
    bot = me["result"]
    print(f"   TAMAM: bot @{bot.get('username')} ({bot.get('first_name')})")

    print("2) Webhook denetimi (getWebhookInfo)…")
    wh = cagir(token, "getWebhookInfo")
    url = (wh.get("result") or {}).get("url")
    if url:
        print(f"   UYARI: bota bir webhook tanımlı ({url}); getUpdates bu durumda çalışmaz. Kaldırılıyor…")
        print("   ", cagir(token, "deleteWebhook").get("description"))
    else:
        print("   TAMAM: webhook yok")

    print("3) Bota gelen mesajlar (getUpdates)…")
    g = cagir(token, "getUpdates", {"limit": 100})
    if not g.get("ok"):
        print("   HATA:", g.get("description"))
        return 1
    guncellemeler = g.get("result") or []
    sohbetler: dict[str, dict] = {}
    for u in guncellemeler:
        m = u.get("message") or u.get("channel_post") or u.get("edited_message") or (u.get("my_chat_member") or {})
        c = m.get("chat") if isinstance(m, dict) else None
        if not c:
            continue
        ad = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("username") or "?"
        sohbetler[str(c["id"])] = {"ad": ad, "tur": c.get("type"), "metin": (m.get("text") or "")[:40]}
    if not guncellemeler:
        print("   Hiç mesaj yok. Telegram'da bu bota (@%s) gidip /start yazın, sonra yeniden çalıştırın." % bot.get("username"))
        print("   Not: Telegram, 24 saatten eski okunmamış mesajları siler.")
    else:
        print(f"   {len(guncellemeler)} güncelleme, {len(sohbetler)} farklı sohbet:")
        for kimlik, s in sohbetler.items():
            print(f"   - SOHBET ID: {kimlik:>16}   {s['tur']:<10} {s['ad']}   son mesaj: {s['metin']!r}")
        print("   → Bu ID'yi CreaManage → Bildirimler → 'Sohbet kimlikleri' kutusuna yazın.")

    if n.gonder:
        print(f"4) {n.gonder} sohbetine test mesajı…")
        r = cagir(token, "sendMessage", {"chat_id": n.gonder, "text": "CreaManage test mesajı ✅"})
        print("   TAMAM, mesaj gitti." if r.get("ok") else f"   HATA: {r.get('description')}")
        if not r.get("ok") and "chat not found" in str(r.get("description")):
            print("   → Bu kişi bota henüz /start yazmamış ya da ID yanlış.")
    return 0


if __name__ == "__main__":
    sys.exit(ana())
