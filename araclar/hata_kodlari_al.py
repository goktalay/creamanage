#!/usr/bin/env python3
"""Creality hata kodu tablosunu indirip creamanage/veri/hata_kodlari.json dosyasına yazar.

  python3 araclar/hata_kodlari_al.py                    # Creality K2 Plus sayfasından
  python3 araclar/hata_kodlari_al.py --url <adres>      # başka bir sayfadan (K2 Pro, K1…)
  python3 araclar/hata_kodlari_al.py --csv tablo.csv    # kod;başlık;açıklama;çözüm;modül
  python3 araclar/hata_kodlari_al.py --html sayfa.html  # kaydedilmiş sayfadan

Sayfadaki tüm HTML tabloları taranır; ilk hücresi 3-4 haneli sayı olan satırlar kod olarak
alınır. Mevcut tablo ile birleştirilir (aynı kod → yeni değer).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creamanage import hata_kodlari as H  # noqa: E402

KOD = re.compile(r"^\s*(?:[A-Za-z]{1,3}[-_ ]?)?(\d{3,5})\s*$")


class TabloAyristirici(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tablolar: list[list[list[str]]] = []
        self._satir: list[str] | None = None
        self._hucre: list[str] | None = None
        self._basliklar: list[str] = []
        self._son_baslik = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tablolar.append([])
        elif tag == "tr":
            self._satir = []
        elif tag in ("td", "th"):
            self._hucre = []
        elif tag in ("h1", "h2", "h3", "h4"):
            self._hucre = []
            self._baslik_modu = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._hucre is not None and self._satir is not None:
            self._satir.append(re.sub(r"\s+", " ", "".join(self._hucre)).strip()); self._hucre = None
        elif tag == "tr" and self._satir is not None and self.tablolar:
            self.tablolar[-1].append(self._satir); self._satir = None
        elif tag in ("h1", "h2", "h3", "h4") and self._hucre is not None:
            self._son_baslik = re.sub(r"\s+", " ", "".join(self._hucre)).strip(); self._hucre = None
            if self.tablolar is not None:
                self._basliklar.append(self._son_baslik)

    def handle_data(self, veri):
        if self._hucre is not None:
            self._hucre.append(veri)


def html_ayristir(html: str) -> dict:
    a = TabloAyristirici(); a.feed(html)
    kodlar: dict = {}
    for tablo in a.tablolar:
        if not tablo:
            continue
        baslik = [h.lower() for h in tablo[0]]
        for satir in tablo:
            if len(satir) < 2:
                continue
            m = KOD.match(satir[0])
            if not m:
                continue
            kod = m.group(1)
            metinler = [x for x in satir[1:] if x]
            kayit = {"tam_kod": satir[0].strip(), "baslik": metinler[0] if metinler else "", "aciklama": metinler[1] if len(metinler) > 1 else "",
                     "cozum": " ".join(metinler[2:]) if len(metinler) > 2 else "", "modul": ""}
            # başlık satırında 'solution'/'cause' gibi sütun adları varsa ona göre eşle
            for i, h in enumerate(baslik[1:], start=1):
                if i < len(satir):
                    if "solution" in h or "çözüm" in h or "handling" in h or "fix" in h:
                        kayit["cozum"] = satir[i]
                    elif "cause" in h or "reason" in h or "description" in h or "meaning" in h or "açıklama" in h:
                        kayit["aciklama"] = satir[i]
                    elif "module" in h or "modül" in h:
                        kayit["modul"] = satir[i]
            kodlar[kod] = kayit
    return kodlar


def csv_ayristir(yol: str) -> dict:
    kodlar = {}
    with open(yol, encoding="utf-8-sig", newline="") as f:
        for satir in csv.reader(f, delimiter=";"):
            if len(satir) < 2 or not KOD.match(satir[0]):
                continue
            kodlar[KOD.match(satir[0]).group(1)] = {"baslik": satir[1], "aciklama": satir[2] if len(satir) > 2 else "",
                                                   "cozum": satir[3] if len(satir) > 3 else "", "modul": satir[4] if len(satir) > 4 else ""}
    return kodlar


def ana(argv=None) -> int:
    p = argparse.ArgumentParser(description="Creality hata kodu tablosunu indir")
    p.add_argument("--url", default=H.CREALITY_SAYFA)
    p.add_argument("--csv"); p.add_argument("--html")
    n = p.parse_args(argv)
    if n.csv:
        yeni, kaynak = csv_ayristir(n.csv), n.csv
    else:
        if n.html:
            html, kaynak = Path(n.html).read_text(encoding="utf-8", errors="ignore"), n.html
        else:
            print("İndiriliyor:", n.url)
            istek = urllib.request.Request(n.url, headers={"User-Agent": "Mozilla/5.0 (CreaManage)"})
            with urllib.request.urlopen(istek, timeout=30) as y:
                html = y.read().decode("utf-8", errors="ignore")
            kaynak = n.url
        yeni = html_ayristir(html)
    if not yeni:
        print("Tabloda kod bulunamadı. Sayfayı tarayıcıda 'Farklı kaydet' ile HTML olarak kaydedip --html ile verin,"
              " ya da kod;başlık;açıklama;çözüm biçiminde CSV hazırlayıp --csv ile verin.")
        return 1
    mevcut = dict(H.kodlar()); mevcut.update(yeni)
    adet = H.kaydet(mevcut, kaynak)
    print(f"{len(yeni)} kod alındı, tabloda toplam {adet} kod. Dosya: {H.DOSYA}")
    for kod, k in list(yeni.items())[:5]:
        print(f"  {kod}: {k['baslik'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(ana())
