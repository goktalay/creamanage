"""Yazıcı başına SQLite telemetri kaydı ve API uçları."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

KAYNAK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KAYNAK)); sys.path.insert(0, str(KAYNAK / "araclar"))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage import k2_protokol as P  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.kullanicilar import KullaniciYonetimi  # noqa: E402
from creamanage.telemetri_kayit import TelemetriKayit  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import uygulama_olustur  # noqa: E402
from sahte_yazici import filo_kur  # noqa: E402

PORT = int(os.environ.get("CREAMANAGE_TEST_PORT", "19999"))


class KayitTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = TelemetriKayit(Path(self.tmp.name) / "tel", saklama_gun=1)

    def tearDown(self):
        self.t.kapat(); self.tmp.cleanup()

    def test_ornek_yalniz_degisince_yazilir(self):
        o = {"durum": "basiyor", "baglanti": "bagli", "nozul": 200.0, "ilerleme": 10, "dosya": "a.gcode", "hata_kodu": 0}
        self.assertTrue(self.t.ornekle(7, o, {"ip": "10.0.0.7"}, zaman=1000.0))
        self.assertFalse(self.t.ornekle(7, o, {"ip": "10.0.0.7"}, zaman=1001.0))     # aynı → yazılmaz
        o2 = dict(o, nozul=201.0)
        self.assertTrue(self.t.ornekle(7, o2, {"ip": "10.0.0.7"}, zaman=1002.0))
        self.assertTrue(self.t.dosya_yolu(7).exists())
        orn = self.t.ornekler(7)
        self.assertEqual(len(orn), 2); self.assertEqual(orn[0]["nozul"], 201.0); self.assertEqual(orn[0]["dosya"], "a.gcode")
        ilk = self.t.degisimler(7)                            # yeni dosyada ilk değerler "None → x" olarak yazılır
        self.assertIn(("baglanti", None, "bagli"), [(d["alan"], d["eski"], d["yeni"]) for d in ilk])

    def test_degisimler_ve_hatalar(self):
        temel = {"durum": "bosta", "baglanti": "bagli", "hata_kodu": 0, "dosya": "", "filament_yok": False, "son_hata": ""}
        self.t.ornekle(3, temel, {"ip": "10.0.0.3"}, zaman=1.0)
        self.t.ornekle(3, dict(temel, durum="basiyor", dosya="x.gcode"), {"ip": "10.0.0.3"}, zaman=2.0)
        self.t.ornekle(3, dict(temel, durum="hata", dosya="x.gcode", hata_kodu=500, hata_anahtari="2718"), {"ip": "10.0.0.3"}, zaman=3.0)
        self.t.ornekle(3, dict(temel, durum="basiyor", dosya="x.gcode"), {"ip": "10.0.0.3"}, zaman=4.0)
        self.t.ornekle(3, dict(temel, durum="cevrimdisi", baglanti="kopuk", dosya="x.gcode", son_hata="timeout"), {"ip": "10.0.0.99"}, zaman=5.0)
        d = self.t.degisimler(3)
        alanlar = [(x["alan"], x["eski"], x["yeni"]) for x in d]
        self.assertIn(("durum", "bosta", "basiyor"), alanlar)
        self.assertIn(("hata_kodu", "0", "500"), alanlar)
        self.assertIn(("baglanti", "bagli", "kopuk"), alanlar)
        self.assertIn(("ip", "10.0.0.3", "10.0.0.99"), alanlar)
        self.assertIn(("dosya", "", "x.gcode"), alanlar)
        h = self.t.hatalar(3)
        self.assertEqual([(x["yeni"], x["basladi"]) for x in h], [("0", False), ("500", True), ("0", False)])
        self.assertEqual(h[1]["baglam"], "2718")
        kopus = next(x for x in d if x["alan"] == "baglanti"); self.assertEqual(kopus["baglam"], "timeout")

    def test_temizlik_ve_seyreltme(self):
        for i in range(120):
            self.t.ornekle(1, {"durum": "basiyor", "baglanti": "bagli", "nozul": 200 + i, "hata_kodu": 0}, None, zaman=1_000_000 + i)
        self.assertEqual(len(self.t.ornekler(1, limit=1000)), 120)
        self.assertLessEqual(len(self.t.ornekler(1, limit=1000, adim_sn=60)), 3)  # dakikada bir (120 sn → en çok 3 kova)
        self.assertEqual(len(self.t.ornekler(1, baslangic=1_000_100, limit=1000)), 20)
        self.t.temizle(simdi=1_000_000 + 86400 + 60)                              # 1 gün saklama → ilk 60 sn gider
        self.assertEqual(len(self.t.ornekler(1, limit=1000)), 60)
        oz = self.t.ozet(1); self.assertEqual(oz["ornek"], 60); self.assertGreater(oz["boyut"], 0)

    def test_yeniden_acinca_dosya_korunur(self):
        self.t.ornekle(5, {"durum": "bosta", "baglanti": "bagli", "hata_kodu": 0}, None, zaman=10.0)
        self.t.kapat()
        t2 = TelemetriKayit(Path(self.tmp.name) / "tel")
        self.assertEqual(len(t2.ornekler(5)), 1)
        # yeniden açınca son değerler yüklenir; aynı özet yeni değişim satırı üretmez
        onceki = len(t2.degisimler(5))
        t2.ornekle(5, {"durum": "bosta", "baglanti": "bagli", "hata_kodu": 0}, None, zaman=11.0)
        self.assertEqual(len(t2.degisimler(5)), onceki); t2.kapat()


class UctanUcaTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sahte = await filo_kur(1, baslangic=2, port=PORT, hizli=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.tel = TelemetriKayit(Path(self.tmp.name) / "tel", aralik_sn=0.1)
        self.filo = Filo(self.vt, self.tel); await self.filo.baslat()
        self.client = TestClient(TestServer(uygulama_olustur(self.filo))); await self.client.start_server()
        KullaniciYonetimi(self.vt).ekle("admin", "T", "sistem_yoneticisi", "testparola123")
        await self.client.post("/api/giris", json={"kullanici_adi": "admin", "parola": "testparola123"})

    async def asyncTearDown(self):
        await self.client.close(); self.vt.kapat(); self.tmp.cleanup()
        for y in self.sahte:
            await y.durdur()

    async def test_canli_kayit_ve_api(self):
        self.sahte[0].baski_baslat("kapak.gcode", katman=20)
        r = await self.client.post("/api/yazicilar", json={"ad": "Y1", "ip": "127.0.0.2", "port": PORT})
        yid = (await r.json())["yazici"]["id"]
        await asyncio.sleep(1.5)
        r = await self.client.get(f"/api/yazicilar/{yid}/telemetri?limit=50"); v = await r.json()
        self.assertGreater(len(v["ornekler"]), 3, v)
        self.assertEqual(v["ornekler"][0]["dosya"], "kapak.gcode"); self.assertGreater(v["ozet"]["ornek"], 3)
        r = await self.client.get(f"/api/yazicilar/{yid}/degisimler"); d = (await r.json())["degisimler"]
        self.assertTrue(any(x["alan"] == "baglanti" and x["yeni"] == "bagli" for x in d), d)
        r = await self.client.get(f"/api/yazicilar/{yid}/hatalar"); self.assertEqual(r.status, 200)
        self.assertTrue(self.tel.dosya_yolu(yid).exists())
        # özet: model adı ve yazılım sürümü
        g = self.filo.yazici_gorunum(yid)["canli"]
        self.assertEqual(g["model_adi"], "K2 Plus")
        # silinince dosya kapanır ama kalır
        await self.client.delete(f"/api/yazicilar/{yid}")
        self.assertNotIn(yid, self.tel.kayitlar)


class ProtokolEkTesti(unittest.TestCase):
    def test_model_ve_surum(self):
        self.assertEqual(P.model_adi("F008"), "K2 Plus"); self.assertEqual(P.model_adi("K2 Plus"), "K2 Plus")
        self.assertEqual(P.yazilim_surumu("printer hw ver:;printer sw ver:;DWIN hw ver:CR0CN240110C10;DWIN sw ver:1.1.6.4;"), "1.1.6.4")
        self.assertEqual(P.yazilim_surumu("printer sw ver:1.2.0;DWIN sw ver:1.1.6.4;"), "1.2.0")
        self.assertEqual(P.yazilim_surumu("V1.2.3.4"), "V1.2.3.4")
        o = P.ozet({"model": "F008", "modelVersion": "DWIN sw ver:1.1.6.4;"})
        self.assertEqual((o["model_adi"], o["yazilim_surumu"]), ("K2 Plus", "1.1.6.4"))


if __name__ == "__main__":
    unittest.main()
