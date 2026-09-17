"""Çalışma ayarları: komut satırı ve ortam değişkenleri (CREAMANAGE_*)."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Ayarlar:
    host: str = "0.0.0.0"
    port: int = 8090
    veritabani: str = "creamanage.sqlite"
    log_seviye: str = "INFO"
    telemetri_dizini: str = ""
    telemetri_saklama_gun: int = 30


def ayarlari_oku(argv: list[str] | None = None) -> Ayarlar:
    a = Ayarlar(
        host=os.environ.get("CREAMANAGE_HOST", "0.0.0.0"),
        port=int(os.environ.get("CREAMANAGE_PORT", "8090")),
        veritabani=os.environ.get("CREAMANAGE_VERITABANI", str(Path.cwd() / "creamanage.sqlite")),
        log_seviye=os.environ.get("CREAMANAGE_LOG", "INFO"),
        telemetri_dizini=os.environ.get("CREAMANAGE_TELEMETRI", ""),
        telemetri_saklama_gun=int(os.environ.get("CREAMANAGE_TELEMETRI_GUN", "30")),
    )
    p = argparse.ArgumentParser(description="CreaManage (CREAMANAGE)")
    p.add_argument("--host", default=a.host, help="dinlenecek adres (varsayılan 0.0.0.0)")
    p.add_argument("--port", type=int, default=a.port, help="web portu (varsayılan 8090)")
    p.add_argument("--veritabani", default=a.veritabani, help="SQLite dosya yolu")
    p.add_argument("--log", default=a.log_seviye, help="log seviyesi (DEBUG/INFO/WARNING)")
    p.add_argument("--telemetri", default=a.telemetri_dizini, help="yazıcı telemetri SQLite dizini (varsayılan: <veritabanı>_telemetri/)")
    p.add_argument("--telemetri-gun", type=int, default=a.telemetri_saklama_gun, help="telemetri saklama süresi, gün (varsayılan 30)")
    n = p.parse_args(argv)
    telemetri = n.telemetri or str(Path(n.veritabani).with_suffix("")) + "_telemetri"
    return Ayarlar(host=n.host, port=n.port, veritabani=n.veritabani, log_seviye=n.log.upper(),
                   telemetri_dizini=telemetri, telemetri_saklama_gun=n.telemetri_gun)
