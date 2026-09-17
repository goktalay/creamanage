"""Sistem dışı müdahale (majör olay), rol bazlı olay görünürlüğü, hata kodu tablosu."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KAYNAK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KAYNAK)); sys.path.insert(0, str(KAYNAK / "araclar"))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage import hata_kodlari as HK  # noqa: E402
from creamanage import telegram as T  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.kullanicilar import KullaniciYonetimi  # noqa: E402
from creamanage.olaylar import O_DIS_MUDAHALE  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import uygulama_olustur  # noqa: E402
from sahte_yazici import filo_kur  # noqa: E402
from test_telegram import SahteTelegram  # noqa: E402

PORT = int(os.environ.get("CREAMANAGE_TEST_PORT", "19999"))


async def bekle(kosul, sn=8.0):
    son = asyncio.get_running_loop().time() + sn
    while asyncio.get_running_loop().time() < son:
        if kosul():
            return True
        await asyncio.sleep(0.05)
    return kosul()


class HataKoduTesti(unittest.TestCase):
    def setUp(self):
        self._eski = HK.DOSYA
        self.tmp = tempfile.TemporaryDirectory()
        HK.DOSYA = Path(self.tmp.name) / "h.json"
        HK.yukle(zorla=True)

    def tearDown(self):
        HK.DOSYA = self._eski; HK.yukle(zorla=True); self.tmp.cleanup()

    def test_bilinmeyen_ve_bilinen(self):
        a = HK.acikla(500, "2718")
        self.assertFalse(a["bilinen"]); self.assertIn("2718", a["metin"]); self.assertEqual(a["sinif"], "Kritik hata")
        HK.kaydet({"2718": {"baslik": "Nozul ısınma hatası", "aciklama": "Isıtıcı hedefe ulaşamadı", "cozum": "Termistörü kontrol edin", "modul": "Ekstruder"}}, "test")
        a = HK.acikla(500, "2718")
        self.assertTrue(a["bilinen"]); self.assertEqual(a["metin"], "Nozul ısınma hatası"); self.assertEqual(a["modul"], "Ekstruder")
        self.assertEqual(HK.acikla(2718, None)["metin"], "Nozul ısınma hatası")      # key yoksa errcode ile
        self.assertEqual(HK.bilgi()["adet"], 1)

    def test_html_ayristirma(self):
        from hata_kodlari_al import html_ayristir
        html = """<h2>Extruder</h2><table><tr><th>Code</th><th>Description</th><th>Solution</th></tr>
        <tr><td>E-2718</td><td>Nozzle heating failed</td><td>Check the thermistor</td></tr>
        <tr><td>2060</td><td>Bed leveling failed</td><td>Clean the nozzle</td></tr><tr><td>abc</td><td>x</td></tr></table>"""
        k = html_ayristir(html)
        self.assertEqual(set(k), {"2718", "2060"})
        self.assertEqual(k["2718"]["aciklama"], "Nozzle heating failed"); self.assertEqual(k["2718"]["cozum"], "Check the thermistor")


class HataKoduApiTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._eski = HK.DOSYA
        self.tmp = tempfile.TemporaryDirectory()
        HK.DOSYA = Path(self.tmp.name) / "h.json"; HK.yukle(zorla=True)
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.filo = Filo(self.vt); await self.filo.baslat()
        self.app = uygulama_olustur(self.filo)
        self.admin = TestClient(TestServer(self.app)); await self.admin.start_server()
        self.yy = TestClient(TestServer(self.app)); await self.yy.start_server()
        ky = KullaniciYonetimi(self.vt); ky.ekle("admin", "A", "sistem_yoneticisi", "testparola123"); ky.ekle("yyon", "Y", "yazici_yoneticisi", "testparola123")
        await self.admin.post("/api/giris", json={"kullanici_adi": "admin", "parola": "testparola123"})
        await self.yy.post("/api/giris", json={"kullanici_adi": "yyon", "parola": "testparola123"})

    async def asyncTearDown(self):
        await self.admin.close(); await self.yy.close(); self.vt.kapat(); HK.DOSYA = self._eski; HK.yukle(zorla=True); self.tmp.cleanup()

    async def test_yonetim(self):
        r = await self.admin.put("/api/hata_kodlari/CA2070", json={"tam_kod": "CA2070", "baslik": "Kayış gerdirme hatası", "cozum": "Gerdiriciyi kontrol edin", "modul": "Kayış"})
        self.assertEqual(r.status, 200, await r.text()); v = await r.json(); self.assertEqual(v["kayit"]["kod"], "2070")
        r = await self.admin.put("/api/hata_kodlari/2071", json={"baslik": ""}); self.assertEqual(r.status, 400)
        r = await self.yy.put("/api/hata_kodlari/2072", json={"baslik": "x"}); self.assertEqual(r.status, 403)     # yalnız sistem yöneticisi
        r = await self.yy.get("/api/hata_kodlari"); self.assertEqual(r.status, 200)                              # okuma herkese
        self.assertEqual(HK.acikla(500, "2070")["metin"], "Kayış gerdirme hatası")
        # CSV içe aktarım
        import aiohttp as _a
        fd = _a.FormData(); fd.add_field("file", "CB2510;Sıcak yatak termistörü açık devre;;Kabloyu kontrol edin;Kontrolör\nabc;x\n".encode("utf-8"), filename="tablo.csv")
        r = await self.admin.post("/api/hata_kodlari/ice_aktar", data=fd); self.assertEqual(r.status, 200, await r.text())
        v = await r.json(); self.assertEqual(v["alinan"], 1); self.assertEqual(v["toplam"], 2)
        # JSON içe aktarım
        fd = _a.FormData(); fd.add_field("file", json.dumps({"kodlar": {"XS2000": {"baslik": "Sistem hatası", "cozum": "Yeniden başlatın"}}}).encode(), filename="k.json")
        r = await self.admin.post("/api/hata_kodlari/ice_aktar", data=fd); self.assertEqual((await r.json())["toplam"], 3)
        r = await self.admin.get("/api/hata_kodlari"); liste = (await r.json())["liste"]; self.assertEqual([k["kod"] for k in liste], ["2000", "2070", "2510"])
        r = await self.admin.delete("/api/hata_kodlari/CA2070"); self.assertEqual(r.status, 200)
        r = await self.admin.delete("/api/hata_kodlari/CA2070"); self.assertEqual(r.status, 404)
        self.assertIn("hata_kodu_kaydetti", [g["eylem"] for g in self.vt.denetim_listesi()])
        self.assertIn("hata_kodu_ice_aktardi", [g["eylem"] for g in self.vt.denetim_listesi()])
        # tercih: yenileme_sn
        r = await self.admin.put("/api/ben/tercihler", json={"yenileme_sn": 10}); self.assertEqual(r.status, 200)
        r = await self.admin.put("/api/ben/tercihler", json={"yenileme_sn": 0}); self.assertEqual(r.status, 400)


class MudahaleTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sahte = await filo_kur(1, baslangic=2, port=PORT, hizli=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.tg_sunucu = SahteTelegram(); await self.tg_sunucu.sunucu.start_server()
        self.tg = T.TelegramBildirici(self.vt, api_taban=self.tg_sunucu.taban); T.TOPLAMA_PENCERESI_SN = 0.1
        self.tg.kaydet({"token": "123456789:AAGdo9GEHHPcxMATlcIK8diyIAKU_rSS_TEST", "sohbetler": ["42"], "yonetici_sohbetler": ["-100123"], "etkin": True, "olaylar": ["hata", "duraklatildi"]})
        self.filo = Filo(self.vt); self.filo.olaylar.abone_ol(self.tg.olay_geldi); await self.filo.baslat()
        self.app = uygulama_olustur(self.filo, self.tg)
        self.admin = TestClient(TestServer(self.app)); await self.admin.start_server()
        self.goz = TestClient(TestServer(self.app)); await self.goz.start_server()
        ky = KullaniciYonetimi(self.vt)
        ky.ekle("admin", "A", "sistem_yoneticisi", "testparola123"); ky.ekle("goz", "G", "gozetmen", "testparola123")
        ky.ekle("yyon", "Y", "yazici_yoneticisi", "testparola123")
        await self.admin.post("/api/giris", json={"kullanici_adi": "admin", "parola": "testparola123"})
        await self.goz.post("/api/giris", json={"kullanici_adi": "goz", "parola": "testparola123"})
        self.sahte[0].baski_baslat("is.gcode", katman=1000)
        r = await self.admin.post("/api/yazicilar", json={"ad": "Y1", "ip": "127.0.0.2", "port": PORT})
        self.yid = (await r.json())["yazici"]["id"]
        self.assertTrue(await bekle(lambda: self.filo.yazici_gorunum(self.yid)["canli"]["durum"] == "basiyor"))

    async def asyncTearDown(self):
        await self.admin.close(); await self.goz.close(); await self.tg_sunucu.sunucu.close(); self.vt.kapat(); self.tmp.cleanup()
        for y in self.sahte:
            await y.durdur()

    def _turler(self):
        return [o["tur"] for o in self.vt.olaylar(50, self.yid)]

    async def test_sistem_komutu_major_uretmez(self):
        r = await self.admin.post(f"/api/yazicilar/{self.yid}/komut", json={"komut": "duraklat"}); self.assertEqual(r.status, 200)
        self.assertTrue(await bekle(lambda: "duraklatildi" in self._turler()))
        await asyncio.sleep(0.3)
        self.assertNotIn(O_DIS_MUDAHALE, self._turler())

    async def test_yazicidan_durdurma_major_ve_yalniz_yonetici(self):
        ws_admin = await self.admin.ws_connect("/ws"); await ws_admin.receive_json()
        ws_goz = await self.goz.ws_connect("/ws"); await ws_goz.receive_json()
        # Yazıcının ekranından duraklatma: simülatöre doğrudan komut (sistem üzerinden değil)
        self.sahte[0]._komut({"pause": 1})
        self.assertTrue(await bekle(lambda: O_DIS_MUDAHALE in self._turler(), sn=10))
        olay = next(o for o in self.vt.olaylar(50, self.yid) if o["tur"] == O_DIS_MUDAHALE)
        self.assertEqual(olay["seviye"], "major"); self.assertIn("YAZICIDAN", olay["mesaj"]); self.assertIn("is.gcode", olay["mesaj"])
        # API: gözetmen majör olayı görmez, yönetici görür
        r = await self.goz.get("/api/olaylar"); self.assertNotIn(O_DIS_MUDAHALE, [o["tur"] for o in (await r.json())["olaylar"]])
        r = await self.admin.get("/api/olaylar"); self.assertIn(O_DIS_MUDAHALE, [o["tur"] for o in (await r.json())["olaylar"]])
        r = await self.goz.get(f"/api/yazicilar/{self.yid}"); self.assertNotIn(O_DIS_MUDAHALE, [o["tur"] for o in (await r.json())["olaylar"]])
        # WS: yönetici alır
        gelen = []
        for _ in range(30):
            m = await asyncio.wait_for(ws_admin.receive_json(), timeout=5)
            if m["tur"] == "olay": gelen.append(m["olay"]["tur"])
            if O_DIS_MUDAHALE in gelen: break
        self.assertIn(O_DIS_MUDAHALE, gelen)
        # WS: gözetmene majör gitmez (duraklatildi olayı gider)
        goz_gelen = []
        for _ in range(30):
            try:
                m = await asyncio.wait_for(ws_goz.receive_json(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            if m["tur"] == "olay": goz_gelen.append(m["olay"]["tur"])
        self.assertNotIn(O_DIS_MUDAHALE, goz_gelen); self.assertIn("duraklatildi", goz_gelen)
        await ws_admin.close(); await ws_goz.close()
        # Telegram: majör yalnız yönetici kanalına, duraklatildi normal kanala
        await self.tg.bekle()
        self.assertTrue(await bekle(lambda: len(self.tg_sunucu.gelen) >= 2, sn=5), self.tg_sunucu.gelen)
        hedefler = {g["chat_id"]: g["text"] for g in self.tg_sunucu.gelen}
        self.assertIn("MAJÖR", hedefler.get("-100123", "")); self.assertNotIn("MAJÖR", hedefler.get("42", ""))
        self.assertIn("duraklatıldı", hedefler.get("42", ""))

    async def test_yazicidan_iptal_major(self):
        self.sahte[0]._komut({"stop": 1})
        self.assertTrue(await bekle(lambda: O_DIS_MUDAHALE in self._turler(), sn=10))
        olay = next(o for o in self.vt.olaylar(50, self.yid) if o["tur"] == O_DIS_MUDAHALE)
        self.assertIn("iptal", olay["mesaj"])


if __name__ == "__main__":
    unittest.main()
