"""Kullanıcı sistemi: hash, roller, kurulum, giriş, oturum, yetki denetimi."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from creamanage import kullanicilar as K  # noqa: E402
from creamanage.filo import Filo  # noqa: E402
from creamanage.veritabani import Veritabani  # noqa: E402
from creamanage.web import gerekli_rol, uygulama_olustur  # noqa: E402

PAROLA = "X21mtm6@T45mn60@"


class HashTesti(unittest.TestCase):
    def test_hash_ve_dogrulama(self):
        h = K.parola_hashle(PAROLA)
        self.assertTrue(h.startswith("pbkdf2_sha256$"))
        self.assertNotIn(PAROLA, h)
        self.assertTrue(K.parola_dogrula(PAROLA, h))
        self.assertFalse(K.parola_dogrula(PAROLA + "x", h))
        self.assertFalse(K.parola_dogrula(PAROLA, "bozuk"))
        self.assertNotEqual(K.parola_hashle(PAROLA), h)   # tuz rastgele

    def test_gerekli_rol(self):
        self.assertEqual(gerekli_rol("GET", "/api/yazicilar"), "gozetmen")
        self.assertEqual(gerekli_rol("POST", "/api/yazicilar"), "yazici_yoneticisi")
        self.assertEqual(gerekli_rol("POST", "/api/yazicilar/3/komut"), "yazici_yoneticisi")
        self.assertEqual(gerekli_rol("PUT", "/api/ayarlar/telegram"), "sistem_yoneticisi")
        self.assertEqual(gerekli_rol("GET", "/api/ayarlar/telegram"), "sistem_yoneticisi")
        self.assertEqual(gerekli_rol("GET", "/api/kullanicilar"), "sistem_yoneticisi")
        self.assertEqual(gerekli_rol("DELETE", "/api/kullanicilar/2"), "sistem_yoneticisi")
        self.assertEqual(gerekli_rol("PUT", "/api/ben/parola"), "gozetmen")
        self.assertEqual(gerekli_rol("POST", "/api/cikis"), "gozetmen")


class YonetimTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.ky = K.KullaniciYonetimi(self.vt)

    def tearDown(self):
        self.vt.kapat(); self.tmp.cleanup()

    def test_ekle_giris_kilit(self):
        self.assertFalse(self.ky.kullanici_var_mi())
        k = self.ky.ekle("mkaderoglu", "Muhammed Kaderoğlu", "sistem_yoneticisi", PAROLA)
        self.assertEqual(k["rol_adi"], "Sistem Yöneticisi")
        with self.assertRaises(ValueError):
            self.ky.ekle("mkaderoglu", "", "gozetmen", PAROLA)        # aynı ad
        with self.assertRaises(ValueError):
            self.ky.ekle("MKADEROGLU", "", "gozetmen", PAROLA)        # büyük/küçük harf farkı yok
        with self.assertRaises(ValueError):
            self.ky.ekle("ali", "", "gozetmen", "kisa")                # parola kısa
        with self.assertRaises(ValueError):
            self.ky.ekle("a b", "", "gozetmen", PAROLA)                # geçersiz ad
        s = self.ky.giris("MKaderoglu", PAROLA, "1.2.3.4")
        self.assertEqual(s["kullanici"]["kullanici_adi"], "mkaderoglu")
        self.assertEqual(self.ky.oturum_kullanicisi(s["token"])["id"], k["id"])
        self.assertIsNone(self.ky.oturum_kullanicisi("yok"))
        for _ in range(5):
            with self.assertRaises(ValueError):
                self.ky.giris("mkaderoglu", "yanlis", "1.2.3.4")
        with self.assertRaisesRegex(ValueError, "bekleyin"):
            self.ky.giris("mkaderoglu", PAROLA, "1.2.3.4")           # kilitli
        self.ky.giris("mkaderoglu", PAROLA, "5.6.7.8")                # başka IP'den serbest
        self.ky.cikis(s["token"])
        self.assertIsNone(self.ky.oturum_kullanicisi(s["token"]))

    def test_son_yonetici_korunur(self):
        a = self.ky.ekle("admin", "", "sistem_yoneticisi", PAROLA)
        with self.assertRaises(ValueError):
            self.ky.sil(a["id"])
        with self.assertRaises(ValueError):
            self.ky.guncelle(a["id"], rol="gozetmen")
        with self.assertRaises(ValueError):
            self.ky.guncelle(a["id"], etkin=False)
        b = self.ky.ekle("admin2", "", "sistem_yoneticisi", PAROLA)
        self.ky.guncelle(a["id"], rol="gozetmen")                     # artık ikinci yönetici var
        self.ky.sil(b["id"]) if False else None
        with self.assertRaises(ValueError):
            self.ky.sil(b["id"])                                      # b son yönetici kaldı

    def test_parola_degistir_oturum_dusurur(self):
        k = self.ky.ekle("ali", "Ali", "gozetmen", PAROLA)
        s1 = self.ky.giris("ali", PAROLA); s2 = self.ky.giris("ali", PAROLA)
        with self.assertRaises(ValueError):
            self.ky.parola_degistir(k["id"], "yanlis", "yeniparola123")
        self.ky.parola_degistir(k["id"], PAROLA, "yeniparola123", haric_token=s1["token"])
        self.assertIsNotNone(self.ky.oturum_kullanicisi(s1["token"]))   # kendi oturumu kalır
        self.assertIsNone(self.ky.oturum_kullanicisi(s2["token"]))      # diğerleri düşer
        self.ky.guncelle(k["id"], etkin=False)
        self.assertIsNone(self.ky.oturum_kullanicisi(s1["token"]))      # pasif → düşer
        with self.assertRaises(ValueError):
            self.ky.giris("ali", "yeniparola123")


class ApiTesti(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vt = Veritabani(Path(self.tmp.name) / "t.sqlite")
        self.ky = K.KullaniciYonetimi(self.vt)
        self.filo = Filo(self.vt)
        await self.filo.baslat()
        self.app = uygulama_olustur(self.filo, None, self.ky)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close(); self.vt.kapat(); self.tmp.cleanup()

    async def istemci(self):
        c = TestClient(TestServer(self.app)); await c.start_server(); self.addAsyncCleanup(c.close); return c

    async def test_kurulum_ve_giris_akisi(self):
        # Kullanıcı yokken korumalı uçlar 401, sayfa /giris'e yönlenir
        r = await self.client.get("/api/yazicilar"); self.assertEqual(r.status, 401)
        r = await self.client.get("/", allow_redirects=False); self.assertEqual(r.status, 302); self.assertEqual(r.headers["Location"], "/giris")
        r = await self.client.get("/giris"); self.assertEqual(r.status, 200); self.assertIn("İlk kurulum", await r.text())
        r = await self.client.get("/api/kurulum"); self.assertTrue((await r.json())["kurulum_gerekli"])
        # İlk yönetici
        r = await self.client.post("/api/kurulum", json={"kullanici_adi": "mkaderoglu", "ad": "Muhammed Kaderoğlu", "parola": PAROLA})
        self.assertEqual(r.status, 201)
        self.assertEqual((await r.json())["kullanici"]["rol"], "sistem_yoneticisi")
        self.assertIn(K.CEREZ_ADI, r.cookies)
        r = await self.client.post("/api/kurulum", json={"kullanici_adi": "x", "parola": PAROLA}); self.assertEqual(r.status, 409)
        # Çerezle erişim
        r = await self.client.get("/api/ben"); self.assertEqual((await r.json())["kullanici"]["kullanici_adi"], "mkaderoglu")
        r = await self.client.get("/api/yazicilar"); self.assertEqual(r.status, 200)
        r = await self.client.get("/giris", allow_redirects=False); self.assertEqual(r.status, 302)   # girişliyken ana sayfaya
        ws = await self.client.ws_connect("/ws"); ilk = await ws.receive_json(); self.assertEqual(ilk["kullanici"]["rol"], "sistem_yoneticisi"); await ws.close()
        # Çıkış
        r = await self.client.post("/api/cikis"); self.assertEqual(r.status, 200)
        r = await self.client.get("/api/ben"); self.assertEqual(r.status, 401)
        # Yanlış parola 401, doğru 200
        r = await self.client.post("/api/giris", json={"kullanici_adi": "mkaderoglu", "parola": "yanlis"}); self.assertEqual(r.status, 401)
        r = await self.client.post("/api/giris", json={"kullanici_adi": "mkaderoglu", "parola": PAROLA}); self.assertEqual(r.status, 200)

    async def test_roller_uclarda_uygulanir(self):
        self.ky.ekle("admin", "", "sistem_yoneticisi", PAROLA)
        self.ky.ekle("yyon", "Yazıcı Yön.", "yazici_yoneticisi", PAROLA)
        self.ky.ekle("goz", "Gözetmen", "gozetmen", PAROLA)
        admin, yy, goz = self.client, await self.istemci(), await self.istemci()
        for c, ad in ((admin, "admin"), (yy, "yyon"), (goz, "goz")):
            r = await c.post("/api/giris", json={"kullanici_adi": ad, "parola": PAROLA}); self.assertEqual(r.status, 200)
        # Gözetmen: okur ama değiştiremez
        r = await goz.get("/api/yazicilar"); self.assertEqual(r.status, 200)
        r = await goz.post("/api/yazicilar", json={"ad": "x", "ip": "127.0.0.9"}); self.assertEqual(r.status, 403)
        r = await goz.post("/api/tarama", json={"cidr": "127.0.0.0/30"}); self.assertEqual(r.status, 403)
        r = await goz.get("/api/ayarlar/telegram"); self.assertEqual(r.status, 403)   # bildirim ayarları yalnız sistem yöneticisi
        r = await yy.get("/api/ayarlar/telegram"); self.assertEqual(r.status, 403)
        r = await goz.get("/api/kullanicilar"); self.assertEqual(r.status, 403)
        ws = await goz.ws_connect("/ws"); self.assertEqual((await ws.receive_json())["tur"], "anlik"); await ws.close()
        # Yazıcı yöneticisi: yazıcı işleri serbest, kullanıcı yönetimi yasak
        r = await yy.post("/api/yazicilar", json={"ad": "Y", "ip": "127.0.0.9"}); self.assertEqual(r.status, 201)
        yid = (await r.json())["yazici"]["id"]
        r = await yy.post(f"/api/yazicilar/{yid}/komut", json={"komut": "isik", "deger": 1}); self.assertEqual(r.status, 200)
        r = await yy.get("/api/kullanicilar"); self.assertEqual(r.status, 403)
        r = await yy.post("/api/kullanicilar", json={"kullanici_adi": "z", "rol": "gozetmen", "parola": PAROLA}); self.assertEqual(r.status, 403)
        r = await goz.delete(f"/api/yazicilar/{yid}"); self.assertEqual(r.status, 403)
        r = await yy.delete(f"/api/yazicilar/{yid}"); self.assertEqual(r.status, 200)
        # Sistem yöneticisi: kullanıcı yönetimi
        r = await admin.get("/api/kullanicilar"); v = await r.json(); self.assertEqual(len(v["kullanicilar"]), 3)
        goz_id = next(k["id"] for k in v["kullanicilar"] if k["kullanici_adi"] == "goz")
        admin_id = next(k["id"] for k in v["kullanicilar"] if k["kullanici_adi"] == "admin")
        r = await admin.post("/api/kullanicilar", json={"kullanici_adi": "yeni", "ad": "Yeni", "rol": "gozetmen", "parola": PAROLA}); self.assertEqual(r.status, 201)
        r = await admin.post("/api/kullanicilar", json={"kullanici_adi": "yeni", "rol": "gozetmen", "parola": PAROLA}); self.assertEqual(r.status, 400)
        r = await admin.put(f"/api/kullanicilar/{goz_id}", json={"rol": "yazici_yoneticisi", "ad": "Terfi"}); self.assertEqual(r.status, 200)
        r = await goz.post("/api/yazicilar", json={"ad": "x", "ip": "127.0.0.8"}); self.assertEqual(r.status, 201)   # terfi anında geçerli
        r = await admin.put(f"/api/kullanicilar/{admin_id}", json={"rol": "gozetmen"}); self.assertEqual(r.status, 400)  # kendi rolü
        r = await admin.delete(f"/api/kullanicilar/{admin_id}"); self.assertEqual(r.status, 400)                          # kendini silme
        r = await admin.put(f"/api/kullanicilar/{goz_id}", json={"etkin": False}); self.assertEqual(r.status, 200)
        r = await goz.get("/api/ben"); self.assertEqual(r.status, 401)      # pasif → oturum düştü
        r = await admin.delete(f"/api/kullanicilar/{goz_id}"); self.assertEqual(r.status, 200)
        # Kendi parolasını değiştirme (her rol)
        r = await yy.put("/api/ben/parola", json={"eski": "yanlis", "yeni": "yenip4rola!"}); self.assertEqual(r.status, 400)
        r = await yy.put("/api/ben/parola", json={"eski": PAROLA, "yeni": "yenip4rola!"}); self.assertEqual(r.status, 200)
        r = await yy.get("/api/ben"); self.assertEqual(r.status, 200)       # kendi oturumu korunur
        # Tercihler (tema) kullanıcıya bağlı saklanır; gözetmen dahil herkes kendi tercihini yazar
        r = await goz2.put("/api/ben/tercihler", json={"tema": "koyu"}) if False else await admin.put("/api/ben/tercihler", json={"tema": "koyu"})
        self.assertEqual(r.status, 200); self.assertEqual((await r.json())["tercihler"]["tema"], "koyu")
        r = await admin.get("/api/ben"); self.assertEqual((await r.json())["kullanici"]["tercihler"]["tema"], "koyu")
        r = await admin.put("/api/ben/tercihler", json={"tema": "mor"}); self.assertEqual(r.status, 400)
        r = await admin.put("/api/ben/tercihler", json={"parola_hash": "x"}); self.assertEqual(r.status, 400)
        r = await yy.get("/api/ben"); self.assertNotIn("tema", (await r.json())["kullanici"]["tercihler"])   # başka kullanıcıyı etkilemez
        # Denetim kaydı: yazıcı yöneticisinin geçmişi
        yy_id = next(k["id"] for k in v["kullanicilar"] if k["kullanici_adi"] == "yyon")
        r = await admin.get(f"/api/kullanicilar/{yy_id}/gecmis"); self.assertEqual(r.status, 200)
        eylemler = [g["eylem"] for g in (await r.json())["gecmis"]]
        for e in ("giris", "yazici_ekledi", "komut_isik", "yazici_sildi", "parola_degistirdi"):
            self.assertIn(e, eylemler, eylemler)
        komut = next(g for g in (await r.json())["gecmis"] if g["eylem"] == "komut_isik")
        self.assertIn("127.0.0.9", komut["hedef"])
        r = await yy.get(f"/api/kullanicilar/{yy_id}/gecmis"); self.assertEqual(r.status, 403)   # yalnız sistem yöneticisi
        r = await admin.get("/api/kullanicilar/gecmis"); self.assertGreater(len((await r.json())["gecmis"]), 5)
        # Başarısız giriş de kullanıcı adına yazılır
        r = await admin.post("/api/giris", json={"kullanici_adi": "yyon", "parola": "yanlis"}); self.assertEqual(r.status, 401)
        r = await admin.get(f"/api/kullanicilar/{yy_id}/gecmis")
        self.assertIn("giris_basarisiz", [g["eylem"] for g in (await r.json())["gecmis"]])


if __name__ == "__main__":
    unittest.main()
