"""aiohttp web uygulaması: statik arayüz, REST API, tarayıcıya WebSocket yayını."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import tempfile
import weakref
from pathlib import Path

from aiohttp import WSMsgType, web

from . import k2_protokol as P
from .filo import Filo
from .kullanicilar import CEREZ_ADI, OTURUM_EN_FAZLA_SN, ROL_ADLARI, KullaniciYonetimi, gorunum as k_gorunum, yetkili_mi
from .telegram import TelegramBildirici
from . import yukleme as Y
from . import hata_kodlari as HK
from . import kamera as KAM
from .olaylar import yonetici_mi_gorur
from .surum import FIRMA, SURUM, URUN_ADI, URUN_KODU

log = logging.getLogger("creamanage.web")
FILO_ANAHTAR = web.AppKey("filo", Filo)
WS_ISTEMCILER = web.AppKey("ws_istemciler", weakref.WeakSet)
WS_ROLLER = web.AppKey("ws_roller", weakref.WeakKeyDictionary)
WEB_DIZIN = Path(__file__).resolve().parent.parent / "web"


def _json(veri, durum: int = 200) -> web.Response:
    return web.json_response(veri, status=durum, dumps=lambda v: json.dumps(v, ensure_ascii=False))


def _hata(mesaj: str, durum: int = 400) -> web.Response:
    return _json({"hata": mesaj}, durum)


async def _govde(istek: web.Request) -> dict:
    try:
        veri = await istek.json()
    except (ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="geçersiz JSON")
    if not isinstance(veri, dict):
        raise web.HTTPBadRequest(text="JSON nesnesi bekleniyor")
    return veri


def _ip_dogrula(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        raise web.HTTPBadRequest(text=f"geçersiz IP: {ip}")


# Kimlik gerektirmeyen yollar
ACIK_YOLLAR = {"/giris", "/api/giris", "/api/kurulum", "/api/surum"}


def gerekli_rol(yontem: str, yol: str) -> str:
    """Her istek için en düşük yeterli rol."""
    if yol.startswith("/api/kullanicilar") or yol.startswith("/api/ayarlar"):
        return "sistem_yoneticisi"
    if yol.startswith("/api/hata_kodlari") and yontem != "GET":
        return "sistem_yoneticisi"
    if yontem != "GET" and (yol in ("/api/yazicilar", "/api/yazicilar/toplu") or yol.startswith("/api/tarama")
                            or (yontem in ("PUT", "DELETE") and yol.startswith("/api/yazicilar/"))):
        return "sistem_yoneticisi"          # yazıcı ekleme/silme/ayar/tarama yalnız sistem yöneticisi
    if yol in ("/api/cikis", "/api/ben", "/api/ben/parola", "/api/ben/tercihler") or yol.endswith("/kamera/kayit"):
        return "gozetmen"
    if yontem in ("POST", "PUT", "DELETE", "PATCH"):
        return "yazici_yoneticisi"
    return "gozetmen"


def uygulama_olustur(filo: Filo, telegram: TelegramBildirici | None = None,
                     kullanicilar: KullaniciYonetimi | None = None) -> web.Application:
    ky = kullanicilar or KullaniciYonetimi(filo.vt)

    @web.middleware
    async def kimlik_katmani(istek: web.Request, handler):
        yol = istek.path
        if yol.startswith("/static/") or yol in ACIK_YOLLAR:
            return await handler(istek)
        k = ky.oturum_kullanicisi(istek.cookies.get(CEREZ_ADI))
        if k is None:
            if yol == "/":
                raise web.HTTPFound("/giris")
            return _hata("giriş gerekli", 401)
        istek["kullanici"] = k
        if not yetkili_mi(k["rol"], gerekli_rol(istek.method, yol)):
            return _hata("bu işlem için yetkiniz yok", 403)
        return await handler(istek)

    app = web.Application(middlewares=[kimlik_katmani], client_max_size=Y.EN_BUYUK_DOSYA)
    app[FILO_ANAHTAR] = filo
    app[WS_ISTEMCILER] = weakref.WeakSet()
    app[WS_ROLLER] = weakref.WeakKeyDictionary()

    async def yayin(mesaj: dict) -> None:
        metin = json.dumps(mesaj, ensure_ascii=False)
        yalniz_yonetici = mesaj.get("tur") == "olay" and not yonetici_mi_gorur(mesaj.get("olay") or {}, "gozetmen")
        for ws in list(app[WS_ISTEMCILER]):
            if yalniz_yonetici and app[WS_ROLLER].get(ws) != "sistem_yoneticisi":
                continue
            try:
                await ws.send_str(metin)
            except Exception:  # noqa: BLE001
                pass

    filo.yayinci_ekle(yayin)

    # --- sayfalar ---
    async def ana_sayfa(_):
        return web.FileResponse(WEB_DIZIN / "index.html")

    async def giris_sayfasi(istek):
        if ky.oturum_kullanicisi(istek.cookies.get(CEREZ_ADI)):
            raise web.HTTPFound("/")
        return web.FileResponse(WEB_DIZIN / "giris.html")

    # --- kimlik ---
    def _ip(istek: web.Request) -> str:
        return istek.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (istek.remote or "")

    def _denetim(istek: web.Request, eylem: str, hedef: str = "", ayrinti: str = "",
                 kullanici: dict | None = None, kullanici_adi: str | None = None) -> None:
        k = kullanici if kullanici is not None else istek.get("kullanici")
        filo.vt.denetim_ekle(k["id"] if k else None, (k["kullanici_adi"] if k else kullanici_adi) or "",
                             eylem, hedef, ayrinti, _ip(istek))

    def _yazici_etiketi(yid: int) -> str:
        k = filo.kayitlar.get(yid) or {}
        return f"{k.get('ad', yid)} ({k.get('ip', '')})"

    def _cerez_yaz(yanit: web.Response, token: str) -> web.Response:
        yanit.set_cookie(CEREZ_ADI, token, httponly=True, samesite="Lax", max_age=OTURUM_EN_FAZLA_SN, path="/")
        return yanit

    async def kurulum_durum(_):
        return _json({"kurulum_gerekli": not ky.kullanici_var_mi(), "roller": ROL_ADLARI})

    async def kurulum_yap(istek):
        """İlk sistem yöneticisi — yalnız hiç kullanıcı yokken çalışır."""
        if ky.kullanici_var_mi():
            return _hata("kurulum zaten yapılmış", 409)
        v = await _govde(istek)
        try:
            k = ky.ekle(str(v.get("kullanici_adi", "")), str(v.get("ad", "")), "sistem_yoneticisi", str(v.get("parola", "")))
        except ValueError as e:
            return _hata(str(e))
        sonuc = ky.giris(k["kullanici_adi"], str(v.get("parola", "")), _ip(istek))
        _denetim(istek, "kurulum", "", "ilk sistem yöneticisi oluşturuldu", kullanici=k)
        await filo._olay("kullanici", f"İlk sistem yöneticisi oluşturuldu: {k['kullanici_adi']}", None, {"kullanici": k["kullanici_adi"]})
        return _cerez_yaz(_json({"kullanici": sonuc["kullanici"]}, 201), sonuc["token"])

    async def giris(istek):
        v = await _govde(istek)
        try:
            sonuc = ky.giris(str(v.get("kullanici_adi", "")), str(v.get("parola", "")), _ip(istek))
        except ValueError as e:
            log.warning("başarısız giriş: %s (%s)", v.get("kullanici_adi"), _ip(istek))
            _denetim(istek, "giris_basarisiz", "", str(e), kullanici_adi=str(v.get("kullanici_adi", ""))[:64])
            return _hata(str(e), 401)
        log.info("giriş: %s (%s)", sonuc["kullanici"]["kullanici_adi"], _ip(istek))
        _denetim(istek, "giris", "", "", kullanici=sonuc["kullanici"])
        return _cerez_yaz(_json({"kullanici": sonuc["kullanici"]}), sonuc["token"])

    async def cikis(istek):
        _denetim(istek, "cikis")
        ky.cikis(istek.cookies.get(CEREZ_ADI))
        yanit = _json({"cikis": True})
        yanit.del_cookie(CEREZ_ADI, path="/")
        return yanit

    async def ben(istek):
        return _json({"kullanici": k_gorunum(istek["kullanici"])})

    async def ben_parola(istek):
        v = await _govde(istek)
        try:
            ky.parola_degistir(istek["kullanici"]["id"], str(v.get("eski", "")), str(v.get("yeni", "")),
                               istek.cookies.get(CEREZ_ADI))
        except ValueError as e:
            return _hata(str(e))
        _denetim(istek, "parola_degistirdi", "", "kendi parolası")
        return _json({"degisti": True})

    async def ben_tercihler(istek):
        v = await _govde(istek)
        try:
            t = ky.tercih_guncelle(istek["kullanici"]["id"], v)
        except ValueError as e:
            return _hata(str(e))
        return _json({"tercihler": t})

    # --- kullanıcı yönetimi (yalnız sistem yöneticisi; rol denetimi ara katmanda) ---
    async def kullanici_listesi(_):
        return _json({"kullanicilar": ky.listele(), "roller": ROL_ADLARI})

    async def kullanici_ekle(istek):
        v = await _govde(istek)
        try:
            k = ky.ekle(str(v.get("kullanici_adi", "")), str(v.get("ad", "")), str(v.get("rol", "")), str(v.get("parola", "")))
        except ValueError as e:
            return _hata(str(e))
        _denetim(istek, "kullanici_ekledi", k["kullanici_adi"], k["rol_adi"])
        await filo._olay("kullanici", f"Kullanıcı eklendi: {k['kullanici_adi']} ({k['rol_adi']}) — {istek['kullanici']['kullanici_adi']}", None)
        return _json({"kullanici": k}, 201)

    async def kullanici_guncelle(istek):
        kid = int(istek.match_info["id"])
        v = await _govde(istek)
        if kid == istek["kullanici"]["id"] and ("rol" in v or v.get("etkin") is False):
            return _hata("kendi rolünüzü ya da etkinliğinizi değiştiremezsiniz")
        try:
            k = ky.guncelle(kid, ad=v.get("ad"), rol=v.get("rol"), etkin=v.get("etkin"), parola=v.get("parola") or None)
        except LookupError as e:
            return _hata(str(e), 404)
        except ValueError as e:
            return _hata(str(e))
        degisen = ", ".join(x for x, var in (("ad", v.get("ad") is not None), ("rol", v.get("rol") is not None),
                                              ("etkin", v.get("etkin") is not None), ("parola", bool(v.get("parola")))) if var)
        _denetim(istek, "kullanici_guncelledi", k["kullanici_adi"], f"{degisen} → {k['rol_adi']}, {'etkin' if k['etkin'] else 'pasif'}")
        return _json({"kullanici": k})

    async def kullanici_sil(istek):
        kid = int(istek.match_info["id"])
        if kid == istek["kullanici"]["id"]:
            return _hata("kendinizi silemezsiniz")
        silinen = filo.vt.kullanici(kid)
        try:
            ky.sil(kid)
        except LookupError as e:
            return _hata(str(e), 404)
        except ValueError as e:
            return _hata(str(e))
        _denetim(istek, "kullanici_sildi", silinen["kullanici_adi"] if silinen else str(kid))
        await filo._olay("kullanici", f"Kullanıcı silindi: {silinen['kullanici_adi'] if silinen else kid} — {istek['kullanici']['kullanici_adi']}", None)
        return _json({"silindi": kid})

    async def kullanici_gecmis(istek):
        kid = int(istek.match_info["id"])
        k = filo.vt.kullanici(kid)
        if k is None:
            return _hata("kullanıcı bulunamadı", 404)
        limit = min(int(istek.query.get("limit", "300")), 2000)
        return _json({"kullanici": k_gorunum(k), "gecmis": filo.vt.denetim_listesi(kid, limit, k["kullanici_adi"])})

    async def denetim_listesi(istek):
        limit = min(int(istek.query.get("limit", "300")), 2000)
        return _json({"gecmis": filo.vt.denetim_listesi(None, limit)})

    # --- API ---
    async def surum(_):
        return _json({"urun": URUN_KODU, "ad": URUN_ADI, "surum": SURUM, "firma": FIRMA})

    async def yazicilar(_):
        return _json({"yazicilar": filo.yazicilar_gorunum(), "sayilar": filo.ozet_sayilar()})

    def _olay_suz(olaylar, istek):
        rol = istek["kullanici"]["rol"]
        return [o for o in olaylar if yonetici_mi_gorur(o, rol)]

    async def yazici(istek):
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        g = filo.yazici_gorunum(yid)
        c = g.get("canli") or {}
        return _json({"yazici": g, "ham": filo.ham(yid) if istek["kullanici"]["rol"] == "sistem_yoneticisi" else {},
                      "olaylar": _olay_suz(filo.vt.olaylar(100, yid), istek),
                      "hata": HK.acikla(c.get("hata_kodu"), c.get("hata_anahtari")) if c.get("hata_kodu") else None})

    async def yazici_ekle(istek):
        v = await _govde(istek)
        ip = _ip_dogrula(str(v.get("ip", "")))
        if ip in filo.kayitli_ipler():
            return _hata("bu IP zaten kayıtlı", 409)
        port = int(v.get("port") or P.WS_PORT)
        kayit = await filo.yazici_ekle(str(v.get("ad", "")), ip, port,
                                       model=str(v.get("model", "")), hostname=str(v.get("hostname", "")),
                                       grup=str(v.get("grup", "")), notlar=str(v.get("notlar", "")),
                                       http_port=v.get("http_port"))
        _denetim(istek, "yazici_ekledi", f"{kayit['ad']} ({ip})")
        return _json({"yazici": kayit}, 201)

    async def toplu_ekle(istek):
        v = await _govde(istek)
        secilen = v.get("yazicilar")
        if not isinstance(secilen, list) or not secilen:
            return _hata("yazicilar listesi boş")
        eklenen, atlanan = [], []
        for s in secilen:
            if not isinstance(s, dict):
                continue
            try:
                ip = _ip_dogrula(str(s.get("ip", "")))
            except web.HTTPBadRequest:
                atlanan.append({"ip": s.get("ip"), "neden": "geçersiz IP"})
                continue
            if ip in filo.kayitli_ipler():
                atlanan.append({"ip": ip, "neden": "zaten kayıtlı"})
                continue
            kayit = await filo.yazici_ekle(str(s.get("ad", "")), ip, int(s.get("port") or P.WS_PORT),
                                           model=str(s.get("model", "")), hostname=str(s.get("hostname", "")),
                                           grup=str(s.get("grup", "")))
            eklenen.append(kayit)
        if eklenen:
            _denetim(istek, "yazici_ekledi", f"{len(eklenen)} yazıcı (tarama)", ", ".join(k["ip"] for k in eklenen))
        return _json({"eklenen": eklenen, "atlanan": atlanan}, 201)

    async def yazici_guncelle(istek):
        yid = int(istek.match_info["id"])
        v = await _govde(istek)
        alanlar = {}
        for k in ("ad", "grup", "notlar", "model", "kamera_url"):
            if k in v:
                alanlar[k] = str(v[k]).strip()
        if "ip" in v:
            ip = _ip_dogrula(str(v["ip"]))
            if any(k["ip"] == ip and k["id"] != yid for k in filo.kayitlar.values()):
                return _hata("bu IP başka bir yazıcıda kayıtlı", 409)
            alanlar["ip"] = ip
        if "port" in v:
            alanlar["port"] = int(v["port"])
        if "http_port" in v:
            alanlar["http_port"] = int(v["http_port"])
        if "etkin" in v:
            alanlar["etkin"] = 1 if v["etkin"] else 0
        kayit = await filo.yazici_guncelle(yid, **alanlar)
        if kayit is None:
            return _hata("yazıcı bulunamadı", 404)
        _denetim(istek, "yazici_guncelledi", _yazici_etiketi(yid), ", ".join(f"{k}={v}" for k, v in alanlar.items()))
        return _json({"yazici": kayit})

    async def yazici_sil(istek):
        yid = int(istek.match_info["id"])
        etiket = _yazici_etiketi(yid)
        if not await filo.yazici_sil(yid):
            return _hata("yazıcı bulunamadı", 404)
        _denetim(istek, "yazici_sildi", etiket)
        return _json({"silindi": yid})

    async def komut(istek):
        yid = int(istek.match_info["id"])
        v = await _govde(istek)
        ad = str(v.get("komut", ""))
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        try:
            sonuc = await filo.komut(yid, ad, v.get("deger"), istek["kullanici"]["kullanici_adi"])
        except ValueError as e:
            return _hata(str(e))
        dosya = (filo.baglantilar[yid].ozet().get("dosya") if yid in filo.baglantilar else "") or ""
        _denetim(istek, f"komut_{ad}", _yazici_etiketi(yid),
                 (f"dosya: {dosya}; " if dosya else "") + (f"değer: {v.get('deger')}; " if v.get("deger") is not None else "")
                 + ("gönderildi" if sonuc else "GÖNDERİLEMEDİ: yazıcı bağlı değil"))
        return _json({"gonderildi": sonuc})

    def _zaman(istek, ad, varsayilan=None):
        v = istek.query.get(ad)
        try:
            return float(v) if v not in (None, "") else varsayilan
        except ValueError:
            return varsayilan

    async def telemetri_ornekler(istek):
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        if filo.telemetri is None:
            return _json({"ornekler": [], "ozet": {}})
        limit = min(int(istek.query.get("limit", "600")), 5000)
        adim = _zaman(istek, "adim", 0.0)
        bas = _zaman(istek, "baslangic"); bit = _zaman(istek, "bitis")
        return _json({"ornekler": filo.telemetri.ornekler(yid, bas, bit, limit, adim or 0.0),
                      "ozet": filo.telemetri.ozet(yid)})

    async def telemetri_degisimler(istek):
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        if filo.telemetri is None:
            return _json({"degisimler": []})
        limit = min(int(istek.query.get("limit", "300")), 5000)
        return _json({"degisimler": filo.telemetri.degisimler(yid, istek.query.get("alan") or None, _zaman(istek, "baslangic"), limit)})

    async def telemetri_hatalar(istek):
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        hatalar = filo.telemetri.hatalar(yid) if filo.telemetri else []
        for h in hatalar:
            if h.get("basladi"):
                h["aciklama"] = HK.acikla(h.get("yeni"), h.get("baglam"))
        olaylar = [o for o in filo.vt.olaylar(300, yid) if o["tur"] in ("hata", "hata_gecti", "filament_yok", "koptu", "dis_mudahale")]
        return _json({"hatalar": hatalar, "olaylar": _olay_suz(olaylar, istek)})

    async def kamera_goruntu(istek):
        """kamera_url tanımlıysa sunucu tek kare çeker; değilse 404 + tarayıcı WebRTC bilgisi."""
        yid = int(istek.match_info["id"])
        kayit = filo.kayitlar.get(yid)
        if kayit is None:
            return _hata("yazıcı bulunamadı", 404)
        url = (kayit.get("kamera_url") or "").strip()
        if not url:
            return _json({"hata": "sunucu tarafı kamera URL'si tanımlı değil; tarayıcı WebRTC yolu kullanılır",
                          "webrtc": f"http://{kayit['ip']}:8000/call/webrtc_local", "ip": kayit["ip"]}, 404)
        try:
            veri, tur = await KAM.goruntu_al(url)
        except Exception as e:  # noqa: BLE001
            _denetim(istek, "kamera_goruntu_hatasi", _yazici_etiketi(yid), f"{url}: {e}")
            return _hata(f"kamera görüntüsü alınamadı: {e}", 502)
        _denetim(istek, "kamera_goruntu", _yazici_etiketi(yid), f"sunucu ({len(veri) // 1024} KB)")
        return web.Response(body=veri, content_type=tur, headers={"Cache-Control": "no-store"})

    async def kamera_kayit(istek):
        """Tarayıcının doğrudan WebRTC ile aldığı kare için işlem geçmişi kaydı."""
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        v = await _govde(istek)
        _denetim(istek, "kamera_goruntu" if v.get("basarili", True) else "kamera_goruntu_hatasi", _yazici_etiketi(yid),
                 "tarayıcı WebRTC" + (f": {str(v.get('hata', ''))[:200]}" if v.get("hata") else ""))
        return _json({"kaydedildi": True})

    async def dosya_yukle(istek):
        """multipart: file (zorunlu), baslat (1/0, varsayılan 1). Yükler ve baskıyı başlatır."""
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        okuyucu = await istek.multipart()
        dosya_adi, baslat, gecici = "", True, None
        try:
            async for parca in okuyucu:
                if parca.name == "baslat":
                    baslat = (await parca.text()).strip() not in ("0", "false", "hayir", "")
                elif parca.name == "file":
                    dosya_adi = Y.guvenli_dosya_adi(parca.filename or "")
                    if not Y.uzanti_izinli_mi(dosya_adi):
                        return _hata(f"yalnız {', '.join(Y.IZINLI_UZANTILAR)} dosyaları yüklenebilir")
                    fd, gecici = tempfile.mkstemp(prefix="creamanage_", suffix="_" + dosya_adi)
                    boyut = 0
                    with os.fdopen(fd, "wb") as f:
                        while True:
                            veri = await parca.read_chunk(1024 * 1024)
                            if not veri:
                                break
                            boyut += len(veri)
                            if boyut > Y.EN_BUYUK_DOSYA:
                                return _hata("dosya çok büyük", 413)
                            f.write(veri)
            if not gecici or not dosya_adi:
                return _hata("file alanı eksik")
            try:
                sonuc = await filo.dosya_yukle_ve_baslat(yid, dosya_adi, gecici, baslat, istek["kullanici"]["kullanici_adi"])
            except RuntimeError as e:
                _denetim(istek, "dosya_yukleme_hatasi", _yazici_etiketi(yid), f"{dosya_adi}: {e}")
                return _hata(str(e), 502)
            _denetim(istek, "dosya_yukledi", _yazici_etiketi(yid),
                     f"{sonuc['dosya_adi']} ({boyut // 1024} KB)" + ("; baskı başlatıldı" if sonuc["baslatildi"] else ("; başlatılmadı" if not baslat else "; BAŞLATILAMADI")))
            return _json(sonuc, 201)
        finally:
            if gecici:
                try:
                    os.unlink(gecici)
                except OSError:
                    pass

    async def aglar(_):
        return _json({"aglar": filo.aglar()})

    async def tarama_baslat(istek):
        v = await _govde(istek)
        cidr = str(v.get("cidr", "")).strip()
        if not cidr:
            return _hata("cidr gerekli")
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return _hata("geçersiz CIDR")
        try:
            t = filo.tarama_baslat(cidr, int(v.get("port") or P.WS_PORT))
        except RuntimeError as e:
            return _hata(str(e), 409)
        _denetim(istek, "tarama_baslatti", cidr)
        return _json({"tarama": filo.tarama_gorunum(), "id": t.id}, 202)

    async def tarama_durum(_):
        t = filo.tarama_gorunum()
        if t is None:
            return _hata("tarama yok", 404)
        return _json({"tarama": t})

    async def tarama_iptal(_):
        if filo.tarama is None:
            return _hata("tarama yok", 404)
        filo.tarama.iptal()
        _denetim(istek, "tarama_iptal", filo.tarama.cidr)
        return _json({"iptal": True})

    async def olaylar(istek):
        limit = min(int(istek.query.get("limit", "100")), 1000)
        return _json({"olaylar": _olay_suz(filo.vt.olaylar(limit), istek)})

    async def hata_kodlari_oku(istek):
        return _json({"bilgi": HK.bilgi(), "kodlar": HK.kodlar(), "liste": HK.listele()})

    async def hata_kodu_yaz(istek):
        kod = istek.match_info["kod"]
        v = await _govde(istek)
        try:
            kayit = HK.kod_kaydet(kod, v)
        except ValueError as e:
            return _hata(str(e))
        _denetim(istek, "hata_kodu_kaydetti", kayit["tam_kod"], kayit["baslik"][:120])
        return _json({"kayit": kayit, "bilgi": HK.bilgi()})

    async def hata_kodu_sil(istek):
        kod = istek.match_info["kod"]
        if not HK.kod_sil(kod):
            return _hata("kod bulunamadı", 404)
        _denetim(istek, "hata_kodu_sildi", kod)
        return _json({"silindi": HK.kanonik(kod), "bilgi": HK.bilgi()})

    async def hata_kodlari_ice_aktar(istek):
        """multipart file: .csv (kod;başlık;açıklama;çözüm;modül), .json ({"kodlar":{…}} ya da düz sözlük), .html (Creality sayfası)."""
        import sys as _sys
        _sys.path.insert(0, str(WEB_DIZIN.parent / "araclar"))
        from hata_kodlari_al import csv_ayristir, html_ayristir  # noqa: WPS433
        okuyucu = await istek.multipart()
        ad, icerik = "", b""
        async for parca in okuyucu:
            if parca.name == "file":
                ad = (parca.filename or "").lower()
                icerik = await parca.read(decode=False)
                break
        if not icerik:
            return _hata("dosya eksik")
        metin = icerik.decode("utf-8-sig", errors="ignore")
        try:
            if ad.endswith(".json"):
                veri = json.loads(metin)
                yeni = veri.get("kodlar", veri) if isinstance(veri, dict) else {}
                yeni = {k: v for k, v in yeni.items() if isinstance(v, dict) and not str(k).startswith("_")}
            elif ad.endswith(".csv") or ad.endswith(".txt"):
                fd, yol = tempfile.mkstemp(suffix=".csv")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(metin)
                try:
                    yeni = csv_ayristir(yol)
                finally:
                    os.unlink(yol)
            else:
                yeni = html_ayristir(metin)
        except (ValueError, OSError) as e:
            return _hata(f"dosya çözümlenemedi: {e}")
        if not yeni:
            return _hata("dosyada kod bulunamadı (CSV: kod;başlık;açıklama;çözüm;modül — noktalı virgülle)")
        mevcut = dict(HK.kodlar()); mevcut.update({HK.kanonik(k): v for k, v in yeni.items() if HK.kanonik(k)})
        adet = HK.kaydet(mevcut, f"içe aktarım: {ad} ({istek['kullanici']['kullanici_adi']})")
        _denetim(istek, "hata_kodu_ice_aktardi", ad, f"{len(yeni)} kod, toplam {adet}")
        return _json({"alinan": len(yeni), "toplam": adet, "bilgi": HK.bilgi()})

    # --- Telegram bildirim ayarları ---
    def _tg() -> TelegramBildirici:
        if telegram is None:
            raise web.HTTPNotFound(text="Telegram kanalı etkin değil")
        return telegram

    async def telegram_oku(_):
        return _json({"telegram": _tg().gorunum()})

    async def telegram_yaz(istek):
        v = await _govde(istek)
        tg = _tg()
        try:
            gorunum = tg.kaydet(v)
        except ValueError as e:
            return _hata(str(e))
        _denetim(istek, "bildirim_ayarladi", "Telegram",
                 ", ".join(x for x, var in (("belirteç", bool(str(v.get("token") or "").strip())), ("sohbetler", "sohbetler" in v),
                                            ("olaylar", "olaylar" in v), ("etkin", "etkin" in v)) if var))
        uyari = ""
        if tg.ayar["token"]:
            try:
                bot = await tg.bot_bilgisi()            # kaydedilen belirteci hemen doğrula
                gorunum = tg.gorunum()
            except Exception as e:  # noqa: BLE001
                uyari = f"Ayar kaydedildi ama Telegram doğrulaması başarısız: {e}"
        return _json({"telegram": gorunum, "uyari": uyari})

    async def telegram_test(istek):
        v = await _govde(istek)
        tg = _tg()
        token = str(v.get("token") or "").strip() or None
        sohbetler = v.get("sohbetler")
        sohbetler = [str(x).strip() for x in sohbetler if str(x).strip()] if isinstance(sohbetler, list) else None
        if not (token or tg.ayar["token"]):
            return _hata("bot belirteci girilmemiş")
        if not (sohbetler or tg.ayar["sohbetler"]):
            return _hata("sohbet kimliği girilmemiş")
        hatalar = await tg.test_mesaji(token, sohbetler)
        _denetim(istek, "bildirim_test", "Telegram", "başarılı" if not hatalar else "; ".join(hatalar))
        return _json({"basarili": not hatalar, "hatalar": hatalar})

    async def telegram_sohbetler(istek):
        v = await _govde(istek)
        tg = _tg()
        token = str(v.get("token") or "").strip() or None
        try:
            bot = await tg.bot_bilgisi(token)
            sohbetler = await tg.sohbetleri_bul(token)
        except Exception as e:  # noqa: BLE001
            return _hata(f"Telegram: {e}", 502)
        return _json({"bot": bot, "sohbetler": sohbetler})

    async def ws_ucu(istek):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(istek)
        app[WS_ROLLER][ws] = istek["kullanici"]["rol"]
        app[WS_ISTEMCILER].add(ws)
        try:
            await ws.send_str(json.dumps({
                "tur": "anlik", "kullanici": k_gorunum(istek["kullanici"]), "yazicilar": filo.yazicilar_gorunum(),
                "sayilar": filo.ozet_sayilar(), "olaylar": _olay_suz(filo.vt.olaylar(100), istek),
                "tarama": filo.tarama_gorunum()}, ensure_ascii=False))
            async for msg in ws:
                if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            app[WS_ISTEMCILER].discard(ws)
        return ws

    app.router.add_get("/", ana_sayfa)
    app.router.add_get("/giris", giris_sayfasi)
    app.router.add_get("/api/kurulum", kurulum_durum)
    app.router.add_post("/api/kurulum", kurulum_yap)
    app.router.add_post("/api/giris", giris)
    app.router.add_post("/api/cikis", cikis)
    app.router.add_get("/api/ben", ben)
    app.router.add_put("/api/ben/parola", ben_parola)
    app.router.add_put("/api/ben/tercihler", ben_tercihler)
    app.router.add_get("/api/kullanicilar", kullanici_listesi)
    app.router.add_post("/api/kullanicilar", kullanici_ekle)
    app.router.add_put(r"/api/kullanicilar/{id:\d+}", kullanici_guncelle)
    app.router.add_delete(r"/api/kullanicilar/{id:\d+}", kullanici_sil)
    app.router.add_get(r"/api/kullanicilar/{id:\d+}/gecmis", kullanici_gecmis)
    app.router.add_get("/api/kullanicilar/gecmis", denetim_listesi)
    app.router.add_get("/api/surum", surum)
    app.router.add_get("/api/yazicilar", yazicilar)
    app.router.add_post("/api/yazicilar", yazici_ekle)
    app.router.add_post("/api/yazicilar/toplu", toplu_ekle)
    app.router.add_get(r"/api/yazicilar/{id:\d+}", yazici)
    app.router.add_put(r"/api/yazicilar/{id:\d+}", yazici_guncelle)
    app.router.add_delete(r"/api/yazicilar/{id:\d+}", yazici_sil)
    app.router.add_post(r"/api/yazicilar/{id:\d+}/komut", komut)
    app.router.add_post(r"/api/yazicilar/{id:\d+}/dosya", dosya_yukle)
    app.router.add_get(r"/api/yazicilar/{id:\d+}/kamera", kamera_goruntu)
    app.router.add_post(r"/api/yazicilar/{id:\d+}/kamera/kayit", kamera_kayit)
    app.router.add_get(r"/api/yazicilar/{id:\d+}/telemetri", telemetri_ornekler)
    app.router.add_get(r"/api/yazicilar/{id:\d+}/degisimler", telemetri_degisimler)
    app.router.add_get(r"/api/yazicilar/{id:\d+}/hatalar", telemetri_hatalar)
    app.router.add_get("/api/aglar", aglar)
    app.router.add_post("/api/tarama", tarama_baslat)
    app.router.add_get("/api/tarama", tarama_durum)
    app.router.add_post("/api/tarama/iptal", tarama_iptal)
    app.router.add_get("/api/olaylar", olaylar)
    app.router.add_get("/api/hata_kodlari", hata_kodlari_oku)
    app.router.add_put("/api/hata_kodlari/{kod}", hata_kodu_yaz)
    app.router.add_delete("/api/hata_kodlari/{kod}", hata_kodu_sil)
    app.router.add_post("/api/hata_kodlari/ice_aktar", hata_kodlari_ice_aktar)
    app.router.add_get("/api/ayarlar/telegram", telegram_oku)
    app.router.add_put("/api/ayarlar/telegram", telegram_yaz)
    app.router.add_post("/api/ayarlar/telegram/test", telegram_test)
    app.router.add_post("/api/ayarlar/telegram/sohbetler", telegram_sohbetler)
    app.router.add_get("/ws", ws_ucu)
    app.router.add_static("/static/", WEB_DIZIN, show_index=False)

    async def kapanis(_):
        for ws in list(app[WS_ISTEMCILER]):
            await ws.close()
        await filo.durdur()

    app.on_shutdown.append(kapanis)
    return app
