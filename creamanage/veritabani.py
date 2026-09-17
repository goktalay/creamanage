"""SQLite kalıcı kayıt: yazıcılar ve olaylar. Sırlar burada tutulmaz."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SEMA = """
CREATE TABLE IF NOT EXISTS yazicilar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ad TEXT NOT NULL,
    ip TEXT NOT NULL UNIQUE,
    port INTEGER NOT NULL DEFAULT 9999,
    model TEXT NOT NULL DEFAULT '',
    hostname TEXT NOT NULL DEFAULT '',
    grup TEXT NOT NULL DEFAULT '',
    notlar TEXT NOT NULL DEFAULT '',
    etkin INTEGER NOT NULL DEFAULT 1,
    eklenme REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS olaylar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman REAL NOT NULL,
    yazici_id INTEGER,
    tur TEXT NOT NULL,
    seviye TEXT NOT NULL DEFAULT 'bilgi',
    mesaj TEXT NOT NULL,
    veri TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS olaylar_zaman ON olaylar(zaman DESC);
CREATE TABLE IF NOT EXISTS ayarlar (
    anahtar TEXT PRIMARY KEY,
    deger TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kullanicilar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_adi TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ad TEXT NOT NULL DEFAULT '',
    rol TEXT NOT NULL,
    parola_hash TEXT NOT NULL,
    etkin INTEGER NOT NULL DEFAULT 1,
    olusturma REAL NOT NULL,
    son_giris REAL
);
CREATE TABLE IF NOT EXISTS denetim (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman REAL NOT NULL,
    kullanici_id INTEGER,
    kullanici_adi TEXT NOT NULL DEFAULT '',
    eylem TEXT NOT NULL,
    hedef TEXT NOT NULL DEFAULT '',
    ayrinti TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS denetim_kullanici ON denetim(kullanici_id, id DESC);
CREATE TABLE IF NOT EXISTS oturumlar (
    token TEXT PRIMARY KEY,
    kullanici_id INTEGER NOT NULL,
    olusturma REAL NOT NULL,
    son_kullanim REAL NOT NULL,
    ip TEXT NOT NULL DEFAULT ''
);
"""


class Veritabani:
    def __init__(self, yol: str | Path) -> None:
        self.yol = str(yol)
        self._kilit = threading.Lock()
        self._bag = sqlite3.connect(self.yol, check_same_thread=False)
        self._bag.row_factory = sqlite3.Row
        with self._kilit:
            self._bag.executescript(SEMA)
            self._bag.commit()
            self._goc()

    def _goc(self) -> None:
        """Eski veritabanlarına yeni sütunları ekler (kilit alınmış halde çağrılır)."""
        mevcut = {s[1] for s in self._bag.execute("PRAGMA table_info(yazicilar)").fetchall()}
        for sutun, tanim in (("http_port", "INTEGER NOT NULL DEFAULT 80"),
                             ("gcode_dizini", "TEXT NOT NULL DEFAULT ''")):
            if sutun not in mevcut:
                self._bag.execute(f"ALTER TABLE yazicilar ADD COLUMN {sutun} {tanim}")
        mevcut_k = {s[1] for s in self._bag.execute("PRAGMA table_info(kullanicilar)").fetchall()}
        if "tercihler" not in mevcut_k:
            self._bag.execute("ALTER TABLE kullanicilar ADD COLUMN tercihler TEXT NOT NULL DEFAULT '{}'")
        self._bag.commit()

    def kapat(self) -> None:
        with self._kilit:
            self._bag.close()

    # --- yazıcılar ---
    def yazicilar(self) -> list[dict]:
        with self._kilit:
            satirlar = self._bag.execute("SELECT * FROM yazicilar ORDER BY ad, id").fetchall()
        return [dict(s) for s in satirlar]

    def yazici(self, yazici_id: int) -> dict | None:
        with self._kilit:
            s = self._bag.execute("SELECT * FROM yazicilar WHERE id=?", (yazici_id,)).fetchone()
        return dict(s) if s else None

    def yazici_ekle(self, ad: str, ip: str, port: int = 9999, model: str = "",
                    hostname: str = "", grup: str = "", notlar: str = "", http_port: int = 80) -> dict:
        with self._kilit:
            cur = self._bag.execute(
                "INSERT INTO yazicilar(ad, ip, port, model, hostname, grup, notlar, eklenme, http_port)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (ad.strip(), ip.strip(), int(port), model, hostname, grup, notlar, time.time(), int(http_port)))
            self._bag.commit()
            yeni_id = cur.lastrowid
        kayit = self.yazici(int(yeni_id))
        assert kayit is not None
        return kayit

    def yazici_guncelle(self, yazici_id: int, **alanlar) -> dict | None:
        izinli = {"ad", "ip", "port", "model", "hostname", "grup", "notlar", "etkin", "http_port", "gcode_dizini"}
        alanlar = {k: v for k, v in alanlar.items() if k in izinli}
        if alanlar:
            sql = ", ".join(f"{k}=?" for k in alanlar)
            with self._kilit:
                self._bag.execute(f"UPDATE yazicilar SET {sql} WHERE id=?",
                                  (*alanlar.values(), yazici_id))
                self._bag.commit()
        return self.yazici(yazici_id)

    def yazici_sil(self, yazici_id: int) -> bool:
        with self._kilit:
            cur = self._bag.execute("DELETE FROM yazicilar WHERE id=?", (yazici_id,))
            self._bag.commit()
        return cur.rowcount > 0

    # --- ayarlar (JSON değerli anahtar/değer) ---
    def ayar_oku(self, anahtar: str, varsayilan=None):
        with self._kilit:
            s = self._bag.execute("SELECT deger FROM ayarlar WHERE anahtar=?", (anahtar,)).fetchone()
        if not s:
            return varsayilan
        try:
            return json.loads(s["deger"])
        except ValueError:
            return varsayilan

    def ayar_yaz(self, anahtar: str, deger) -> None:
        with self._kilit:
            self._bag.execute("INSERT INTO ayarlar(anahtar, deger) VALUES (?,?)"
                              " ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger",
                              (anahtar, json.dumps(deger, ensure_ascii=False)))
            self._bag.commit()

    # --- olaylar ---
    def olay_ekle(self, tur: str, mesaj: str, yazici_id: int | None = None,
                  seviye: str = "bilgi", veri: dict | None = None) -> dict:
        zaman = time.time()
        with self._kilit:
            cur = self._bag.execute(
                "INSERT INTO olaylar(zaman, yazici_id, tur, seviye, mesaj, veri) VALUES (?,?,?,?,?,?)",
                (zaman, yazici_id, tur, seviye, mesaj, json.dumps(veri or {}, ensure_ascii=False)))
            self._bag.commit()
            olay_id = cur.lastrowid
        return {"id": olay_id, "zaman": zaman, "yazici_id": yazici_id, "tur": tur,
                "seviye": seviye, "mesaj": mesaj, "veri": veri or {}}

    def olaylar(self, limit: int = 100, yazici_id: int | None = None) -> list[dict]:
        with self._kilit:
            if yazici_id is None:
                satirlar = self._bag.execute(
                    "SELECT * FROM olaylar ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            else:
                satirlar = self._bag.execute(
                    "SELECT * FROM olaylar WHERE yazici_id=? ORDER BY id DESC LIMIT ?",
                    (yazici_id, limit)).fetchall()
        sonuc = []
        for s in satirlar:
            d = dict(s)
            try:
                d["veri"] = json.loads(d.get("veri") or "{}")
            except ValueError:
                d["veri"] = {}
            sonuc.append(d)
        return sonuc

    # --- kullanıcılar ---
    def kullanicilar(self) -> list[dict]:
        with self._kilit:
            satirlar = self._bag.execute("SELECT * FROM kullanicilar ORDER BY kullanici_adi").fetchall()
        return [dict(s) for s in satirlar]

    def kullanici(self, kullanici_id: int) -> dict | None:
        with self._kilit:
            s = self._bag.execute("SELECT * FROM kullanicilar WHERE id=?", (kullanici_id,)).fetchone()
        return dict(s) if s else None

    def kullanici_adiyla(self, kullanici_adi: str) -> dict | None:
        with self._kilit:
            s = self._bag.execute("SELECT * FROM kullanicilar WHERE kullanici_adi=? COLLATE NOCASE",
                                  (kullanici_adi.strip(),)).fetchone()
        return dict(s) if s else None

    def kullanici_ekle(self, kullanici_adi: str, ad: str, rol: str, parola_hash: str) -> dict:
        with self._kilit:
            cur = self._bag.execute(
                "INSERT INTO kullanicilar(kullanici_adi, ad, rol, parola_hash, olusturma) VALUES (?,?,?,?,?)",
                (kullanici_adi.strip(), ad.strip(), rol, parola_hash, time.time()))
            self._bag.commit()
            yeni_id = cur.lastrowid
        k = self.kullanici(int(yeni_id))
        assert k is not None
        return k

    def kullanici_guncelle(self, kullanici_id: int, **alanlar) -> dict | None:
        izinli = {"ad", "rol", "parola_hash", "etkin", "son_giris", "kullanici_adi", "tercihler"}
        alanlar = {k: v for k, v in alanlar.items() if k in izinli}
        if alanlar:
            sql = ", ".join(f"{k}=?" for k in alanlar)
            with self._kilit:
                self._bag.execute(f"UPDATE kullanicilar SET {sql} WHERE id=?", (*alanlar.values(), kullanici_id))
                self._bag.commit()
        return self.kullanici(kullanici_id)

    def kullanici_sil(self, kullanici_id: int) -> bool:
        with self._kilit:
            cur = self._bag.execute("DELETE FROM kullanicilar WHERE id=?", (kullanici_id,))
            self._bag.execute("DELETE FROM oturumlar WHERE kullanici_id=?", (kullanici_id,))
            self._bag.commit()
        return cur.rowcount > 0

    # --- oturumlar ---
    def oturum_ekle(self, token: str, kullanici_id: int, ip: str) -> None:
        simdi = time.time()
        with self._kilit:
            self._bag.execute("INSERT INTO oturumlar(token, kullanici_id, olusturma, son_kullanim, ip) VALUES (?,?,?,?,?)",
                              (token, kullanici_id, simdi, simdi, ip))
            self._bag.commit()

    def oturum(self, token: str) -> dict | None:
        with self._kilit:
            s = self._bag.execute("SELECT * FROM oturumlar WHERE token=?", (token,)).fetchone()
        return dict(s) if s else None

    def oturum_dokun(self, token: str) -> None:
        with self._kilit:
            self._bag.execute("UPDATE oturumlar SET son_kullanim=? WHERE token=?", (time.time(), token))
            self._bag.commit()

    def oturum_sil(self, token: str) -> None:
        with self._kilit:
            self._bag.execute("DELETE FROM oturumlar WHERE token=?", (token,))
            self._bag.commit()

    def oturumlari_sil(self, kullanici_id: int, haric_token: str | None = None) -> None:
        with self._kilit:
            if haric_token:
                self._bag.execute("DELETE FROM oturumlar WHERE kullanici_id=? AND token<>?", (kullanici_id, haric_token))
            else:
                self._bag.execute("DELETE FROM oturumlar WHERE kullanici_id=?", (kullanici_id,))
            self._bag.commit()

    def eski_oturumlari_temizle(self, esik_zaman: float) -> None:
        with self._kilit:
            self._bag.execute("DELETE FROM oturumlar WHERE son_kullanim < ?", (esik_zaman,))
            self._bag.commit()

    # --- denetim (kullanıcı işlem geçmişi) ---
    def denetim_ekle(self, kullanici_id: int | None, kullanici_adi: str, eylem: str,
                     hedef: str = "", ayrinti: str = "", ip: str = "") -> None:
        with self._kilit:
            self._bag.execute(
                "INSERT INTO denetim(zaman, kullanici_id, kullanici_adi, eylem, hedef, ayrinti, ip) VALUES (?,?,?,?,?,?,?)",
                (time.time(), kullanici_id, kullanici_adi, eylem, hedef, ayrinti[:500], ip))
            self._bag.commit()

    def denetim_listesi(self, kullanici_id: int | None = None, limit: int = 200,
                        kullanici_adi: str | None = None) -> list[dict]:
        with self._kilit:
            if kullanici_id is not None:
                satirlar = self._bag.execute(
                    "SELECT * FROM denetim WHERE kullanici_id=? OR (kullanici_id IS NULL AND kullanici_adi=?)"
                    " ORDER BY id DESC LIMIT ?", (kullanici_id, kullanici_adi or "", limit)).fetchall()
            else:
                satirlar = self._bag.execute("SELECT * FROM denetim ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(s) for s in satirlar]
