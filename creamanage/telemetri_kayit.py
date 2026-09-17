"""Yazıcı başına ayrı SQLite dosyasına telemetri ve değişiklik kaydı.

Her yazıcı için ``<dizin>/yazici_<id>.sqlite`` açılır. Kayıt döngüsü saniyede bir
çalışır: yazıcının özeti (sıcaklıklar, ilerleme, durum, bağlantı…) bir önceki
örnekten farklıysa ``ornekler`` tablosuna yeni satır yazılır (değişmeyen saniyeler
atlanır, dosya şişmez). Ayrıca durum, bağlantı, hata, dosya, IP gibi alanların her
değişimi ``degisimler`` tablosuna (eski → yeni) ayrıca işlenir; hata geçmişi ve
ağ/bağlantı geçmişi buradan okunur. Eski kayıtlar ``saklama_gun`` sonra silinir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("creamanage.telemetri")

ORNEK_ALANLARI = ("durum", "baglanti", "state_kodu", "device_state", "dosya", "ilerleme", "katman",
                  "toplam_katman", "kalan_sn", "gecen_sn", "nozul", "nozul_hedef", "tabla", "tabla_hedef",
                  "kabin", "kabin_hedef", "fan", "hiz_yuzde", "isik", "filament_yok", "hata_kodu", "hata_anahtari")
DEGISIM_ALANLARI = ("durum", "baglanti", "hata_kodu", "dosya", "ip", "filament_yok", "son_hata")
SEMA = """
CREATE TABLE IF NOT EXISTS ornekler (
    zaman REAL PRIMARY KEY,
    durum TEXT, baglanti TEXT, state_kodu INTEGER, device_state INTEGER, dosya TEXT,
    ilerleme REAL, katman INTEGER, toplam_katman INTEGER, kalan_sn INTEGER, gecen_sn INTEGER,
    nozul REAL, nozul_hedef REAL, tabla REAL, tabla_hedef REAL, kabin REAL, kabin_hedef REAL,
    fan REAL, hiz_yuzde REAL, isik INTEGER, filament_yok INTEGER, hata_kodu INTEGER, hata_anahtari TEXT
);
CREATE TABLE IF NOT EXISTS degisimler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman REAL NOT NULL,
    alan TEXT NOT NULL,
    eski TEXT,
    yeni TEXT,
    baglam TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS degisimler_zaman ON degisimler(zaman DESC);
CREATE INDEX IF NOT EXISTS degisimler_alan ON degisimler(alan, zaman DESC);
"""


def _m(v):
    """SQLite'a yazılabilir hale getirir (bool → int, dict/list → JSON)."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


class YaziciKaydi:
    def __init__(self, yol: Path) -> None:
        self.yol = yol
        self.bag = sqlite3.connect(str(yol), check_same_thread=False)
        self.bag.row_factory = sqlite3.Row
        self.bag.execute("PRAGMA journal_mode=WAL")
        self.bag.execute("PRAGMA synchronous=NORMAL")
        self.bag.executescript(SEMA)
        self.bag.commit()
        self.son_ornek: dict | None = None
        self.son_degisim: dict = {}
        self.yeni_dosya = self.bag.execute("SELECT COUNT(*) FROM degisimler").fetchone()[0] == 0
        if not self.yeni_dosya:
            # Yeniden başlatmada son bilinen değerler: gereksiz "None → x" satırları yazılmasın
            for satir in self.bag.execute(
                    "SELECT alan, yeni FROM degisimler WHERE id IN (SELECT MAX(id) FROM degisimler GROUP BY alan)").fetchall():
                self.son_degisim[satir["alan"]] = satir["yeni"]

    def kapat(self) -> None:
        try:
            self.bag.close()
        except sqlite3.Error:
            pass


class TelemetriKayit:
    def __init__(self, dizin: str | Path, saklama_gun: int = 30, aralik_sn: float = 1.0) -> None:
        self.dizin = Path(dizin)
        self.dizin.mkdir(parents=True, exist_ok=True)
        self.saklama_gun = saklama_gun
        self.aralik_sn = aralik_sn
        self.kayitlar: dict[int, YaziciKaydi] = {}
        self._gorev: asyncio.Task | None = None
        self._son_temizlik = 0.0
        self.yazilan = 0

    # --- dosya yönetimi ---
    def dosya_yolu(self, yid: int) -> Path:
        return self.dizin / f"yazici_{yid}.sqlite"

    def kayit(self, yid: int) -> YaziciKaydi:
        k = self.kayitlar.get(yid)
        if k is None:
            k = self.kayitlar[yid] = YaziciKaydi(self.dosya_yolu(yid))
        return k

    def kapat(self, yid: int | None = None) -> None:
        for kid in ([yid] if yid is not None else list(self.kayitlar)):
            k = self.kayitlar.pop(kid, None)
            if k:
                k.kapat()

    # --- kayıt ---
    def ornekle(self, yid: int, ozet: dict, kayit_bilgi: dict | None = None, zaman: float | None = None) -> bool:
        """Özet değiştiyse örnek yazar, değişen izlenen alanları degisimler'e işler. Yazıldıysa True."""
        zaman = zaman or time.time()
        k = self.kayit(yid)
        ornek = {a: _m(ozet.get(a)) for a in ORNEK_ALANLARI}
        yazildi = False
        if ornek != k.son_ornek:
            k.bag.execute(
                "INSERT OR REPLACE INTO ornekler(zaman," + ",".join(ORNEK_ALANLARI) + ") VALUES (?" + ",?" * len(ORNEK_ALANLARI) + ")",
                (zaman, *[ornek[a] for a in ORNEK_ALANLARI]))
            k.son_ornek = ornek
            yazildi = True
            self.yazilan += 1
        izlenen = {a: _m(ozet.get(a)) for a in DEGISIM_ALANLARI if a != "ip"}
        if kayit_bilgi:
            izlenen["ip"] = kayit_bilgi.get("ip")
        if k.son_degisim or k.yeni_dosya:
            for alan, yeni in izlenen.items():
                eski = k.son_degisim.get(alan)
                eski_metin = None if eski is None else str(eski)
                yeni_metin = None if yeni is None else str(yeni)
                if eski_metin != yeni_metin:
                    baglam = ""
                    if alan == "hata_kodu":
                        baglam = str(ozet.get("hata_anahtari") or "")
                    elif alan == "baglanti":
                        baglam = str(ozet.get("son_hata") or "")
                    elif alan == "durum":
                        baglam = str(ozet.get("dosya") or "")
                    k.bag.execute("INSERT INTO degisimler(zaman, alan, eski, yeni, baglam) VALUES (?,?,?,?,?)",
                                  (zaman, alan, eski_metin, yeni_metin, baglam))
                    yazildi = True
        k.yeni_dosya = False
        k.son_degisim = {a: (None if v is None else str(v)) for a, v in izlenen.items()}
        if yazildi:
            k.bag.commit()
        return yazildi

    def temizle(self, simdi: float | None = None) -> None:
        esik = (simdi or time.time()) - self.saklama_gun * 86400
        for k in self.kayitlar.values():
            k.bag.execute("DELETE FROM ornekler WHERE zaman < ?", (esik,))
            k.bag.execute("DELETE FROM degisimler WHERE zaman < ?", (esik,))
            k.bag.commit()

    # --- döngü ---
    def baslat(self, filo) -> None:
        if self._gorev is None or self._gorev.done():
            self._gorev = asyncio.create_task(self._dongu(filo), name="telemetri-kayit")

    async def durdur(self) -> None:
        if self._gorev:
            self._gorev.cancel()
            try:
                await self._gorev
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._gorev = None
        self.kapat()

    async def _dongu(self, filo) -> None:
        while True:
            try:
                await asyncio.sleep(self.aralik_sn)
                simdi = time.time()
                for yid, b in list(filo.baglantilar.items()):
                    try:
                        self.ornekle(yid, b.ozet(), filo.kayitlar.get(yid), simdi)
                    except sqlite3.Error as e:
                        log.warning("telemetri kaydı yazılamadı (yazıcı %s): %s", yid, e)
                if simdi - self._son_temizlik > 3600:
                    self._son_temizlik = simdi
                    await asyncio.to_thread(self.temizle, simdi)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("telemetri kayıt döngüsü hatası")

    # --- sorgular ---
    def ornekler(self, yid: int, baslangic: float | None = None, bitis: float | None = None,
                 limit: int = 1000, adim_sn: float = 0.0) -> list[dict]:
        """Zaman aralığındaki örnekler (en yeni önce). adim_sn > 0 ise seyreltir (ör. 60 = dakikada bir)."""
        if not self.dosya_yolu(yid).exists() and yid not in self.kayitlar:
            return []
        k = self.kayit(yid)
        sql, p = "SELECT * FROM ornekler WHERE 1=1", []
        if baslangic is not None:
            sql += " AND zaman >= ?"; p.append(baslangic)
        if bitis is not None:
            sql += " AND zaman <= ?"; p.append(bitis)
        if adim_sn and adim_sn > 0:
            sql += " GROUP BY CAST(zaman / ? AS INTEGER)"; p.append(adim_sn)
        sql += " ORDER BY zaman DESC LIMIT ?"; p.append(limit)
        return [dict(s) for s in k.bag.execute(sql, p).fetchall()]

    def degisimler(self, yid: int, alan: str | None = None, baslangic: float | None = None,
                   limit: int = 500) -> list[dict]:
        if not self.dosya_yolu(yid).exists() and yid not in self.kayitlar:
            return []
        k = self.kayit(yid)
        sql, p = "SELECT * FROM degisimler WHERE 1=1", []
        if alan:
            sql += " AND alan = ?"; p.append(alan)
        if baslangic is not None:
            sql += " AND zaman >= ?"; p.append(baslangic)
        sql += " ORDER BY id DESC LIMIT ?"; p.append(limit)
        return [dict(s) for s in k.bag.execute(sql, p).fetchall()]

    def hatalar(self, yid: int, limit: int = 200) -> list[dict]:
        """Hata kodunun değiştiği anlar: yeni != 0 → hata başladı, yeni == 0 → geçti."""
        return [dict(d, basladi=(d["yeni"] not in (None, "0", "None", ""))) for d in self.degisimler(yid, "hata_kodu", limit=limit)]

    def ozet(self, yid: int) -> dict:
        if not self.dosya_yolu(yid).exists() and yid not in self.kayitlar:
            return {"ornek": 0, "degisim": 0, "ilk": None, "son": None, "boyut": 0}
        k = self.kayit(yid)
        o = k.bag.execute("SELECT COUNT(*), MIN(zaman), MAX(zaman) FROM ornekler").fetchone()
        d = k.bag.execute("SELECT COUNT(*) FROM degisimler").fetchone()
        try:
            boyut = self.dosya_yolu(yid).stat().st_size
        except OSError:
            boyut = 0
        return {"ornek": o[0], "degisim": d[0], "ilk": o[1], "son": o[2], "boyut": boyut, "dosya": str(self.dosya_yolu(yid))}
