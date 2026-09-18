"""Dosya kütüphanesi: sunucuda saklanan G-code/3MF dosyaları, önizleme resmi çıkarma.

Yüklenen her dosya ``<dosya_dizini>/<id>_<ad>`` olarak saklanır; aynı içerik (SHA-256)
yeniden yüklenirse mevcut kayıt kullanılır. Önizleme:
  * G-code (Creality Print / OrcaSlicer / PrusaSlicer): ``; thumbnail begin WxH N`` …
    ``; thumbnail end`` blokları (base64 PNG); en büyüğü alınır. ``.gcode.gz`` de açılır.
  * 3MF: zip içindeki ``Metadata/*.png`` (thumbnail).
Ayrıca ``; estimated printing time`` / ``; filament used [mm]`` başlıkları okunur.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import logging
import re
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger("creamanage.dosyalar")
BASLIK_OKU = 4 * 1024 * 1024          # önizleme için dosyanın ilk 4 MB'ı yeter
_ZAMAN = re.compile(r";\s*(?:estimated printing time.*?|TIME)\s*[:=]\s*(.+)", re.I)
_FILAMENT = re.compile(r";\s*filament used \[mm\]\s*[:=]\s*([\d.]+)", re.I)


def sha256_hesapla(yol: str | Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1024 * 1024), b""):
            h.update(parca)
    return h.hexdigest()


def _sure_saniye(metin: str) -> int | None:
    metin = metin.strip().lower()
    if metin.isdigit():
        return int(metin)
    toplam, bulundu = 0, False
    for sayi, birim in re.findall(r"(\d+)\s*([dhms])", metin):
        toplam += int(sayi) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[birim]; bulundu = True
    return toplam if bulundu else None


def gcode_bilgi(yol: str | Path) -> dict:
    """{"resim": bytes|None, "tahmini_sn": int|None, "filament_mm": float|None}"""
    sonuc: dict = {"resim": None, "tahmini_sn": None, "filament_mm": None}
    yol = Path(yol)
    ad = yol.name.lower()
    try:
        if ad.endswith(".3mf"):
            with zipfile.ZipFile(yol) as z:
                adaylar = [n for n in z.namelist() if n.lower().endswith(".png") and "thumbnail" in n.lower()] or \
                          [n for n in z.namelist() if n.lower().startswith("metadata/") and n.lower().endswith(".png")]
                if adaylar:
                    en = max(adaylar, key=lambda n: z.getinfo(n).file_size)
                    sonuc["resim"] = z.read(en)
            return sonuc
        if ad.endswith(".gz"):
            with gzip.open(yol, "rb") as f:
                veri = f.read(BASLIK_OKU)
        else:
            with open(yol, "rb") as f:
                veri = f.read(BASLIK_OKU)
    except (OSError, zipfile.BadZipFile, EOFError) as e:
        log.debug("önizleme okunamadı %s: %s", yol, e)
        return sonuc
    metin = veri.decode("utf-8", errors="ignore")
    en_buyuk, en_alan = None, -1
    for m in re.finditer(r";\s*thumbnail(?:_JPG|_QOI)? begin (\d+)x(\d+) (\d+)\s*\n(.*?);\s*thumbnail(?:_JPG|_QOI)? end", metin, re.S | re.I):
        if "_JPG" in m.group(0)[:40].upper() or "_QOI" in m.group(0)[:40].upper():
            continue
        alan = int(m.group(1)) * int(m.group(2))
        if alan > en_alan:
            en_alan, en_buyuk = alan, m.group(4)
    if en_buyuk:
        b64 = "".join(satir.strip().lstrip(";").strip() for satir in en_buyuk.splitlines())
        try:
            png = base64.b64decode(b64)
            if png.startswith(b"\x89PNG"):
                sonuc["resim"] = png
        except ValueError:
            pass
    z = _ZAMAN.search(metin)
    if z:
        sonuc["tahmini_sn"] = _sure_saniye(z.group(1))
    fm = _FILAMENT.search(metin)
    if fm:
        try:
            sonuc["filament_mm"] = float(fm.group(1))
        except ValueError:
            pass
    return sonuc


class DosyaKutuphanesi:
    def __init__(self, vt, dizin: str | Path) -> None:
        self.vt = vt
        self.dizin = Path(dizin)
        self.dizin.mkdir(parents=True, exist_ok=True)
        (self.dizin / "resimler").mkdir(exist_ok=True)

    def ekle(self, gecici_yol: str | Path, ad: str, kullanici: dict | None, aciklama: str = "") -> tuple[dict, bool]:
        """Geçici dosyayı kütüphaneye taşır. (kayıt, yeni_mi) döndürür; aynı içerik varsa onu verir."""
        sha = sha256_hesapla(gecici_yol)
        mevcut = self.vt.dosya_sha_ile(sha)
        if mevcut and Path(mevcut["yol"]).exists():
            if aciklama and not mevcut.get("aciklama"):
                mevcut = self.vt.dosya_guncelle(mevcut["id"], aciklama=aciklama) or mevcut
            return mevcut, False
        boyut = Path(gecici_yol).stat().st_size
        bilgi = gcode_bilgi(gecici_yol)
        kayit = self.vt.dosya_ekle(ad, "", boyut, sha, (kullanici or {}).get("id"), (kullanici or {}).get("kullanici_adi", ""),
                                   aciklama, "", bilgi["tahmini_sn"], bilgi["filament_mm"])
        hedef = self.dizin / f"{kayit['id']}_{ad}"
        shutil.move(str(gecici_yol), hedef)
        resim_yol = ""
        if bilgi["resim"]:
            resim = self.dizin / "resimler" / f"{kayit['id']}.png"
            resim.write_bytes(bilgi["resim"]); resim_yol = str(resim)
        kayit = self.vt.dosya_guncelle(kayit["id"], resim_yol=resim_yol) or kayit
        # yol sütunu doğrudan güncellenmez (izinli değil) → ayrı sorgu
        self.vt._yaz("UPDATE dosyalar SET yol=? WHERE id=?", (str(hedef), kayit["id"]))
        kayit = self.vt.dosya(kayit["id"]) or kayit
        return kayit, True

    def sil(self, dosya_id: int) -> bool:
        d = self.vt.dosya(dosya_id)
        if d is None:
            return False
        for yol in (d.get("yol"), d.get("resim_yol")):
            if yol:
                try:
                    Path(yol).unlink()
                except OSError:
                    pass
        return self.vt.dosya_sil(dosya_id)

    @staticmethod
    def gorunum(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in ("yol",)} | {"resim_var": bool(d.get("resim_yol")), "var": Path(d["yol"]).exists() if d.get("yol") else False}
