"""aiohttp web uygulaması: statik arayüz, REST API, tarayıcıya WebSocket yayını."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import weakref
from pathlib import Path

from aiohttp import WSMsgType, web

from . import k2_protokol as P
from .filo import Filo
from .kullanicilar import CEREZ_ADI, OTURUM_EN_FAZLA_SN, ROL_ADLARI, KullaniciYonetimi, gorunum as k_gorunum, yetkili_mi
from .telegram import TelegramBildirici
from .surum import FIRMA, SURUM, URUN_ADI, URUN_KODU

log = logging.getLogger("creamanage.web")
FILO_ANAHTAR = web.AppKey("filo", Filo)
WS_ISTEMCILER = web.AppKey("ws_istemciler", weakref.WeakSet)
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
    if yol.startswith("/api/kullanicilar"):
        return "sistem_yoneticisi"
    if yol in ("/api/cikis", "/api/ben", "/api/ben/parola"):
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

    app = web.Application(middlewares=[kimlik_katmani])
    app[FILO_ANAHTAR] = filo
    app[WS_ISTEMCILER] = weakref.WeakSet()

    async def yayin(mesaj: dict) -> None:
        metin = json.dumps(mesaj, ensure_ascii=False)
        for ws in list(app[WS_ISTEMCILER]):
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

    async def yazici(istek):
        yid = int(istek.match_info["id"])
        if yid not in filo.kayitlar:
            return _hata("yazıcı bulunamadı", 404)
        return _json({"yazici": filo.yazici_gorunum(yid), "ham": filo.ham(yid),
                      "olaylar": filo.vt.olaylar(50, yid)})

    async def yazici_ekle(istek):
        v = await _govde(istek)
        ip = _ip_dogrula(str(v.get("ip", "")))
        if ip in filo.kayitli_ipler():
            return _hata("bu IP zaten kayıtlı", 409)
        port = int(v.get("port") or P.WS_PORT)
        kayit = await filo.yazici_ekle(str(v.get("ad", "")), ip, port,
                                       model=str(v.get("model", "")), hostname=str(v.get("hostname", "")),
                                       grup=str(v.get("grup", "")), notlar=str(v.get("notlar", "")))
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
        for k in ("ad", "grup", "notlar", "model"):
            if k in v:
                alanlar[k] = str(v[k])
        if "ip" in v:
            ip = _ip_dogrula(str(v["ip"]))
            if any(k["ip"] == ip and k["id"] != yid for k in filo.kayitlar.values()):
                return _hata("bu IP başka bir yazıcıda kayıtlı", 409)
            alanlar["ip"] = ip
        if "port" in v:
            alanlar["port"] = int(v["port"])
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
            sonuc = await filo.komut(yid, ad, v.get("deger"))
        except ValueError as e:
            return _hata(str(e))
        dosya = (filo.baglantilar[yid].ozet().get("dosya") if yid in filo.baglantilar else "") or ""
        _denetim(istek, f"komut_{ad}", _yazici_etiketi(yid),
                 (f"dosya: {dosya}; " if dosya else "") + (f"değer: {v.get('deger')}; " if v.get("deger") is not None else "")
                 + ("gönderildi" if sonuc else "GÖNDERİLEMEDİ: yazıcı bağlı değil"))
        return _json({"gonderildi": sonuc})

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
        return _json({"iptal": True})

    async def olaylar(istek):
        limit = min(int(istek.query.get("limit", "100")), 1000)
        return _json({"olaylar": filo.vt.olaylar(limit)})

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
        app[WS_ISTEMCILER].add(ws)
        try:
            await ws.send_str(json.dumps({
                "tur": "anlik", "kullanici": k_gorunum(istek["kullanici"]), "yazicilar": filo.yazicilar_gorunum(),
                "sayilar": filo.ozet_sayilar(), "olaylar": filo.vt.olaylar(50),
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
    app.router.add_get("/api/aglar", aglar)
    app.router.add_post("/api/tarama", tarama_baslat)
    app.router.add_get("/api/tarama", tarama_durum)
    app.router.add_post("/api/tarama/iptal", tarama_iptal)
    app.router.add_get("/api/olaylar", olaylar)
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
