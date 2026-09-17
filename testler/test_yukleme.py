"""Dosya yükleme ve baskı başlatma — simülatörün /upload ucu ve WebSocket'iyle uçtan uca."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

KAYNAK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KAYNAK)); sys.path.insert(0, str(KAYNAK / "araclar"))

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage import k2_protokol as P  # noqa: E402
from creamanage import yukleme as Y  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.kullanicilar import KullaniciYonetimi  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import uygulama_olustur  # noqa: E402
from sahte_yazici import filo_kur  # noqa: E402

PORT = int(os.environ.get("CREAMANAGE_TEST_PORT", "19999"))


async def bekle(kosul, sn=8.0):
    son = asyncio.get_running_loop().time() + sn
    while asyncio.get_running_loop().time() < son:
        if kosul():
            return True
        await asyncio.sleep(0.05)
    return kosul()


class YardimciTesti(unittest.TestCase):
    def test_guvenli_ad(self):
        self.assertEqual(Y.guvenli_dosya_adi("../../Kapak Şablonu (v2) ğü.gcode"), "Kapak_Sablonu_(v2)_gu.gcode")
        self.assertEqual(Y.guvenli_dosya_adi("C:\\\\Users\\\\x\\\\parça.gcode"), "parca.gcode")
        self.assertEqual(Y.guvenli_dosya_adi(""), "dosya.gcode")
        self.assertTrue(Y.uzanti_izinli_mi("a.GCODE")); self.assertTrue(Y.uzanti_izinli_mi("a.gcode.gz"))
        self.assertFalse(Y.uzanti_izinli_mi("virus.exe"))
        self.assertEqual(Y.hedef_yol("", "a.gcode"), "/mnt/UDISK/printer_data/gcodes/a.gcode")
        self.assertEqual(Y.hedef_yol("/usr/data/printer_data/gcodes/", "a.gcode"), "/usr/data/printer_data/gcodes/a.gcode")

    def test_protokol(self):
        import json
        self.assertEqual(json.loads(P.komut_baski_baslat("/mnt/UDISK/printer_data/gcodes/a.gcode"))["params"],
                         {"opGcodeFile": "printprt:/mnt/UDISK/printer_data/gcodes/a.gcode"})
        self.assertEqual(P.dosya_dizini("/mnt/UDISK/printer_data/gcodes/a.gcode"), "/mnt/UDISK/printer_data/gcodes")
        self.assertEqual(P.dosya_dizini("a.gcode"), "")


class YuklemeTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sahte = await filo_kur(1, baslangic=2, port=PORT, hizli=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.filo = Filo(self.vt); await self.filo.baslat()
        self.client = TestClient(TestServer(uygulama_olustur(self.filo))); await self.client.start_server()
        KullaniciYonetimi(self.vt).ekle("yon", "Yön.", "yazici_yoneticisi", "testparola123")
        KullaniciYonetimi(self.vt).ekle("goz", "Göz.", "gozetmen", "testparola123")
        KullaniciYonetimi(self.vt).ekle("admin", "A", "sistem_yoneticisi", "testparola123")
        self.admin = TestClient(TestServer(self.client.server.app)); await self.admin.start_server(); self.addAsyncCleanup(self.admin.close)
        r = await self.admin.post("/api/giris", json={"kullanici_adi": "admin", "parola": "testparola123"}); assert r.status == 200
        r = await self.client.post("/api/giris", json={"kullanici_adi": "yon", "parola": "testparola123"}); assert r.status == 200
        self.gcode = Path(self.tmp.name) / "Kapak v2.gcode"
        self.gcode.write_bytes(b"; test gcode\nG28\n" * 5000)

    async def asyncTearDown(self):
        await self.client.close(); self.vt.kapat(); self.tmp.cleanup()
        for y in self.sahte:
            await y.durdur()

    async def test_bilgi_ve_dogrudan_yukleme(self):
        b = await Y.bilgi("127.0.0.2", PORT)
        self.assertEqual(b["model"], "F008"); self.assertEqual(b["model_adi"], "K2 Plus")
        s = await Y.dosya_yukle("127.0.0.2", "Kapak v2.gcode", self.gcode, port=PORT)
        self.assertEqual(s["dosya_adi"], "Kapak_v2.gcode"); self.assertEqual(s["port"], PORT)
        self.assertEqual(self.sahte[0].yuklenen_dosyalar[-1], ("Kapak_v2.gcode", self.gcode.stat().st_size))
        with self.assertRaises(RuntimeError):
            await Y.dosya_yukle("127.0.0.2", "x.gcode", self.gcode, port=PORT + 1, zaman_asimi=5)   # yanlış port, 80/4408 de kapalı

    async def test_api_yukle_ve_baslat(self):
        r = await self.admin.post("/api/yazicilar", json={"ad": "Y1", "ip": "127.0.0.2", "port": PORT, "http_port": PORT})
        yid = (await r.json())["yazici"]["id"]
        self.assertTrue(await bekle(lambda: self.filo.yazici_gorunum(yid)["canli"]["baglanti"] == "bagli"))
        # Yanlış uzantı reddedilir
        fd = aiohttp.FormData(); fd.add_field("file", b"x", filename="kotu.exe")
        r = await self.client.post(f"/api/yazicilar/{yid}/dosya", data=fd); self.assertEqual(r.status, 400)
        # Yükle + başlat
        fd = aiohttp.FormData(); fd.add_field("file", self.gcode.read_bytes(), filename="Kapak v2.gcode"); fd.add_field("baslat", "1")
        r = await self.client.post(f"/api/yazicilar/{yid}/dosya", data=fd)
        self.assertEqual(r.status, 201, await r.text())
        v = await r.json()
        self.assertEqual(v["dosya_adi"], "Kapak_v2.gcode"); self.assertTrue(v["baslatildi"])
        self.assertEqual(v["yol"], "/mnt/UDISK/printer_data/gcodes/Kapak_v2.gcode")
        self.assertIn({"opGcodeFile": "printprt:/mnt/UDISK/printer_data/gcodes/Kapak_v2.gcode"}, self.sahte[0].gelen_komutlar)
        self.assertTrue(await bekle(lambda: self.filo.yazici_gorunum(yid)["canli"]["dosya"] == "Kapak_v2.gcode"))
        self.assertEqual(self.filo.yazici_gorunum(yid)["canli"]["durum"], P.D_BASIYOR)
        # gcode dizini telemetriden öğrenildi; denetim ve olay kaydı var
        self.assertTrue(await bekle(lambda: self.vt.yazici(yid)["gcode_dizini"] == "/mnt/UDISK/printer_data/gcodes"))
        self.assertIn("dosya_yukledi", [g["eylem"] for g in self.vt.denetim_listesi()])
        self.assertIn("dosya_yuklendi", [o["tur"] for o in self.vt.olaylar(20, yid)])
        # Yalnız yükle, başlatma
        fd = aiohttp.FormData(); fd.add_field("file", b"G28\n", filename="b.gcode"); fd.add_field("baslat", "0")
        r = await self.client.post(f"/api/yazicilar/{yid}/dosya", data=fd); self.assertEqual(r.status, 201)
        self.assertFalse((await r.json())["baslatildi"])
        # Gözetmen yükleyemez
        goz = TestClient(TestServer(self.client.server.app)); await goz.start_server(); self.addAsyncCleanup(goz.close)
        await goz.post("/api/giris", json={"kullanici_adi": "goz", "parola": "testparola123"})
        fd = aiohttp.FormData(); fd.add_field("file", b"G28\n", filename="c.gcode")
        r = await goz.post(f"/api/yazicilar/{yid}/dosya", data=fd); self.assertEqual(r.status, 403)

    async def test_yazici_kapaliysa_502(self):
        r = await self.admin.post("/api/yazicilar", json={"ad": "Yok", "ip": "127.0.0.9", "port": PORT, "http_port": PORT})
        yid = (await r.json())["yazici"]["id"]
        fd = aiohttp.FormData(); fd.add_field("file", b"G28\n", filename="c.gcode")
        r = await self.client.post(f"/api/yazicilar/{yid}/dosya", data=fd); self.assertEqual(r.status, 502)
        self.assertIn("dosya_yukleme_hatasi", [g["eylem"] for g in self.vt.denetim_listesi()])


if __name__ == "__main__":
    unittest.main()
