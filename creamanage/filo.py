"""Filo yöneticisi: kayıtlı yazıcılar, canlı bağlantılar, tarama işleri, olaylar."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from . import k2_protokol as P
from .k2_baglanti import YaziciBaglantisi
from .olaylar import (O_DIS_MUDAHALE, O_YAZICI_EKLENDI, O_YAZICI_SILINDI, SEVIYE, OlayMerkezi,
                      gecis_olaylari)
from .tarayici import Tarama, yerel_aglar
from .veritabani import Veritabani
from . import yukleme as Y

log = logging.getLogger("creamanage.filo")

YAYIN_ARALIGI_SN = 1.0   # bir yazıcı için arayüze en sık yayın aralığı
KOMUT_PENCERESI_SN = 120.0   # sistemden verilen komut bu süre içinde etkisini göstermeli

Yayinci = Callable[[dict], Awaitable[None] | None]


class Filo:
    def __init__(self, vt: Veritabani, telemetri=None, kutuphane=None) -> None:
        self.vt = vt
        self.telemetri = telemetri      # TelemetriKayit (isteğe bağlı)
        self.kutuphane = kutuphane      # DosyaKutuphanesi (isteğe bağlı)
        self.olaylar = OlayMerkezi()
        self.baglantilar: dict[int, YaziciBaglantisi] = {}
        self.kayitlar: dict[int, dict] = {}
        self._son_ozet: dict[int, dict] = {}
        self._son_yayin: dict[int, float] = {}
        self._bekleyen_yayin: dict[int, asyncio.TimerHandle] = {}
        self._yayincilar: list[Yayinci] = []
        self.tarama: Tarama | None = None
        self._tarama_gorevi: asyncio.Task | None = None
        self.son_komut: dict[int, tuple[str, float, str]] = {}   # yid → (komut, zaman, kullanıcı)

    # --- yaşam döngüsü ---
    async def baslat(self) -> None:
        for k in self.vt.yazicilar():
            self.kayitlar[k["id"]] = k
            if k.get("etkin", 1):
                self._baglanti_kur(k)
        log.info("%d yazıcı yüklendi", len(self.kayitlar))
        if self.telemetri:
            self.telemetri.baslat(self)

    async def durdur(self) -> None:
        if self.telemetri:
            await self.telemetri.durdur()
        for th in self._bekleyen_yayin.values():
            th.cancel()
        self._bekleyen_yayin.clear()
        if self.tarama:
            self.tarama.iptal()
        if self._tarama_gorevi:
            self._tarama_gorevi.cancel()
        await asyncio.gather(*(b.durdur() for b in self.baglantilar.values()),
                             return_exceptions=True)
        self.baglantilar.clear()

    def yayinci_ekle(self, geri: Yayinci) -> None:
        self._yayincilar.append(geri)

    def yayinci_cikar(self, geri: Yayinci) -> None:
        if geri in self._yayincilar:
            self._yayincilar.remove(geri)

    async def _yayinla(self, mesaj: dict) -> None:
        for y in list(self._yayincilar):
            try:
                r = y(mesaj)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:  # noqa: BLE001
                log.exception("yayıncı hata verdi")

    # --- bağlantı yönetimi ---
    def _baglanti_kur(self, kayit: dict) -> None:
        b = YaziciBaglantisi(kayit["id"], kayit["ip"], int(kayit.get("port") or P.WS_PORT),
                             on_guncelleme=self._guncelleme, on_baglanti=self._guncelleme)
        self.baglantilar[kayit["id"]] = b
        b.baslat()

    async def _guncelleme(self, b: YaziciBaglantisi) -> None:
        yid = b.yazici_id
        kayit = self.kayitlar.get(yid)
        if kayit is None:
            return
        yeni = b.ozet()
        eski = self._son_ozet.get(yid)
        # Model/hostname ilk kez öğrenildiyse kalıcı kayda yaz
        guncelle = {}
        if yeni.get("model") and yeni["model"] != kayit.get("model"):
            guncelle["model"] = yeni["model"]
        if yeni.get("hostname") and yeni["hostname"] != kayit.get("hostname"):
            guncelle["hostname"] = yeni["hostname"]
            if kayit.get("ad") in ("", kayit.get("ip")):
                guncelle["ad"] = yeni["hostname"]     # elle IP ile eklenene hostname'i ad yap
        dizin = P.dosya_dizini(yeni.get("dosya_yolu", ""))
        if dizin and dizin != kayit.get("gcode_dizini"):
            guncelle["gcode_dizini"] = dizin       # yükleme hedefi telemetriden öğrenilir
        if guncelle:
            k = self.vt.yazici_guncelle(yid, **guncelle)
            if k:
                self.kayitlar[yid] = k
        for tur, mesaj, veri in gecis_olaylari(kayit["ad"], eski, yeni):
            await self._olay(tur, mesaj, yid, veri)
        self._baski_izle(yid, kayit, eski, yeni)
        mudahale = self._dis_mudahale(yid, eski, yeni)
        if mudahale:
            await self._olay(O_DIS_MUDAHALE, f"{kayit['ad']}: {mudahale}", yid,
                             {"dosya": (eski or {}).get("dosya") or yeni.get("dosya") or "", "ilerleme": (eski or {}).get("ilerleme")})
        self._son_ozet[yid] = yeni
        self._yayin_planla(yid)

    # --- baskı kayıtları (başlatma / bitirme sistemi) ---
    def _baski_izle(self, yid: int, kayit: dict, eski: dict | None, yeni: dict) -> None:
        """Durum geçişlerinden baskı kayıtlarını üretir: başlama, bitiş, sonuç, hata, süre."""
        if not yeni.get("veri_var") or yeni.get("baglanti") != "bagli":
            return
        d, e_d = yeni.get("durum"), (eski or {}).get("durum")
        acik = self.vt.acik_baski(yid)
        dosya = yeni.get("dosya") or ""
        if d in (P.D_BASIYOR, P.D_DURAKLATILDI):
            if acik and acik["dosya_adi"] != dosya and dosya:
                self.vt.baski_guncelle(acik["id"], bitis=time.time(), sonuc="bilinmiyor")
                acik = None
            if acik is None and d == P.D_BASIYOR:
                yukleme = self.vt.son_yukleme(yid, dosya, time.time() - 7 * 86400) if dosya else None
                dosya_id = yukleme["dosya_id"] if yukleme else None
                if dosya_id is None and dosya:
                    ayni = [x for x in self.vt.dosyalar() if x["ad"] == dosya]
                    dosya_id = ayni[0]["id"] if ayni else None
                gecen = yeni.get("gecen_sn") or 0
                self.vt.baski_ekle(yid, kayit["ad"], dosya, yukleme["id"] if yukleme else None, dosya_id,
                                   baslama=time.time() - (gecen if 0 < gecen < 30 * 86400 else 0))
                acik = self.vt.acik_baski(yid)
            if acik and yeni.get("hata_kodu") and not acik.get("hata_kodu"):
                self.vt.baski_guncelle(acik["id"], hata_kodu=int(yeni["hata_kodu"]), hata_metni=str(yeni.get("hata_anahtari") or ""))
            return
        if acik is None:
            return
        if d == P.D_HATA:
            self.vt.baski_guncelle(acik["id"], hata_kodu=int(yeni.get("hata_kodu") or 0), hata_metni=str(yeni.get("hata_anahtari") or ""))
            return
        if d in (P.D_TAMAMLANDI, P.D_BOSTA) or (d == P.D_HAZIRLANIYOR and e_d in (P.D_BOSTA, P.D_TAMAMLANDI)):
            ilerleme = (eski or {}).get("ilerleme") if (eski or {}).get("ilerleme") is not None else yeni.get("ilerleme")
            if d == P.D_TAMAMLANDI or (ilerleme is not None and ilerleme >= 100):
                sonuc = "tamamlandi"
            elif acik.get("hata_kodu") or (eski or {}).get("hata_kodu"):
                sonuc = "hata"
            elif e_d in (P.D_BASIYOR, P.D_DURAKLATILDI, P.D_HATA):
                sonuc = "iptal"
            else:
                sonuc = "bilinmiyor"      # sunucu kapalıyken bitmiş
            gecen = (eski or {}).get("gecen_sn") or yeni.get("gecen_sn")
            toplam = int(gecen) if gecen else int(time.time() - acik["baslama"])
            self.vt.baski_guncelle(acik["id"], bitis=time.time(), sonuc=sonuc, toplam_sn=toplam, ilerleme=ilerleme)

    def _sistem_komutu_var_mi(self, yid: int, *komutlar: str) -> bool:
        k = self.son_komut.get(yid)
        return bool(k and k[0] in komutlar and time.time() - k[1] <= KOMUT_PENCERESI_SN)

    def _dis_mudahale(self, yid: int, eski: dict | None, yeni: dict) -> str:
        """Baskı sistemden komut verilmeden durdu/iptal edildiyse (yazıcı ekranından) metin döner."""
        if not eski or not eski.get("veri_var") or eski.get("baglanti") != "bagli" or yeni.get("baglanti") != "bagli":
            return ""
        e, y = eski.get("durum"), yeni.get("durum")
        if e == y:
            return ""
        if e == P.D_BASIYOR and y == P.D_DURAKLATILDI and not self._sistem_komutu_var_mi(yid, "duraklat"):
            return f"baskı YAZICIDAN durduruldu (sistem dışı müdahale) — {eski.get('dosya') or ''} %{int(eski.get('ilerleme') or 0)}"
        ilerleme = eski.get("ilerleme")
        iptal_gibi = y in (P.D_BOSTA,) or (y == P.D_TAMAMLANDI and ilerleme is not None and ilerleme < 100)
        if e in (P.D_BASIYOR, P.D_DURAKLATILDI) and iptal_gibi and not self._sistem_komutu_var_mi(yid, "durdur", "baski_baslat"):
            return f"baskı YAZICIDAN iptal edildi (sistem dışı müdahale) — {eski.get('dosya') or ''} %{int(ilerleme or 0)}"
        return ""

    def _yayin_planla(self, yid: int) -> None:
        """Yazıcı başına en fazla saniyede bir arayüz yayını (56 yazıcı için hafif)."""
        if yid in self._bekleyen_yayin:
            return
        loop = asyncio.get_running_loop()
        gecen = time.monotonic() - self._son_yayin.get(yid, 0.0)
        gecikme = max(0.0, YAYIN_ARALIGI_SN - gecen)

        def tetikle() -> None:
            self._bekleyen_yayin.pop(yid, None)
            self._son_yayin[yid] = time.monotonic()
            if yid in self.kayitlar:
                asyncio.ensure_future(self._yayinla({"tur": "yazici", "yazici": self.yazici_gorunum(yid)}))

        self._bekleyen_yayin[yid] = loop.call_later(gecikme, tetikle)

    async def _olay(self, tur: str, mesaj: str, yid: int | None = None, veri: dict | None = None) -> None:
        olay = self.vt.olay_ekle(tur, mesaj, yid, SEVIYE.get(tur, "bilgi"), veri)
        log.info("olay %s: %s", tur, mesaj)
        await self.olaylar.yayinla(olay)
        await self._yayinla({"tur": "olay", "olay": olay})

    # --- görünümler ---
    def yazici_gorunum(self, yid: int) -> dict:
        kayit = dict(self.kayitlar[yid])
        b = self.baglantilar.get(yid)
        kayit["canli"] = b.ozet() if b else {"durum": P.D_CEVRIMDISI, "baglanti": "kopuk"}
        return kayit

    def yazicilar_gorunum(self) -> list[dict]:
        return [self.yazici_gorunum(yid) for yid in sorted(self.kayitlar, key=lambda i: (self.kayitlar[i]["ad"].lower(), i))]

    def ozet_sayilar(self) -> dict:
        sayilar = {d: 0 for d in P.DURUMLAR}
        for yid in self.kayitlar:
            b = self.baglantilar.get(yid)
            d = b.ozet()["durum"] if b else P.D_CEVRIMDISI
            sayilar[d] = sayilar.get(d, 0) + 1
        sayilar["toplam"] = len(self.kayitlar)
        return sayilar

    def ham(self, yid: int) -> dict:
        b = self.baglantilar.get(yid)
        return dict(b.ham) if b else {}

    # --- yazıcı CRUD ---
    async def yazici_ekle(self, ad: str, ip: str, port: int = P.WS_PORT, **ek) -> dict:
        if not ad.strip():
            ad = ek.get("hostname") or ip
        kayit = self.vt.yazici_ekle(ad, ip, port, model=ek.get("model", ""),
                                    hostname=ek.get("hostname", ""), grup=ek.get("grup", ""),
                                    notlar=ek.get("notlar", ""), http_port=int(ek.get("http_port") or Y.HTTP_PORT_VARSAYILAN))
        self.kayitlar[kayit["id"]] = kayit
        self._baglanti_kur(kayit)
        await self._olay(O_YAZICI_EKLENDI, f"{kayit['ad']} ({ip}) eklendi", kayit["id"])
        return self.yazici_gorunum(kayit["id"])

    async def yazici_guncelle(self, yid: int, **alanlar) -> dict | None:
        eski = self.kayitlar.get(yid)
        if eski is None:
            return None
        kayit = self.vt.yazici_guncelle(yid, **alanlar)
        if kayit is None:
            return None
        self.kayitlar[yid] = kayit
        baglanti_degisti = (kayit["ip"] != eski["ip"] or kayit["port"] != eski["port"]
                            or kayit["etkin"] != eski["etkin"])
        if baglanti_degisti:
            b = self.baglantilar.pop(yid, None)
            if b:
                await b.durdur()
            self._son_ozet.pop(yid, None)
            if kayit["etkin"]:
                self._baglanti_kur(kayit)
        gorunum = self.yazici_gorunum(yid)
        await self._yayinla({"tur": "yazici", "yazici": gorunum})
        return gorunum

    async def yazici_sil(self, yid: int) -> bool:
        kayit = self.kayitlar.pop(yid, None)
        if kayit is None:
            return False
        b = self.baglantilar.pop(yid, None)
        if b:
            await b.durdur()
        self._son_ozet.pop(yid, None)
        th = self._bekleyen_yayin.pop(yid, None)
        if th:
            th.cancel()
        self.vt.yazici_sil(yid)
        if self.telemetri:
            self.telemetri.kapat(yid)
        await self._olay(O_YAZICI_SILINDI, f"{kayit['ad']} ({kayit['ip']}) silindi", None)
        await self._yayinla({"tur": "yazici_silindi", "id": yid})
        return True

    async def komut(self, yid: int, ad: str, deger=None, kullanici: str = "") -> bool:
        b = self.baglantilar.get(yid)
        if b is None:
            return False
        self.son_komut[yid] = (ad, time.time(), kullanici)
        sonuc = await b.komut(ad, deger)
        kayit = self.kayitlar.get(yid, {})
        await self._olay("komut", f"{kayit.get('ad', yid)}: {ad} komutu gönderildi"
                         + ("" if sonuc else " (başarısız: bağlı değil)"), yid, {"komut": ad, "deger": deger})
        return sonuc

    # --- dosya kütüphanesi → yazıcı ---
    async def dosya_gonder(self, dosya_id: int, yid: int, baslat: bool = True, kullanici: dict | None = None) -> dict:
        """Kütüphanedeki dosyayı yazıcıya yükler, yükleme kaydı açar, istenirse baskıyı başlatır."""
        kayit = self.kayitlar.get(yid)
        if kayit is None:
            raise LookupError("yazıcı bulunamadı")
        d = self.vt.dosya(dosya_id)
        if d is None or not d.get("yol"):
            raise LookupError("dosya bulunamadı")
        if d.get("durum") != "aktif":
            raise ValueError("pasif dosya yazıcıya gönderilemez")
        k_id, k_ad = (kullanici or {}).get("id"), (kullanici or {}).get("kullanici_adi", "")
        try:
            sonuc = await self.dosya_yukle_ve_baslat(yid, d["ad"], d["yol"], baslat, k_ad, kaydet=False)
        except Exception as e:  # noqa: BLE001
            self.vt.yukleme_ekle(dosya_id, yid, kayit["ad"], k_id, k_ad, False, False, str(e)[:300], "")
            raise
        y = self.vt.yukleme_ekle(dosya_id, yid, kayit["ad"], k_id, k_ad, True, sonuc["baslatildi"], "", sonuc["dosya_adi"])
        sonuc["yukleme_id"] = y["id"]; sonuc["dosya_id"] = dosya_id
        return sonuc

    async def dosya_yukle_ve_baslat(self, yid: int, dosya_adi: str, yerel_yol, baslat: bool = True,
                                    kullanici: str = "", kaydet: bool = True) -> dict:
        kayit = self.kayitlar.get(yid)
        if kayit is None:
            raise LookupError("yazıcı bulunamadı")
        sonuc = await Y.dosya_yukle(kayit["ip"], dosya_adi, yerel_yol, int(kayit.get("http_port") or Y.HTTP_PORT_VARSAYILAN))
        if sonuc["port"] != int(kayit.get("http_port") or 0):
            k = self.vt.yazici_guncelle(yid, http_port=sonuc["port"])
            if k:
                self.kayitlar[yid] = k
        yol = Y.hedef_yol(kayit.get("gcode_dizini") or Y.GCODE_DIZINI_VARSAYILAN, sonuc["dosya_adi"])
        await self._olay("dosya_yuklendi", f"{kayit['ad']}: dosya yüklendi {sonuc['dosya_adi']}" + (f" ({kullanici})" if kullanici else ""),
                         yid, {"dosya": sonuc["dosya_adi"], "yol": yol})
        baslatildi = False
        if baslat:
            b = self.baglantilar.get(yid)
            self.son_komut[yid] = ("baski_baslat", time.time(), kullanici)
            baslatildi = bool(b and await b.komut("baski_baslat", yol))
            await self._olay("baski_baslatildi" if baslatildi else "komut",
                             f"{kayit['ad']}: baskı başlatma komutu {'gönderildi' if baslatildi else 'GÖNDERİLEMEDİ (bağlı değil)'} {sonuc['dosya_adi']}",
                             yid, {"dosya": sonuc["dosya_adi"], "yol": yol})
        return {"dosya_adi": sonuc["dosya_adi"], "yol": yol, "port": sonuc["port"], "baslatildi": baslatildi}

    # --- tarama ---
    def aglar(self) -> list[dict]:
        return yerel_aglar()

    def kayitli_ipler(self) -> set[str]:
        return {k["ip"] for k in self.kayitlar.values()}

    def tarama_baslat(self, cidr: str, port: int = P.WS_PORT) -> Tarama:
        if self.tarama and self.tarama.asama in ("hazir", "port", "kimlik"):
            raise RuntimeError("zaten süren bir tarama var")
        self.tarama = Tarama(cidr, port, on_ilerleme=self._tarama_ilerleme)
        self._tarama_gorevi = asyncio.create_task(self.tarama.calistir())
        return self.tarama

    def tarama_gorunum(self) -> dict | None:
        if not self.tarama:
            return None
        d = self.tarama.sozluk()
        kayitli = self.kayitli_ipler()
        d["bulunan"] = [dict(b, kayitli=b["ip"] in kayitli) for b in d["bulunan"]]
        return d

    async def _tarama_ilerleme(self, t: Tarama) -> None:
        await self._yayinla({"tur": "tarama", "tarama": self.tarama_gorunum()})
