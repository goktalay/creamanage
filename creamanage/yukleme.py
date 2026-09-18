"""Yazıcıya dosya yükleme (HTTP) ve model sorgusu.

Creality Print'in K1/K2 için kullandığı yol (OrcaSlicer CrealityPrint.cpp'den):
  POST http://<ip>[:80]/upload/<url-kodlu dosya adı>   multipart, alan adı "file"
  GET  http://<ip>[:80]/info                            → {"model": "F008", ...}
Yüklenen dosya K2 Plus'ta /mnt/UDISK/printer_data/gcodes/ altına düşer; baskı
WebSocket'ten {"method":"set","params":{"opGcodeFile":"printprt:<tam yol>"}} ile başlar.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import urllib.parse
from pathlib import Path

import aiohttp

log = logging.getLogger("creamanage.yukleme")

HTTP_PORT_VARSAYILAN = 80
HTTP_PORTLAR = (80, 4408)                   # stok web sunucusu; bazı sürümlerde 4408
GCODE_DIZINI_VARSAYILAN = "/mnt/UDISK/printer_data/gcodes"   # K2 ailesi (K1: /usr/data/printer_data/gcodes)
IZINLI_UZANTILAR = (".gcode", ".gcode.gz", ".gco", ".g", ".3mf")
EN_BUYUK_DOSYA = 1024 * 1024 * 1024         # 1 GB
PARCA_BAYT = 4 * 1024 * 1024               # tarayıcıdan parçalı yüklemede önerilen parça boyutu
_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
MODEL_ADLARI = {"F008": "K2 Plus", "F012": "K2 Pro", "F021": "K2", "F022": "SPARKX i7",
                "F001": "K1", "F002": "K1 Max", "F005": "K1C", "F011": "K1 SE"}


def guvenli_dosya_adi(ad: str) -> str:
    """Yol parçalarını atar, Türkçe karakterleri sadeleştirir, boşlukları alt çizgi yapar."""
    ad = str(ad or "").replace("\\", "/")
    if "%" in ad:
        ad = urllib.parse.unquote(ad)            # bazı istemciler dosya adını URL-kodlu gönderir
    ad = Path(ad).name.translate(_TR)
    ad = unicodedata.normalize("NFKD", ad).encode("ascii", "ignore").decode()
    ad = re.sub(r"\s+", "_", ad.strip())
    ad = re.sub(r"[^A-Za-z0-9._()\-+]", "_", ad)
    ad = ad.strip("._")
    return ad[:120] if ad else "dosya.gcode"


def uzanti_izinli_mi(ad: str) -> bool:
    a = ad.lower()
    return any(a.endswith(u) for u in IZINLI_UZANTILAR)


def hedef_yol(dizin: str, dosya_adi: str) -> str:
    return f"{(dizin or GCODE_DIZINI_VARSAYILAN).rstrip('/')}/{dosya_adi}"


async def bilgi(ip: str, port: int = HTTP_PORT_VARSAYILAN, zaman_asimi: float = 5.0) -> dict:
    """GET /info — model kodu (F008 = K2 Plus) ve diğer kimlik alanları."""
    zaman = aiohttp.ClientTimeout(total=zaman_asimi)
    async with aiohttp.ClientSession(timeout=zaman) as oturum:
        async with oturum.get(f"http://{ip}:{port}/info") as yanit:
            if yanit.status != 200:
                raise RuntimeError(f"/info HTTP {yanit.status}")
            veri = await yanit.json(content_type=None)
    if not isinstance(veri, dict):
        raise RuntimeError("/info beklenmeyen yanıt")
    veri["model_adi"] = MODEL_ADLARI.get(str(veri.get("model", "")), str(veri.get("model", "")))
    return veri


async def dosya_yukle(ip: str, dosya_adi: str, yerel_yol: str | Path, port: int = HTTP_PORT_VARSAYILAN,
                      zaman_asimi: float = 600.0) -> dict:
    """Dosyayı yazıcıya yükler; {"port": kullanılan port, "durum": HTTP kodu, "yanit": metin}."""
    dosya_adi = guvenli_dosya_adi(dosya_adi)
    url_ad = urllib.parse.quote(dosya_adi, safe="")
    zaman = aiohttp.ClientTimeout(total=zaman_asimi, sock_connect=5)
    son_hata = ""
    portlar = [port] + [p for p in HTTP_PORTLAR if p != port]
    for p in portlar:
        url = f"http://{ip}:{p}/upload/{url_ad}"
        try:
            async with aiohttp.ClientSession(timeout=zaman) as oturum:
                with open(yerel_yol, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("file", f, filename=dosya_adi, content_type="application/octet-stream")
                    async with oturum.post(url, data=form) as yanit:
                        metin = (await yanit.text())[:300]
                        if 200 <= yanit.status < 300:
                            return {"port": p, "durum": yanit.status, "yanit": metin, "dosya_adi": dosya_adi}
                        son_hata = f"{url}: HTTP {yanit.status} {metin}".strip()
                        if yanit.status not in (404, 405):
                            break                # uç var ama yükleme reddedildi; başka port deneme
        except (aiohttp.ClientError, OSError) as e:
            son_hata = f"{url}: {e}"
            continue
    raise RuntimeError(f"yükleme başarısız — {son_hata}")
