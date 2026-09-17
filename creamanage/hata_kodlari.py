"""Creality hata kodlarını anlamlı metne çevirir.

Tablo ``creamanage/veri/hata_kodlari.json`` dosyasındadır: ``{"kodlar": {"2060": {"baslik": …,
"aciklama": …, "cozum": …, "modul": …}}}``. Creality'nin yayımladığı tabloyu indirip bu
dosyaya yazmak için ``araclar/hata_kodlari_al.py`` kullanılır. Yazıcı ``err`` alanında
``errcode`` (genel sınıf, ör. 500) ve ``key`` (asıl kod, ör. 2718) gönderir; önce ``key``,
sonra ``errcode`` aranır.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("creamanage.hata_kodlari")
DOSYA = Path(__file__).resolve().parent / "veri" / "hata_kodlari.json"
CREALITY_SAYFA = "https://store.creality.com/blogs/all/creality-k2-plus-error-code-troubleshooting"

# errcode sınıfları (topluluk gözlemi; kesin tablo key alanındadır)
ERRCODE_SINIFI = {
    100: "Bilgi", 200: "Uyarı", 208: "Uyarı", 300: "Baskı durdu", 400: "Donanım", 500: "Kritik hata",
}

_tablo: dict = {}
_yuklendi = 0.0


def yukle(zorla: bool = False) -> dict:
    global _tablo, _yuklendi
    try:
        mtime = DOSYA.stat().st_mtime
    except OSError:
        mtime = 0.0
    if zorla or not _tablo or mtime > _yuklendi:
        try:
            _tablo = json.loads(DOSYA.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("hata kodu tablosu okunamadı: %s", e)
            _tablo = {"kodlar": {}}
        _yuklendi = time.time()
    return _tablo


def kodlar() -> dict:
    return yukle().get("kodlar", {})


def bilgi() -> dict:
    t = yukle()
    return {"adet": len(t.get("kodlar", {})), "kaynak": t.get("_kaynak", ""), "guncelleme": t.get("_guncelleme", ""),
            "dosya": str(DOSYA), "creality_sayfa": CREALITY_SAYFA}


def _bul(k: dict, kod: str):
    """'CY2586', '2586', '0115', '115' biçimlerinin hepsini aynı kayda götürür."""
    kod = str(kod).strip()
    sayi = "".join(ch for ch in kod if ch.isdigit())
    for aday in (kod, sayi, sayi.lstrip("0") or "0", sayi.zfill(4)):
        if aday in k:
            return k[aday]
    return None


def acikla(errcode, key=None) -> dict:
    """{"kod", "sinif", "baslik", "aciklama", "cozum", "modul", "metin", "bilinen", "tam_kod"}"""
    k = kodlar()
    kod = str(key).strip() if key not in (None, "", 0, "0") else ""
    if kod:
        kayit = _bul(k, kod)                      # asıl kod key alanındadır; errcode yalnız sınıftır
    elif errcode not in (None, "", 0, "0"):
        kod = str(errcode).strip()
        kayit = k.get(kod) or k.get(kod.lstrip("0") or "0")
    else:
        kayit = None
    try:
        sinif = ERRCODE_SINIFI.get(int(errcode), "")
    except (TypeError, ValueError):
        sinif = ""
    sonuc = {"kod": kod or str(errcode or ""), "errcode": errcode, "sinif": sinif, "bilinen": kayit is not None,
             "baslik": "", "aciklama": "", "cozum": "", "modul": "", "tam_kod": ""}
    if kayit:
        sonuc.update({x: str(kayit.get(x, "")) for x in ("baslik", "aciklama", "cozum", "modul", "tam_kod")})
        sonuc["metin"] = sonuc["baslik"] or sonuc["aciklama"] or f"Hata {kod}"
    else:
        sonuc["metin"] = (f"{sinif}: " if sinif else "") + f"kod {sonuc['kod']} (açıklaması tabloda yok)"
    return sonuc


def kanonik(kod) -> str:
    """'CM0115' / '0115' / 115 → '115' (tek anahtar biçimi)."""
    sayi = "".join(ch for ch in str(kod or "") if ch.isdigit())
    return str(int(sayi)) if sayi else ""


def kaydet(kodlar_sozlugu: dict, kaynak: str = "") -> int:
    birlesik: dict = {}
    for k, v in kodlar_sozlugu.items():
        anahtar = kanonik(k)
        if anahtar and isinstance(v, dict):
            birlesik[anahtar] = v
    veri = {"_aciklama": yukle().get("_aciklama", ""), "_kaynak": kaynak or yukle().get("_kaynak", ""),
            "_guncelleme": time.strftime("%Y-%m-%d %H:%M"), "kodlar": dict(sorted(birlesik.items(), key=lambda x: int(x[0])))}
    DOSYA.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    yukle(zorla=True)
    return len(veri["kodlar"])


ALANLAR = ("tam_kod", "baslik", "aciklama", "cozum", "modul", "yazicilar")


def kod_kaydet(kod, kayit: dict) -> dict:
    """Tek kodu ekler/günceller; kayıt döndürür."""
    anahtar = kanonik(kod)
    if not anahtar:
        raise ValueError("kod sayısal bir bölüm içermeli (ör. CA2070 ya da 2070)")
    temiz = {a: str(kayit.get(a, "") or "").strip()[:2000] for a in ALANLAR}
    if not temiz["baslik"]:
        raise ValueError("başlık boş olamaz")
    if not temiz["tam_kod"]:
        temiz["tam_kod"] = str(kod).strip().upper()
    k = dict(kodlar()); k[anahtar] = temiz
    kaydet(k)
    return dict(temiz, kod=anahtar)


def kod_sil(kod) -> bool:
    anahtar = kanonik(kod)
    k = dict(kodlar())
    if anahtar not in k:
        return False
    del k[anahtar]
    kaydet(k)
    return True


def listele() -> list[dict]:
    return [dict(v, kod=k) for k, v in sorted(kodlar().items(), key=lambda x: int(x[0]))]
