#!/usr/bin/env python3
"""Komut satırından kullanıcı yönetimi — parola unutulduğunda ya da ilk kurulum için.

  python3 araclar/kullanici.py listele
  python3 araclar/kullanici.py ekle <kullanici_adi> --ad "Ad Soyad" --rol sistem_yoneticisi
  python3 araclar/kullanici.py parola <kullanici_adi>          # yeni parola sorar
  python3 araclar/kullanici.py sil <kullanici_adi>
Veritabanı: --veritabani ya da CREAMANAGE_VERITABANI (varsayılan ./creamanage.sqlite)
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creamanage.kullanicilar import ROL_ADLARI, ROLLER, KullaniciYonetimi  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402


def _parola_sor() -> str:
    p1 = getpass.getpass("Parola: ")
    p2 = getpass.getpass("Parola (tekrar): ")
    if p1 != p2:
        sys.exit("Parolalar eşleşmiyor.")
    return p1


def ana(argv=None) -> int:
    p = argparse.ArgumentParser(description="CreaManage kullanıcı aracı")
    p.add_argument("--veritabani", default=os.environ.get("CREAMANAGE_VERITABANI", "creamanage.sqlite"))
    alt = p.add_subparsers(dest="komut", required=True)
    alt.add_parser("listele")
    e = alt.add_parser("ekle"); e.add_argument("kullanici_adi"); e.add_argument("--ad", default="")
    e.add_argument("--rol", choices=list(ROLLER), default="gozetmen"); e.add_argument("--parola", help="verilmezse sorulur")
    pa = alt.add_parser("parola"); pa.add_argument("kullanici_adi"); pa.add_argument("--parola")
    s = alt.add_parser("sil"); s.add_argument("kullanici_adi")
    n = p.parse_args(argv)
    vt = Veritabani(n.veritabani)
    ky = KullaniciYonetimi(vt)
    try:
        if n.komut == "listele":
            for k in ky.listele():
                print(f"{k['kullanici_adi']:<20} {ROL_ADLARI[k['rol']]:<20} {'etkin' if k['etkin'] else 'PASİF':<6} {k['ad']}")
            if not ky.listele():
                print("Kullanıcı yok.")
        elif n.komut == "ekle":
            k = ky.ekle(n.kullanici_adi, n.ad, n.rol, n.parola or _parola_sor())
            print(f"Eklendi: {k['kullanici_adi']} ({k['rol_adi']})")
        elif n.komut == "parola":
            k = vt.kullanici_adiyla(n.kullanici_adi)
            if not k:
                sys.exit("Kullanıcı bulunamadı.")
            ky.guncelle(k["id"], parola=n.parola or _parola_sor())
            print("Parola değiştirildi; kullanıcının oturumları kapatıldı.")
        elif n.komut == "sil":
            k = vt.kullanici_adiyla(n.kullanici_adi)
            if not k:
                sys.exit("Kullanıcı bulunamadı.")
            ky.sil(k["id"])
            print("Silindi.")
    except ValueError as e:
        sys.exit(f"Hata: {e}")
    finally:
        vt.kapat()
    return 0


if __name__ == "__main__":
    sys.exit(ana())
