#!/usr/bin/env python3
"""CREAMANAGE giriş noktası: ``python3 main.py --port 8090``"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiohttp import web  # noqa: E402

from creamanage.ayarlar import ayarlari_oku  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.kullanicilar import KullaniciYonetimi  # noqa: E402
from creamanage.surum import FIRMA, SURUM, URUN_ADI  # noqa: E402
from creamanage.telegram import TelegramBildirici  # noqa: E402
from creamanage.telemetri_kayit import TelemetriKayit  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import uygulama_olustur  # noqa: E402


def _windows_gurultusunu_sustur(loop: asyncio.AbstractEventLoop) -> None:
    """Windows Proactor: tarayıcı bağlantıyı aniden kapatınca zararsız ConnectionResetError loglanır."""
    varsayilan = loop.get_exception_handler()

    def ele(loop_, baglam):
        istisna = baglam.get("exception")
        if isinstance(istisna, ConnectionResetError) and "_call_connection_lost" in str(baglam.get("handle", "")):
            return
        (varsayilan or loop_.default_exception_handler)(baglam)

    loop.set_exception_handler(ele)


async def calistir(argv: list[str] | None = None) -> None:
    ayar = ayarlari_oku(argv)
    if sys.platform == "win32":
        _windows_gurultusunu_sustur(asyncio.get_running_loop())
    logging.basicConfig(level=getattr(logging, ayar.log_seviye, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("creamanage")
    vt = Veritabani(ayar.veritabani)
    telemetri = TelemetriKayit(ayar.telemetri_dizini, ayar.telemetri_saklama_gun)
    filo = Filo(vt, telemetri)
    telegram = TelegramBildirici(vt, api_taban=os.environ.get("CREAMANAGE_TELEGRAM_API") or "https://api.telegram.org")
    filo.olaylar.abone_ol(telegram.olay_geldi)
    await filo.baslat()
    kullanicilar = KullaniciYonetimi(vt)
    app = uygulama_olustur(filo, telegram, kullanicilar)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, ayar.host, ayar.port)
    await site.start()
    log.info("%s %s — %s — http://%s:%d/", URUN_ADI, SURUM, FIRMA, ayar.host, ayar.port)
    log.info("telemetri kaydı: %s (saklama %d gün, saniyede 1 örnek)", ayar.telemetri_dizini, ayar.telemetri_saklama_gun)
    if not kullanicilar.kullanici_var_mi():
        log.warning("Henüz kullanıcı yok: tarayıcıda /giris adresi ilk sistem yöneticisini oluşturmanızı isteyecek.")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        vt.kapat()


if __name__ == "__main__":
    try:
        asyncio.run(calistir())
    except KeyboardInterrupt:
        pass
