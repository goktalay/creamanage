"""Kullanıcılar, roller, parola hash'leme ve oturumlar.

Roller (yetki sırası artan):
  gozetmen            yalnız izler (yazıcılar, durumlar, olaylar)
  yazici_yoneticisi   kullanıcı yönetimi dışında her şey (yazıcı ekleme/silme, komut,
                      tarama, dosya yükleme, bildirim ayarları)
  sistem_yoneticisi   her şey, kullanıcı yönetimi dahil

Parolalar PBKDF2-HMAC-SHA256 (200 000 tur, 16 baytlık rastgele tuz) ile saklanır;
düz parola hiçbir yere yazılmaz. Oturumlar sunucu tarafında (SQLite) tutulur; tarayıcıya
yalnız rastgele bir belirteç (HttpOnly çerez) verilir.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time

ROLLER = {"gozetmen": 1, "yazici_yoneticisi": 2, "sistem_yoneticisi": 3}
ROL_ADLARI = {"gozetmen": "Gözetmen", "yazici_yoneticisi": "Yazıcı Yöneticisi",
              "sistem_yoneticisi": "Sistem Yöneticisi"}
CEREZ_ADI = "creamanage_oturum"
OTURUM_BOSTA_SN = 12 * 3600          # 12 saat kullanılmayan oturum düşer
OTURUM_EN_FAZLA_SN = 30 * 24 * 3600  # 30 gün sonra her koşulda yeniden giriş
PAROLA_EN_AZ = 8
KULLANICI_ADI_KALIBI = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
KILIT_DENEME = 5                     # 5 başarısız giriş → kilit
KILIT_SN = 60
PBKDF2_TUR = 200_000


def parola_hashle(parola: str) -> str:
    tuz = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", parola.encode("utf-8"), tuz, PBKDF2_TUR)
    return f"pbkdf2_sha256${PBKDF2_TUR}${tuz.hex()}${h.hex()}"


def parola_dogrula(parola: str, kayit: str) -> bool:
    try:
        _, tur, tuz_hex, h_hex = kayit.split("$")
        h = hashlib.pbkdf2_hmac("sha256", parola.encode("utf-8"), bytes.fromhex(tuz_hex), int(tur))
        return hmac.compare_digest(h.hex(), h_hex)
    except (ValueError, AttributeError):
        return False


def parola_denetle(parola: str) -> str:
    """Uygunsa boş, değilse hata metni döndürür."""
    if not isinstance(parola, str) or len(parola) < PAROLA_EN_AZ:
        return f"parola en az {PAROLA_EN_AZ} karakter olmalı"
    if len(parola) > 128:
        return "parola çok uzun"
    return ""


def yetkili_mi(rol: str, gerekli: str) -> bool:
    return ROLLER.get(rol, 0) >= ROLLER.get(gerekli, 99)


def gorunum(k: dict) -> dict:
    """Parola hash'i olmadan arayüze verilecek sözlük."""
    return {"id": k["id"], "kullanici_adi": k["kullanici_adi"], "ad": k["ad"], "rol": k["rol"],
            "rol_adi": ROL_ADLARI.get(k["rol"], k["rol"]), "etkin": bool(k.get("etkin", 1)),
            "olusturma": k.get("olusturma"), "son_giris": k.get("son_giris")}


class KullaniciYonetimi:
    def __init__(self, vt) -> None:
        self.vt = vt
        self._basarisiz: dict[str, tuple[int, float]] = {}   # anahtar → (sayı, kilit bitişi)

    # --- kurulum ---
    def kullanici_var_mi(self) -> bool:
        return bool(self.vt.kullanicilar())

    # --- CRUD ---
    def listele(self) -> list[dict]:
        return [gorunum(k) for k in self.vt.kullanicilar()]

    def ekle(self, kullanici_adi: str, ad: str, rol: str, parola: str) -> dict:
        kullanici_adi = (kullanici_adi or "").strip()
        if not KULLANICI_ADI_KALIBI.match(kullanici_adi):
            raise ValueError("kullanıcı adı 3-32 karakter; harf, rakam, nokta, alt çizgi, tire")
        if rol not in ROLLER:
            raise ValueError("geçersiz rol")
        hata = parola_denetle(parola)
        if hata:
            raise ValueError(hata)
        if self.vt.kullanici_adiyla(kullanici_adi):
            raise ValueError("bu kullanıcı adı zaten var")
        return gorunum(self.vt.kullanici_ekle(kullanici_adi, ad or kullanici_adi, rol, parola_hashle(parola)))

    def guncelle(self, kullanici_id: int, *, ad: str | None = None, rol: str | None = None,
                 etkin: bool | None = None, parola: str | None = None) -> dict:
        k = self.vt.kullanici(kullanici_id)
        if k is None:
            raise LookupError("kullanıcı bulunamadı")
        alanlar: dict = {}
        if ad is not None:
            alanlar["ad"] = str(ad).strip() or k["kullanici_adi"]
        if rol is not None:
            if rol not in ROLLER:
                raise ValueError("geçersiz rol")
            alanlar["rol"] = rol
        if etkin is not None:
            alanlar["etkin"] = 1 if etkin else 0
        if parola:
            hata = parola_denetle(parola)
            if hata:
                raise ValueError(hata)
            alanlar["parola_hash"] = parola_hashle(parola)
        # Son sistem yöneticisi yetkisiz ya da pasif bırakılamaz
        if k["rol"] == "sistem_yoneticisi" and (alanlar.get("rol", k["rol"]) != "sistem_yoneticisi"
                                               or alanlar.get("etkin", k["etkin"]) == 0):
            if self._etkin_yonetici_sayisi() <= 1:
                raise ValueError("son sistem yöneticisi yetkisiz ya da pasif bırakılamaz")
        yeni = self.vt.kullanici_guncelle(kullanici_id, **alanlar)
        if parola or alanlar.get("etkin") == 0:
            self.vt.oturumlari_sil(kullanici_id)     # parola/etkinlik değişince oturumlar düşer
        assert yeni is not None
        return gorunum(yeni)

    def sil(self, kullanici_id: int) -> None:
        k = self.vt.kullanici(kullanici_id)
        if k is None:
            raise LookupError("kullanıcı bulunamadı")
        if k["rol"] == "sistem_yoneticisi" and k["etkin"] and self._etkin_yonetici_sayisi() <= 1:
            raise ValueError("son sistem yöneticisi silinemez")
        self.vt.kullanici_sil(kullanici_id)

    def parola_degistir(self, kullanici_id: int, eski: str, yeni: str, haric_token: str | None = None) -> None:
        k = self.vt.kullanici(kullanici_id)
        if k is None or not parola_dogrula(eski, k["parola_hash"]):
            raise ValueError("mevcut parola yanlış")
        hata = parola_denetle(yeni)
        if hata:
            raise ValueError(hata)
        self.vt.kullanici_guncelle(kullanici_id, parola_hash=parola_hashle(yeni))
        self.vt.oturumlari_sil(kullanici_id, haric_token)

    def _etkin_yonetici_sayisi(self) -> int:
        return sum(1 for k in self.vt.kullanicilar() if k["rol"] == "sistem_yoneticisi" and k["etkin"])

    # --- giriş ---
    def _kilit_anahtari(self, kullanici_adi: str, ip: str) -> str:
        return f"{kullanici_adi.strip().lower()}@{ip}"

    def kilitli_sn(self, kullanici_adi: str, ip: str) -> int:
        sayi, bitis = self._basarisiz.get(self._kilit_anahtari(kullanici_adi, ip), (0, 0.0))
        return int(bitis - time.time()) if sayi >= KILIT_DENEME and bitis > time.time() else 0

    def giris(self, kullanici_adi: str, parola: str, ip: str = "") -> dict:
        """Başarılıysa kullanıcı görünümü + token döndürür; değilse ValueError."""
        kalan = self.kilitli_sn(kullanici_adi, ip)
        if kalan > 0:
            raise ValueError(f"çok fazla başarısız deneme; {kalan} sn bekleyin")
        k = self.vt.kullanici_adiyla(kullanici_adi or "")
        anahtar = self._kilit_anahtari(kullanici_adi or "", ip)
        if k is None or not k["etkin"] or not parola_dogrula(parola or "", k["parola_hash"]):
            sayi, _ = self._basarisiz.get(anahtar, (0, 0.0))
            sayi += 1
            self._basarisiz[anahtar] = (sayi, time.time() + KILIT_SN if sayi >= KILIT_DENEME else 0.0)
            raise ValueError("kullanıcı adı ya da parola hatalı")
        self._basarisiz.pop(anahtar, None)
        token = secrets.token_urlsafe(32)
        self.vt.oturum_ekle(token, k["id"], ip)
        self.vt.kullanici_guncelle(k["id"], son_giris=time.time())
        self.vt.eski_oturumlari_temizle(time.time() - OTURUM_EN_FAZLA_SN)
        return {"kullanici": gorunum(k), "token": token}

    def oturum_kullanicisi(self, token: str | None) -> dict | None:
        if not token:
            return None
        o = self.vt.oturum(token)
        if o is None:
            return None
        simdi = time.time()
        if simdi - o["son_kullanim"] > OTURUM_BOSTA_SN or simdi - o["olusturma"] > OTURUM_EN_FAZLA_SN:
            self.vt.oturum_sil(token)
            return None
        k = self.vt.kullanici(o["kullanici_id"])
        if k is None or not k["etkin"]:
            self.vt.oturum_sil(token)
            return None
        if simdi - o["son_kullanim"] > 60:           # yazma yükünü azalt: dakikada bir dokun
            self.vt.oturum_dokun(token)
        return k

    def cikis(self, token: str | None) -> None:
        if token:
            self.vt.oturum_sil(token)
