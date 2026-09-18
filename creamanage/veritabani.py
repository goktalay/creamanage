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
CREATE TABLE IF NOT EXISTS dosyalar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ad TEXT NOT NULL,
    aciklama TEXT NOT NULL DEFAULT '',
    boyut INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    yol TEXT NOT NULL,
    resim_yol TEXT NOT NULL DEFAULT '',
    durum TEXT NOT NULL DEFAULT 'aktif',
    yukleyen_id INTEGER,
    yukleyen_adi TEXT NOT NULL DEFAULT '',
    zaman REAL NOT NULL,
    tahmini_sn INTEGER,
    filament_mm REAL
);
CREATE INDEX IF NOT EXISTS dosyalar_sha ON dosyalar(sha256);
CREATE TABLE IF NOT EXISTS dosya_yuklemeleri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dosya_id INTEGER NOT NULL,
    yazici_id INTEGER,
    yazici_adi TEXT NOT NULL DEFAULT '',
    kullanici_id INTEGER,
    kullanici_adi TEXT NOT NULL DEFAULT '',
    zaman REAL NOT NULL,
    basarili INTEGER NOT NULL DEFAULT 1,
    baslatildi INTEGER NOT NULL DEFAULT 0,
    hata TEXT NOT NULL DEFAULT '',
    yazici_dosya_adi TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS yuklemeler_dosya ON dosya_yuklemeleri(dosya_id, id DESC);
CREATE TABLE IF NOT EXISTS baskilar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    yukleme_id INTEGER,
    dosya_id INTEGER,
    yazici_id INTEGER NOT NULL,
    yazici_adi TEXT NOT NULL DEFAULT '',
    dosya_adi TEXT NOT NULL DEFAULT '',
    baslama REAL NOT NULL,
    bitis REAL,
    sonuc TEXT NOT NULL DEFAULT 'suruyor',
    hata_kodu INTEGER NOT NULL DEFAULT 0,
    hata_metni TEXT NOT NULL DEFAULT '',
    toplam_sn INTEGER,
    ilerleme REAL
);
CREATE INDEX IF NOT EXISTS baskilar_dosya ON baskilar(dosya_id, id DESC);
CREATE INDEX IF NOT EXISTS baskilar_yazici ON baskilar(yazici_id, id DESC);
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
                             ("gcode_dizini", "TEXT NOT NULL DEFAULT ''"),
                             ("kamera_url", "TEXT NOT NULL DEFAULT ''")):
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
        izinli = {"ad", "ip", "port", "model", "hostname", "grup", "notlar", "etkin", "http_port", "gcode_dizini", "kamera_url"}
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

    # --- dosya kütüphanesi ---
    def _satirlar(self, sql: str, p=()) -> list[dict]:
        with self._kilit:
            return [dict(s) for s in self._bag.execute(sql, p).fetchall()]

    def _yaz(self, sql: str, p=()) -> int:
        with self._kilit:
            cur = self._bag.execute(sql, p)
            self._bag.commit()
            return int(cur.lastrowid or cur.rowcount)

    def dosyalar(self, durum: str | None = None) -> list[dict]:
        if durum:
            return self._satirlar("SELECT * FROM dosyalar WHERE durum=? ORDER BY id DESC", (durum,))
        return self._satirlar("SELECT * FROM dosyalar ORDER BY id DESC")

    def dosya(self, dosya_id: int) -> dict | None:
        r = self._satirlar("SELECT * FROM dosyalar WHERE id=?", (dosya_id,))
        return r[0] if r else None

    def dosya_sha_ile(self, sha256: str) -> dict | None:
        r = self._satirlar("SELECT * FROM dosyalar WHERE sha256=? ORDER BY id DESC LIMIT 1", (sha256,))
        return r[0] if r else None

    def dosya_ekle(self, ad: str, yol: str, boyut: int, sha256: str, yukleyen_id, yukleyen_adi: str,
                   aciklama: str = "", resim_yol: str = "", tahmini_sn=None, filament_mm=None) -> dict:
        yeni = self._yaz("INSERT INTO dosyalar(ad, aciklama, boyut, sha256, yol, resim_yol, yukleyen_id, yukleyen_adi, zaman, tahmini_sn, filament_mm)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (ad, aciklama, boyut, sha256, yol, resim_yol, yukleyen_id, yukleyen_adi, time.time(), tahmini_sn, filament_mm))
        d = self.dosya(yeni); assert d is not None
        return d

    def dosya_guncelle(self, dosya_id: int, **alanlar) -> dict | None:
        izinli = {"ad", "aciklama", "durum", "resim_yol"}
        alanlar = {k: v for k, v in alanlar.items() if k in izinli}
        if alanlar:
            self._yaz("UPDATE dosyalar SET " + ", ".join(f"{k}=?" for k in alanlar) + " WHERE id=?", (*alanlar.values(), dosya_id))
        return self.dosya(dosya_id)

    def dosya_sil(self, dosya_id: int) -> bool:
        n = self._yaz("DELETE FROM dosyalar WHERE id=?", (dosya_id,))
        self._yaz("DELETE FROM dosya_yuklemeleri WHERE dosya_id=?", (dosya_id,))
        self._yaz("UPDATE baskilar SET dosya_id=NULL, yukleme_id=NULL WHERE dosya_id=?", (dosya_id,))
        return n > 0

    def yukleme_ekle(self, dosya_id: int, yazici_id, yazici_adi: str, kullanici_id, kullanici_adi: str,
                     basarili: bool, baslatildi: bool, hata: str = "", yazici_dosya_adi: str = "") -> dict:
        yeni = self._yaz("INSERT INTO dosya_yuklemeleri(dosya_id, yazici_id, yazici_adi, kullanici_id, kullanici_adi, zaman, basarili, baslatildi, hata, yazici_dosya_adi)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?)", (dosya_id, yazici_id, yazici_adi, kullanici_id, kullanici_adi, time.time(), int(basarili), int(baslatildi), hata, yazici_dosya_adi))
        return self._satirlar("SELECT * FROM dosya_yuklemeleri WHERE id=?", (yeni,))[0]

    def yuklemeler(self, dosya_id: int | None = None, yazici_id: int | None = None, limit: int = 500) -> list[dict]:
        if dosya_id is not None:
            return self._satirlar("SELECT * FROM dosya_yuklemeleri WHERE dosya_id=? ORDER BY id DESC LIMIT ?", (dosya_id, limit))
        if yazici_id is not None:
            return self._satirlar("SELECT * FROM dosya_yuklemeleri WHERE yazici_id=? ORDER BY id DESC LIMIT ?", (yazici_id, limit))
        return self._satirlar("SELECT * FROM dosya_yuklemeleri ORDER BY id DESC LIMIT ?", (limit,))

    def son_yukleme(self, yazici_id: int, yazici_dosya_adi: str, en_eski: float) -> dict | None:
        r = self._satirlar("SELECT * FROM dosya_yuklemeleri WHERE yazici_id=? AND yazici_dosya_adi=? AND basarili=1 AND zaman>=? ORDER BY id DESC LIMIT 1",
                           (yazici_id, yazici_dosya_adi, en_eski))
        return r[0] if r else None

    def baski_ekle(self, yazici_id: int, yazici_adi: str, dosya_adi: str, yukleme_id=None, dosya_id=None, baslama: float | None = None) -> dict:
        yeni = self._yaz("INSERT INTO baskilar(yukleme_id, dosya_id, yazici_id, yazici_adi, dosya_adi, baslama) VALUES (?,?,?,?,?,?)",
                         (yukleme_id, dosya_id, yazici_id, yazici_adi, dosya_adi, baslama or time.time()))
        return self._satirlar("SELECT * FROM baskilar WHERE id=?", (yeni,))[0]

    def baski_guncelle(self, baski_id: int, **alanlar) -> None:
        izinli = {"bitis", "sonuc", "hata_kodu", "hata_metni", "toplam_sn", "ilerleme", "dosya_id", "yukleme_id"}
        alanlar = {k: v for k, v in alanlar.items() if k in izinli}
        if alanlar:
            self._yaz("UPDATE baskilar SET " + ", ".join(f"{k}=?" for k in alanlar) + " WHERE id=?", (*alanlar.values(), baski_id))

    def acik_baski(self, yazici_id: int) -> dict | None:
        r = self._satirlar("SELECT * FROM baskilar WHERE yazici_id=? AND bitis IS NULL ORDER BY id DESC LIMIT 1", (yazici_id,))
        return r[0] if r else None

    def baskilar(self, dosya_id: int | None = None, yukleme_id: int | None = None, yazici_id: int | None = None, limit: int = 500) -> list[dict]:
        if yukleme_id is not None:
            return self._satirlar("SELECT * FROM baskilar WHERE yukleme_id=? ORDER BY id DESC LIMIT ?", (yukleme_id, limit))
        if dosya_id is not None:
            return self._satirlar("SELECT * FROM baskilar WHERE dosya_id=? ORDER BY id DESC LIMIT ?", (dosya_id, limit))
        if yazici_id is not None:
            return self._satirlar("SELECT * FROM baskilar WHERE yazici_id=? ORDER BY id DESC LIMIT ?", (yazici_id, limit))
        return self._satirlar("SELECT * FROM baskilar ORDER BY id DESC LIMIT ?", (limit,))
