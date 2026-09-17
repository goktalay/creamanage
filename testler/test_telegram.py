"""Telegram bildirim kanalı testleri — sahte Telegram API sunucusuyla (ağ yok)."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage.olaylar import O_BASKI_BITTI, O_HATA, O_KOPTU, OlayMerkezi  # noqa: E402
from creamanage import telegram as T  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402


class SahteTelegram:
    """api.telegram.org taklidi: sendMessage, getMe, getUpdates; isteğe bağlı 429."""

    def __init__(self) -> None:
        self.gelen: list[dict] = []
        self.kalan_429 = 0
        app = web.Application()
        app.router.add_post("/bot{token}/{yontem}", self._ele)
        self.sunucu = TestServer(app)

    async def _ele(self, istek: web.Request):
        token, yontem = istek.match_info["token"], istek.match_info["yontem"]
        govde = await istek.json()
        if token != "GECERLI:TOKEN":
            return web.json_response({"ok": False, "description": "Unauthorized"}, status=401)
        if yontem == "sendMessage":
            if self.kalan_429 > 0:
                self.kalan_429 -= 1
                return web.json_response({"ok": False, "parameters": {"retry_after": 0}}, status=429)
            if str(govde.get("chat_id")) == "999":
                return web.json_response({"ok": False, "description": "chat not found"}, status=400)
            self.gelen.append(govde)
            return web.json_response({"ok": True, "result": {"message_id": len(self.gelen)}})
        if yontem == "getMe":
            return web.json_response({"ok": True, "result": {"username": "creamanage_bot", "first_name": "CreaManage"}})
        if yontem == "getUpdates":
            return web.json_response({"ok": True, "result": [
                {"update_id": 1, "message": {"chat": {"id": 42, "type": "private", "first_name": "Ali", "last_name": "Veli"}}},
                {"update_id": 2, "message": {"chat": {"id": 42, "type": "private", "first_name": "Ali"}}},
                {"update_id": 3, "channel_post": {"chat": {"id": -100123, "type": "channel", "title": "Atölye"}}},
            ]})
        return web.json_response({"ok": False, "description": "bilinmeyen"}, status=404)

    @property
    def taban(self) -> str:
        return f"http://{self.sunucu.host}:{self.sunucu.port}"


class MesajTesti(unittest.TestCase):
    def test_tek_olay(self):
        m = T.mesaj_olustur([{"tur": O_HATA, "mesaj": "Y1: hata 2001 E2001", "veri": {}}])
        self.assertIn("🔴", m)
        self.assertIn("Y1: hata 2001 E2001", m)

    def test_coklu_ve_kacis(self):
        olaylar = [{"tur": O_KOPTU, "mesaj": f"Y{i}: bağlantı koptu <x>", "veri": {}} for i in range(45)]
        m = T.mesaj_olustur(olaylar)
        self.assertIn("45 olay", m)
        self.assertIn("&lt;x&gt;", m)
        self.assertIn("… ve 5 olay daha", m)

    def test_sure(self):
        m = T.mesaj_olustur([{"tur": O_BASKI_BITTI, "mesaj": "Y1: baskı tamamlandı a.gcode", "veri": {"sure_sn": 7800}}])
        self.assertIn("(2 sa 10 dk)", m)

    def test_sohbet_ayiklama(self):
        self.assertEqual(T._sohbetleri_ayikla("1, 2;3\n1"), ["1", "2", "3"])
        self.assertEqual(T._sohbetleri_ayikla([5, "6"]), ["5", "6"])


class BildiriciTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tg_sunucu = SahteTelegram()
        await self.tg_sunucu.sunucu.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.b = T.TelegramBildirici(self.vt, api_taban=self.tg_sunucu.taban)
        T.TOPLAMA_PENCERESI_SN = 0.1

    async def asyncTearDown(self):
        await self.tg_sunucu.sunucu.close()
        self.vt.kapat()
        self.tmp.cleanup()

    async def test_ayar_kalicidir_ve_token_maskelenir(self):
        g = self.b.kaydet({"token": "GECERLI:TOKEN", "sohbetler": "42, -100123", "etkin": True, "olaylar": [O_HATA, "yok"]})
        self.assertTrue(g["token_var"])
        self.assertNotIn("GECERLI:TOKEN", str(g))
        self.assertEqual(g["olaylar"], [O_HATA])
        # boş token gönderilince mevcut korunur
        self.b.kaydet({"token": "", "etkin": False})
        yeni = T.TelegramBildirici(self.vt, api_taban=self.tg_sunucu.taban)
        self.assertEqual(yeni.ayar["token"], "GECERLI:TOKEN")
        self.assertEqual(yeni.ayar["sohbetler"], ["42", "-100123"])
        self.assertFalse(yeni.ayar["etkin"])

    async def test_olaylar_toplanip_gonderilir(self):
        self.b.kaydet({"token": "GECERLI:TOKEN", "sohbetler": ["42"], "etkin": True, "olaylar": [O_HATA, O_BASKI_BITTI]})
        merkez = OlayMerkezi()
        merkez.abone_ol(self.b.olay_geldi)
        await merkez.yayinla({"tur": O_HATA, "mesaj": "Y1: hata 5", "veri": {}})
        await merkez.yayinla({"tur": O_KOPTU, "mesaj": "Y2: koptu", "veri": {}})       # seçili değil
        await merkez.yayinla({"tur": O_BASKI_BITTI, "mesaj": "Y3: baskı tamamlandı a.gcode", "veri": {"sure_sn": 60}})
        await self.b.bekle()
        self.assertEqual(len(self.tg_sunucu.gelen), 1)          # tek toplu mesaj
        metin = self.tg_sunucu.gelen[0]["text"]
        self.assertIn("2 olay", metin)
        self.assertIn("Y1: hata 5", metin)
        self.assertNotIn("Y2", metin)
        self.assertEqual(self.tg_sunucu.gelen[0]["chat_id"], "42")
        self.assertEqual(self.b.gonderilen, 1)
        self.assertEqual(self.b.son_hata, "")

    async def test_devre_disi_gondermez(self):
        self.b.kaydet({"token": "GECERLI:TOKEN", "sohbetler": ["42"], "etkin": False})
        await self.b.olay_geldi({"tur": O_HATA, "mesaj": "x", "veri": {}})
        await self.b.bekle()
        self.assertEqual(self.tg_sunucu.gelen, [])

    async def test_429_yeniden_dener_ve_hatali_sohbet_raporlanir(self):
        self.b.kaydet({"token": "GECERLI:TOKEN", "sohbetler": ["42", "999"], "etkin": True})
        self.tg_sunucu.kalan_429 = 1
        hatalar = await self.b.test_mesaji()
        self.assertEqual(len(self.tg_sunucu.gelen), 1)
        self.assertEqual(len(hatalar), 1)
        self.assertIn("999", hatalar[0])
        self.assertIn("chat not found", self.b.son_hata)

    async def test_gecersiz_token(self):
        hatalar = await self.b.test_mesaji(token="YANLIS", sohbetler=["42"])
        self.assertEqual(len(hatalar), 1)
        self.assertIn("Unauthorized", hatalar[0])

    async def test_sohbetleri_bul(self):
        s = await self.b.sohbetleri_bul(token="GECERLI:TOKEN")
        self.assertEqual({x["id"] for x in s}, {"42", "-100123"})
        self.assertEqual([x["ad"] for x in s if x["id"] == "-100123"], ["Atölye"])
        b = await self.b.bot_bilgisi(token="GECERLI:TOKEN")
        self.assertEqual(b["kullanici_adi"], "creamanage_bot")


class ApiTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from creamanage.filo import Filo
        from creamanage.web import uygulama_olustur
        self.tg_sunucu = SahteTelegram()
        await self.tg_sunucu.sunucu.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.b = T.TelegramBildirici(self.vt, api_taban=self.tg_sunucu.taban)
        self.filo = Filo(self.vt)
        self.filo.olaylar.abone_ol(self.b.olay_geldi)
        await self.filo.baslat()
        self.client = TestClient(TestServer(uygulama_olustur(self.filo, self.b)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.tg_sunucu.sunucu.close()
        self.vt.kapat()
        self.tmp.cleanup()

    async def test_ayar_uclari(self):
        r = await self.client.get("/api/ayarlar/telegram")
        v = (await r.json())["telegram"]
        self.assertFalse(v["token_var"])
        self.assertTrue(any(s["tur"] == O_HATA for s in v["secilebilir"]))
        r = await self.client.put("/api/ayarlar/telegram", json={"token": "GECERLI:TOKEN", "sohbetler": "42", "etkin": True, "olaylar": [O_HATA]})
        self.assertEqual(r.status, 200)
        v = (await r.json())["telegram"]
        self.assertTrue(v["token_var"]); self.assertEqual(v["sohbetler"], ["42"])
        r = await self.client.post("/api/ayarlar/telegram/test", json={})
        self.assertTrue((await r.json())["basarili"])
        self.assertEqual(len(self.tg_sunucu.gelen), 1)
        r = await self.client.post("/api/ayarlar/telegram/sohbetler", json={})
        v = await r.json()
        self.assertEqual(v["bot"]["kullanici_adi"], "creamanage_bot")
        self.assertEqual(len(v["sohbetler"]), 2)
        r = await self.client.post("/api/ayarlar/telegram/sohbetler", json={"token": "YANLIS"})
        self.assertEqual(r.status, 502)

    async def test_eksik_ayarla_test_reddedilir(self):
        r = await self.client.post("/api/ayarlar/telegram/test", json={})
        self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
