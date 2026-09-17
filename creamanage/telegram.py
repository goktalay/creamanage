"""Telegram bildirim kanalı — OlayMerkezi abonesi.

Bot belirteci ve sohbet kimlikleri arayüzden girilir, SQLite ``ayarlar``
tablosunda tutulur (depoya girmez). Olaylar kısa bir pencerede (2 sn)
toplanıp tek mesaj olarak gönderilir; böylece 56 yazıcının aynı anda kopması
56 ayrı mesaj değil tek bir özet üretir. Telegram'ın 429 yanıtına
``retry_after`` ile uyulur.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time

import aiohttp

from .olaylar import (O_BASKI_BASLADI, O_BASKI_BITTI, O_DURAKLATILDI, O_FILAMENT_YOK,
                      O_HATA, O_HATA_GECTI, O_KOPTU, O_BAGLANDI)

log = logging.getLogger("creamanage.telegram")

AYAR_ANAHTARI = "telegram"
API_TABAN = "https://api.telegram.org"
TOPLAMA_PENCERESI_SN = 2.0
EN_FAZLA_SATIR = 40          # tek mesajda gösterilecek olay sayısı (Telegram sınırı 4096 karakter)

# Arayüzde seçilebilen olay türleri (varsayılan: hata + tamamlandı + filament)
SECILEBILIR_OLAYLAR = [
    (O_HATA, "Hata oluştu"),
    (O_BASKI_BITTI, "Baskı tamamlandı"),
    (O_FILAMENT_YOK, "Filament bitti"),
    (O_KOPTU, "Bağlantı koptu"),
    (O_BAGLANDI, "Bağlantı kuruldu"),
    (O_HATA_GECTI, "Hata giderildi"),
    (O_DURAKLATILDI, "Baskı duraklatıldı"),
    (O_BASKI_BASLADI, "Baskı başladı"),
]
VARSAYILAN_OLAYLAR = [O_HATA, O_BASKI_BITTI, O_FILAMENT_YOK]
SIMGE = {
    O_HATA: "🔴", O_BASKI_BITTI: "✅", O_FILAMENT_YOK: "🟠", O_KOPTU: "⚠️",
    O_BAGLANDI: "🔌", O_HATA_GECTI: "🟢", O_DURAKLATILDI: "⏸", O_BASKI_BASLADI: "▶️",
}


def _sure(sn) -> str:
    if not isinstance(sn, (int, float)) or sn <= 0:
        return ""
    sn = int(sn)
    s, d = sn // 3600, (sn % 3600) // 60
    return f"{s} sa {d} dk" if s else f"{d} dk"


def olay_satiri(olay: dict) -> str:
    """Tek olayı Telegram HTML satırına çevirir."""
    tur = olay.get("tur", "")
    mesaj = html.escape(olay.get("mesaj", ""))
    ek = ""
    if tur == O_BASKI_BITTI:
        s = _sure((olay.get("veri") or {}).get("sure_sn"))
        if s:
            ek = f" <i>({s})</i>"
    return f"{SIMGE.get(tur, '•')} {mesaj}{ek}"


def mesaj_olustur(olaylar: list[dict]) -> str:
    if len(olaylar) == 1:
        return f"<b>CreaManage</b>\n{olay_satiri(olaylar[0])}"
    satirlar = [olay_satiri(o) for o in olaylar[:EN_FAZLA_SATIR]]
    if len(olaylar) > EN_FAZLA_SATIR:
        satirlar.append(f"… ve {len(olaylar) - EN_FAZLA_SATIR} olay daha")
    return f"<b>CreaManage · {len(olaylar)} olay</b>\n" + "\n".join(satirlar)


TOKEN_KALIBI = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")


def token_temizle(ham) -> str:
    """Yapıştırma artıklarını ayıklar: boşluk, 'bot' öneki, tırnak, URL parçası."""
    t = str(ham or "").strip().strip("'\"")
    t = re.sub(r"\s+", "", t)
    m = re.search(r"(\d{6,12}:[A-Za-z0-9_-]{30,50})", t)
    return m.group(1) if m else t


def token_gecerli_mi(token: str) -> bool:
    return bool(TOKEN_KALIBI.match(token or ""))


def _sohbetleri_ayikla(metin) -> list[str]:
    if isinstance(metin, list):
        parcalar = [str(p) for p in metin]
    else:
        parcalar = str(metin or "").replace(";", ",").replace("\n", ",").split(",")
    sonuc = []
    for p in parcalar:
        p = p.strip()
        if p and p not in sonuc:
            sonuc.append(p)
    return sonuc


class TelegramBildirici:
    def __init__(self, vt, api_taban: str = API_TABAN) -> None:
        self.vt = vt
        self.api_taban = api_taban.rstrip("/")
        self.ayar = {"etkin": False, "token": "", "sohbetler": [], "olaylar": list(VARSAYILAN_OLAYLAR)}
        self.bot_adi = ""
        self._kuyruk: list[dict] = []
        self._gorev: asyncio.Task | None = None
        self._kilit = asyncio.Lock()
        self.son_gonderim: float | None = None
        self.son_hata = ""
        self.gonderilen = 0
        self.yukle()

    # --- ayarlar ---
    def yukle(self) -> None:
        kayit = self.vt.ayar_oku(AYAR_ANAHTARI)
        if isinstance(kayit, dict):
            self.ayar.update({k: kayit[k] for k in ("etkin", "token", "sohbetler", "olaylar") if k in kayit})
            self.ayar["sohbetler"] = _sohbetleri_ayikla(self.ayar["sohbetler"])

    def kaydet(self, yeni: dict) -> dict:
        if "token" in yeni and str(yeni["token"]).strip():
            token = token_temizle(yeni["token"])                 # boş gelirse mevcut korunur
            if not token_gecerli_mi(token):
                raise ValueError("belirteç biçimi hatalı; BotFather'ın verdiği '123456789:AA…' satırını yapıştırın")
            self.ayar["token"] = token
        if "sohbetler" in yeni:
            self.ayar["sohbetler"] = _sohbetleri_ayikla(yeni["sohbetler"])
        if "olaylar" in yeni and isinstance(yeni["olaylar"], list):
            gecerli = {t for t, _ in SECILEBILIR_OLAYLAR}
            self.ayar["olaylar"] = [t for t in yeni["olaylar"] if t in gecerli]
        if "etkin" in yeni:
            self.ayar["etkin"] = bool(yeni["etkin"])
        self.vt.ayar_yaz(AYAR_ANAHTARI, self.ayar)
        return self.gorunum()

    def gorunum(self) -> dict:
        t = self.ayar["token"]
        return {
            "etkin": self.ayar["etkin"],
            "token_var": bool(t),
            "token_gecerli": token_gecerli_mi(t),
            "token_maske": (t[:6] + "…" + t[-4:]) if len(t) > 12 else ("•••" if t else ""),
            "bot_adi": self.bot_adi,
            "sohbetler": list(self.ayar["sohbetler"]),
            "olaylar": list(self.ayar["olaylar"]),
            "secilebilir": [{"tur": t, "ad": a} for t, a in SECILEBILIR_OLAYLAR],
            "son_gonderim": self.son_gonderim,
            "son_hata": self.son_hata,
            "gonderilen": self.gonderilen,
            "bekleyen": len(self._kuyruk),
        }

    @property
    def hazir(self) -> bool:
        return bool(self.ayar["etkin"] and self.ayar["token"] and self.ayar["sohbetler"])

    # --- olay akışı ---
    async def olay_geldi(self, olay: dict) -> None:
        """OlayMerkezi abonesi."""
        if not self.hazir or olay.get("tur") not in self.ayar["olaylar"]:
            return
        self._kuyruk.append(olay)
        if self._gorev is None or self._gorev.done():
            self._gorev = asyncio.create_task(self._toplayip_gonder())

    async def _toplayip_gonder(self) -> None:
        await asyncio.sleep(TOPLAMA_PENCERESI_SN)
        async with self._kilit:
            olaylar, self._kuyruk = self._kuyruk, []
            if not olaylar:
                return
            await self.metin_gonder(mesaj_olustur(olaylar))

    async def bekle(self) -> None:
        """Testler için: bekleyen toplu gönderim bitene dek bekler."""
        if self._gorev is not None and not self._gorev.done():
            await self._gorev

    # --- Telegram API ---
    async def _api(self, yontem: str, veri: dict | None = None, token: str | None = None) -> dict:
        token = token_temizle(token) if token else self.ayar["token"]
        if not token:
            raise RuntimeError("bot belirteci girilmemiş")
        if not token_gecerli_mi(token):
            raise RuntimeError("belirteç biçimi hatalı ('123456789:AA…' beklenir)")
        url = f"{self.api_taban}/bot{token}/{yontem}"
        zaman = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=zaman) as oturum:
            for deneme in range(3):
                async with oturum.post(url, json=veri or {}) as yanit:
                    try:
                        govde = await yanit.json(content_type=None)
                    except ValueError:
                        govde = {}
                    if yanit.status == 429:
                        bekle = float((govde.get("parameters") or {}).get("retry_after", 2))
                        await asyncio.sleep(min(bekle, 30))
                        continue
                    if not govde.get("ok"):
                        aciklama = govde.get("description") or f"HTTP {yanit.status}"
                        if yanit.status == 404:
                            aciklama += " (belirteç biçimi hatalı olabilir)"
                        elif yanit.status == 401:
                            aciklama += " (belirteç geçersiz ya da iptal edilmiş)"
                        raise RuntimeError(aciklama)
                    return govde.get("result", {})
        raise RuntimeError("Telegram hız sınırı: 3 denemede gönderilemedi")

    async def metin_gonder(self, metin: str, sohbetler: list[str] | None = None,
                           token: str | None = None) -> list[str]:
        """Her sohbete gönderir; hata veren sohbetleri listeler (istisna fırlatmaz)."""
        hatalar = []
        for sohbet in (sohbetler or self.ayar["sohbetler"]):
            try:
                await self._api("sendMessage", {"chat_id": sohbet, "text": metin,
                                                "parse_mode": "HTML", "disable_web_page_preview": True}, token)
                self.gonderilen += 1
                self.son_gonderim = time.time()
            except Exception as e:  # noqa: BLE001
                hatalar.append(f"{sohbet}: {e}")
                log.warning("Telegram gönderimi başarısız (%s): %s", sohbet, e)
        self.son_hata = "; ".join(hatalar)
        return hatalar

    async def test_mesaji(self, token: str | None = None, sohbetler: list[str] | None = None) -> list[str]:
        return await self.metin_gonder("<b>CreaManage</b>\n🔔 Test bildirimi — Telegram bağlantısı çalışıyor.",
                                       sohbetler, token)

    async def sohbetleri_bul(self, token: str | None = None) -> list[dict]:
        """Bota yazan sohbetleri getUpdates ile listeler (kullanıcı önce bota /start yazar)."""
        guncellemeler = await self._api("getUpdates", {"limit": 100, "allowed_updates": ["message", "channel_post", "my_chat_member"]}, token)
        gorulen: dict[str, dict] = {}
        for g in guncellemeler if isinstance(guncellemeler, list) else []:
            m = g.get("message") or g.get("channel_post") or (g.get("my_chat_member") or {})
            sohbet = m.get("chat") if isinstance(m, dict) else None
            if not sohbet:
                continue
            kimlik = str(sohbet.get("id"))
            ad = sohbet.get("title") or " ".join(x for x in (sohbet.get("first_name"), sohbet.get("last_name")) if x) or sohbet.get("username") or kimlik
            gorulen[kimlik] = {"id": kimlik, "ad": ad, "tur": sohbet.get("type", "")}
        return list(gorulen.values())

    async def bot_bilgisi(self, token: str | None = None) -> dict:
        b = await self._api("getMe", {}, token)
        bilgi = {"kullanici_adi": b.get("username", ""), "ad": b.get("first_name", "")}
        if not token or token_temizle(token) == self.ayar["token"]:
            self.bot_adi = bilgi["kullanici_adi"]
        return bilgi
