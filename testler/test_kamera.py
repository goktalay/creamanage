"""Kamera: sunucu taraflı görüntü (PNG ve MJPEG akışından ilk kare), 404 → WebRTC bilgisi, denetim."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

KAYNAK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KAYNAK)); sys.path.insert(0, str(KAYNAK / "araclar"))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage import kamera as KAM  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.kullanicilar import KullaniciYonetimi  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import uygulama_olustur  # noqa: E402
from sahte_yazici import filo_kur  # noqa: E402

PORT = int(os.environ.get("CREAMANAGE_TEST_PORT", "19999"))


class KameraTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sahte = await filo_kur(1, baslangic=2, port=PORT, hizli=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.filo = Filo(self.vt); await self.filo.baslat()
        self.app = uygulama_olustur(self.filo)
        self.admin = TestClient(TestServer(self.app)); await self.admin.start_server()
        self.goz = TestClient(TestServer(self.app)); await self.goz.start_server()
        ky = KullaniciYonetimi(self.vt); ky.ekle("admin", "A", "sistem_yoneticisi", "testparola123"); ky.ekle("goz", "G", "gozetmen", "testparola123")
        await self.admin.post("/api/giris", json={"kullanici_adi": "admin", "parola": "testparola123"})
        await self.goz.post("/api/giris", json={"kullanici_adi": "goz", "parola": "testparola123"})
        r = await self.admin.post("/api/yazicilar", json={"ad": "Y1", "ip": "127.0.0.2", "port": PORT, "http_port": PORT})
        self.yid = (await r.json())["yazici"]["id"]

    async def asyncTearDown(self):
        await self.admin.close(); await self.goz.close(); self.vt.kapat(); self.tmp.cleanup()
        for y in self.sahte:
            await y.durdur()

    async def test_dogrudan_goruntu_al(self):
        veri, tur = await KAM.goruntu_al(f"http://127.0.0.2:{PORT}/snapshot")
        self.assertEqual(tur, "image/png"); self.assertTrue(veri.startswith(b"\x89PNG"))
        veri, tur = await KAM.goruntu_al(f"http://127.0.0.2:{PORT}/stream")
        self.assertEqual(tur, "image/jpeg"); self.assertTrue(veri.startswith(b"\xff\xd8")); self.assertTrue(veri.endswith(b"\xff\xd9"))
        with self.assertRaises(RuntimeError):
            await KAM.goruntu_al(f"http://127.0.0.2:{PORT}/info")          # JSON, görüntü değil

    async def test_api(self):
        # URL yokken 404 + WebRTC bilgisi (tarayıcı yolu)
        r = await self.goz.get(f"/api/yazicilar/{self.yid}/kamera"); self.assertEqual(r.status, 404)
        v = await r.json(); self.assertEqual(v["webrtc"], "http://127.0.0.2:8000/call/webrtc_local"); self.assertEqual(v["ip"], "127.0.0.2")
        # tarayıcı yolu kaydı (gözetmen de yazabilir)
        r = await self.goz.post(f"/api/yazicilar/{self.yid}/kamera/kayit", json={"basarili": True}); self.assertEqual(r.status, 200)
        # sunucu URL'si tanımlanınca görüntü sunucudan gelir (gözetmen görebilir)
        r = await self.admin.put(f"/api/yazicilar/{self.yid}", json={"kamera_url": f"http://127.0.0.2:{PORT}/snapshot"}); self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["yazici"]["kamera_url"], f"http://127.0.0.2:{PORT}/snapshot")
        r = await self.goz.get(f"/api/yazicilar/{self.yid}/kamera"); self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/png"); self.assertTrue((await r.read()).startswith(b"\x89PNG"))
        r = await self.goz.put(f"/api/yazicilar/{self.yid}", json={"kamera_url": "x"}); self.assertEqual(r.status, 403)   # ayar yalnız sistem yöneticisi
        # ulaşılamayan kaynak → 502
        await self.admin.put(f"/api/yazicilar/{self.yid}", json={"kamera_url": "http://127.0.0.2:1/yok"})
        r = await self.goz.get(f"/api/yazicilar/{self.yid}/kamera"); self.assertEqual(r.status, 502)
        eylemler = [g["eylem"] for g in self.vt.denetim_listesi()]
        self.assertIn("kamera_goruntu", eylemler); self.assertIn("kamera_goruntu_hatasi", eylemler)


if __name__ == "__main__":
    unittest.main()
