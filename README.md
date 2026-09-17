# CreaManage

Creality **K2 Plus (Combo)** 3D yazıcı filosunu (hedef: 56 cihaz) yerel ağ üzerinden
**tek merkezden izleyen** web tabanlı yazılım. **Gökkubbe Teknoloji Anonim Şirketi.**

Yazıcılara müdahale gerekmez: stok Creality yazılımının yerel ağda sunduğu
**WebSocket 9999** arayüzü kullanılır (root, Moonraker, bulut yok). Garanti korunur.

## Sürüm 0.8.0 — ne yapar

- **Kullanıcı girişi ve roller:** herkes kullanıcı adı ve parola ile girer. Üç rol:
  **Sistem Yöneticisi** (her şey: yazıcı ekleme/silme/ayarları, ağ tarama, kullanıcılar,
  işlem geçmişi, bildirim ayarları, hata kodu tablosu), **Yazıcı Yöneticisi** (komutlar,
  dosya yükleme ve yazdırma), **Gözetmen** (yalnız izler). Rol denetimi her API ucunda
  sunucu tarafında yapılır; arayüz yalnız yetkili düğmeleri gösterir.
- **İşlem geçmişi (denetim kaydı):** her kullanıcının yaptığı her değişiklik kaydedilir:
  giriş/çıkış/başarısız giriş, komutlar (durdur/başlat/iptal; hangi yazıcı, hangi dosya),
  dosya yükleme (ad, boyut, başlatıldı mı, hata), yazıcı ekleme/silme/güncelleme, tarama
  başlat/iptal, bildirim ayarı ve testi, kullanıcı işlemleri, parola değişikliği; zaman ve
  IP ile. Sistem yöneticisi kullanıcı başına ya da tümünü görüntüler.
- **Dosya yükleme ve yazdırma ("Yükle" görünümü):** her yazıcı bir kart; ortadaki büyük
  dosya adına tıklayınca G-code seçilir, "mevcut işlemi durduracak" uyarısı onaylanınca dosya
  yazıcıya HTTP ile yüklenir ve baskı başlatılır. İlerleme kartta görünür. Gözetmen yalnız
  dosya adını görür.
- **Ağ tarama sihirbazı:** makinedeki alt ağları listeler, seçilen CIDR'da 9999 portunu
  paralel yoklar, yanıt verenlere WebSocket ile kimlik (hostname, model) sorar; bulunanları
  ad ve grup vererek toplu ekler. Elle IP ile ekleme de vardır.
- **Arayüz düzeni:** sabit üst çubuk (logo, modül menüsü, kullanıcı avatarı), ortada
  kaydırılan modül alanı, sabit alt çubukta durum sayaçları. Modüller: Yazıcılar (kartlar),
  Dosya Listesi (satırlar), Dosya Yöneticisi (yükle ve yazdır), Olaylar; sistem yöneticisine
  ek olarak Bildirimler ve Kullanıcılar.
- **Telemetri kaydı (yazıcı başına SQLite):** her yazıcı için ayrı dosya
  (`<veritabanı>_telemetri/yazici_<id>.sqlite`). Saniyede bir örnek alınır, yalnız değişen
  saniyeler yazılır; durum, bağlantı, hata, dosya ve IP değişimleri ayrıca eski→yeni olarak
  kaydedilir. Varsayılan saklama 30 gün (`--telemetri-gun`). Ayrıntı penceresinde Geçmiş
  modülünden aralık/çözünürlük seçilir, CSV indirilir.
- **Yazıcı ayrıntısı:** sabit başlık (ad, IP; modül menüsü ve Kapat), ortada kaydırılan
  modül, alt bilgi çubuğu. Modüller: Durum Bilgisi, İşlemler (yazıcı yöneticisi), Yazıcı
  Hataları, Geçmiş, Yazıcı Ayarları (yalnız sistem yöneticisi: IP/portlar/grup/silme).
- **Hata kodları anlamlı metinle (Türkçe):** `creamanage/veri/hata_kodlari.json` tablosunda
  Creality'nin K2 Plus hata kodu özeti (kontrolör, devre kartı, alet kiti, sistem, AI, CFS;
  80 kod) Türkçe başlık ve çözümle bulunur. Yazıcının `err.key` alanı (asıl kod, ör. 2586 =
  CY2586) tabloda aranır; `err.errcode` yalnız sınıftır (500 kritik, 208 uyarı…). Yeni kodlar
  için `python3 araclar/hata_kodlari_al.py --url/--csv/--html` ile tablo genişletilir.
- **Sistem dışı müdahale = MAJÖR olay:** baskı, CreaManage üzerinden komut verilmeden
  (yazıcı ekranından) durdurulur ya da iptal edilirse `dis_mudahale` olayı üretilir; yalnız
  sistem yöneticileri görür ve Telegram'da yalnız "yönetici kanalı" sohbetlerine gider.
- **Kamera modülü:** ayrıntı penceresinde "Görüntü Al" / "Yenile" ile yazıcı kamerasından
  tek kare. K2 ailesinde stok yazılım JPEG ucu sunmadığı için kare, tarayıcıdan yazıcının
  `:8000/call/webrtc_local` ucuna WebRTC ile bağlanılarak alınır (bilgisayar yazıcıyla aynı
  ağda olmalı, sayfa HTTP ile açılmalı). İsteğe bağlı sunucu taraflı kaynak: Yazıcı
  Ayarları'nda "Kamera görüntü URL'si" (go2rtc `api/frame.jpeg` ya da K1 MJPEG
  `?action=snapshot`/`stream`); tanımlıysa görüntü sunucudan gelir, uzaktan da çalışır.
  Her görüntü alma işlem geçmişine yazılır. PNG indirilebilir.
- **Geçmiş grafikleri:** ayrıntı penceresinde sıcaklık (nozul, tabla, kabin ve hedefleri) ve
  ilerleme grafikleri; ayrı eksenli iki grafik, kesişim çizgili ipucu, klavye ile gezinme,
  açık/koyu tema için doğrulanmış renkler; altındaki tablo ve CSV aynı veriyi verir.
- **Hata kodu tablosu yönetimi (sistem yöneticisi):** "Hata Kodları" modülünde arama,
  düzenleme, ekleme, silme; CSV/JSON/HTML dosyasından içe aktarma.
- **Yenileme aralığı:** alt çubukta 1 sn / 3 sn / 5 sn / 10 sn / 1 dk; yazıcı ekranları
  seçilen aralıkta yenilenir, tercih kullanıcı hesabına kaydedilir.
- **Gece / gündüz teması:** üst çubuktaki güneş/ay düğmesiyle; tercih kullanıcı hesabına
  kaydedilir (her cihazda aynı), seçilmemişse işletim sistemi teması izlenir.
- **Yazıcı ayrıntısı:** ikonlu bilgi kartları (dosya, ilerleme, süreler, sıcaklıklar, fan,
  hız, ışık, CFS, bağlantı, hata, model, grup), ikonlu komut çubuğu, ayarlar ve son olaylar.
- **Canlı gösterge paneli:** her yazıcı için durum (basıyor / boşta / duraklatıldı /
  tamamlandı / hata / hazırlanıyor / çevrimdışı), dosya, ilerleme, katman, kalan süre,
  nozul/tabla/kabin sıcaklıkları. Durum sayaçları, arama, durum ve grup filtresi.
- **Ayrıntı paneli:** tüm alanlar, yazıcıya özel olay geçmişi, düzenleme (ad, IP, port,
  grup, not, bağlantı etkin/kapalı), silme.
- **Komutlar:** Durdur (duraklat), Başlat (sürdür), İptal Et, ışık aç/kapat; duruma göre
  yalnız anlamlı olanlar etkin. Gözetmen komut veremez. (API'de ayrıca nozul, tabla, fan.)
- **Olay akışı:** bağlantı kuruldu/koptu, baskı başladı/bitti/duraklatıldı, hata,
  filament bitti. SQLite'a yazılır, arayüze anlık itilir.
- **Telegram bildirimleri:** hata oluştuğunda ve baskı tamamlandığında (isteğe bağlı:
  filament bitti, bağlantı koptu/kuruldu, hata giderildi, duraklatıldı, başladı) seçilen
  kişi ya da gruplara mesaj. Aynı anda oluşan olaylar tek mesajda toplanır.
- **Kalıcı kayıt:** `creamanage.sqlite` (yazıcılar + olaylar + ayarlar). Depoya girmez.

## Ubuntu'da servis olarak kurulum (önerilen)

```bash
git clone https://github.com/goktalay/creamanage.git
cd creamanage
sudo bash kurulum/ubuntu_kur.sh
```

Betik `creamanage` sistem kullanıcısını açar, kodu `/opt/creamanage` altına kurar (sanal ortam
ile), veriyi `/var/lib/creamanage` (SQLite, telemetri, hata kodu tablosu) altında tutar, ayarları
`/etc/creamanage/creamanage.env` dosyasına yazar ve `creamanage` systemd servisini açılışta
başlayacak şekilde etkinleştirir. Yeniden çalıştırmak güvenlidir.

| İşlem | Komut |
|---|---|
| Durum / günlük | `systemctl status creamanage` · `journalctl -u creamanage -f` |
| Yeniden başlat | `sudo systemctl restart creamanage` |
| Güncelle | `sudo bash /opt/creamanage/kurulum/guncelle.sh` |
| Port / ayar değiştir | `/etc/creamanage/creamanage.env` düzenle, sonra restart |
| Parola sıfırla | `sudo -u creamanage /opt/creamanage/venv/bin/python /opt/creamanage/araclar/kullanici.py --veritabani /var/lib/creamanage/creamanage.sqlite parola mkaderoglu` |
| Yedek | `/var/lib/creamanage` dizinini kopyalayın (servis çalışırken de alınabilir, WAL modu) |

Güvenlik duvarı: `sudo ufw allow 8090/tcp`. Ağ dışından erişim için önüne HTTPS ters vekil
(nginx/caddy) koyun; kamera modülünün tarayıcı WebRTC yolu yalnız HTTP sayfada çalışır, HTTPS
kullanılıyorsa sunucu taraflı kamera URL'si (go2rtc) tanımlayın.

## Elle çalıştırma (geliştirme)

Gereksinim: Python ≥ 3.11 ve `aiohttp` (tek bağımlılık). Windows ve Linux'ta çalışır.

```bash
git clone https://github.com/goktalay/creamanage.git
cd creamanage
pip3 install -r requirements.txt
python3 main.py --port 8090          # http://<sunucu>:8090/
```

İlk açılışta `/giris` sayfası, sistemde kullanıcı olmadığı için **ilk Sistem Yöneticisi**
hesabını oluşturmanızı ister (parola koda ya da depoya yazılmaz). Sonraki kullanıcılar
arayüzdeki **Kullanıcılar** penceresinden eklenir. Parola unutulursa sunucuda:

```bash
python3 araclar/kullanici.py listele
python3 araclar/kullanici.py parola <kullanici_adi>
python3 araclar/kullanici.py ekle <kullanici_adi> --ad "Ad Soyad" --rol sistem_yoneticisi
```

Parolalar PBKDF2-HMAC-SHA256 ile hash'lenir; oturumlar sunucuda tutulur (12 saat
kullanılmazsa düşer), tarayıcıya yalnız HttpOnly çerez verilir. 5 başarısız girişte
60 sn kilit. Ağ dışından erişim açılacaksa HTTPS (ters vekil) önerilir.

Ortam değişkenleri: `CREAMANAGE_HOST`, `CREAMANAGE_PORT`, `CREAMANAGE_VERITABANI`,
`CREAMANAGE_TELEMETRI`, `CREAMANAGE_TELEMETRI_GUN`, `CREAMANAGE_HATA_KODLARI`, `CREAMANAGE_LOG`. Komut satırı: `--host`, `--port`, `--veritabani`, `--log`.

Sunucu, yazıcılarla **aynı yerel ağda** (ya da 9999 portuna yönlendirilmiş bir ağda)
olmalıdır. Tarama için alt ağ en fazla /20 (4096 adres) olabilir.

### Telegram bildirimlerini açma

1. Telegram'da **@BotFather**'a `/newbot` yazın, bot adı verin; verdiği belirteci
   (`123456789:AA…`) kopyalayın.
2. Bildirim alacak kişi bota bir kez `/start` yazsın. Grup için botu gruba ekleyin ve
   grupta bir mesaj yazın.
3. CreaManage'de uygulama menüsünden **Bildirimler** (sistem yöneticisi) → belirteci yapıştırın → **Sohbetleri Bul** →
   listeden kişiyi/grubu işaretleyin → hangi olaylarda bildirim istediğinizi seçin →
   **Telegram bildirimleri etkin** → **Kaydet**. **Test Mesajı Gönder** ile doğrulayın.

"Sohbetleri Bul" sonuç vermezse sunucuda tanı aracını çalıştırın; internet, belirteç,
webhook ve bota gelen mesajları adım adım gösterir, sohbet kimliğini yazdırır:

```bash
python3 araclar/telegram_tani.py <BOT_BELIRTECI>
python3 araclar/telegram_tani.py <BOT_BELIRTECI> --gonder <SOHBET_ID>   # test mesajı
```

Belirteç yalnız sunucudaki `creamanage.sqlite` içinde tutulur; arayüze maskelenmiş döner.
Sunucunun `api.telegram.org` adresine internet erişimi olmalıdır (yazıcı ağı kapalıysa
sunucuya ikinci bir ağ bağlantısı ya da vekil gerekir).

### Donanımsız deneme (simülatör)

```bash
python3 araclar/sahte_yazici.py --adet 6      # 127.0.0.2 … 127.0.0.7 : 9999  (--hizli: baskı saniyeler içinde biter)
python3 main.py --port 8090
# Arayüzde "Yazıcı Ekle" → CIDR 127.0.0.0/28 → Tara
```

Simülatör telemetri, kalp atışı ve `pause/stop/lightSw` komutlarını taklit eder.

### Testler

```bash
cd testler
python3 -m unittest -v test_kamera test_telemetri test_mudahale test_yukleme test_kullanicilar test_k2_protokol test_filo_uctan_uca test_telegram
```

Telegram testleri sahte bir Telegram API sunucusuyla çalışır, internet gerekmez.
Çalışan sunucuyu sahte API'ye yönlendirmek için `CREAMANAGE_TELEGRAM_API=http://…`.

Uçtan uca test gerçek loopback soketleriyle sahte yazıcı kurar; 9999 doluysa
`CREAMANAGE_TEST_PORT` ile port değiştirilebilir.

## Mimari

```
main.py                 giriş noktası
creamanage/
  surum.py         sürüm, ürün adı, firma
  ayarlar.py       komut satırı / ortam değişkenleri
  k2_protokol.py   saf protokol: mesaj üretimi, çözümleme, durum türetme, özet  (G/Ç yok)
  k2_baglanti.py   yazıcı başına kalıcı WebSocket istemcisi, kalp atışı, yeniden bağlanma
  tarayici.py      alt ağ listesi, paralel port yoklama, kimlik sorgusu, Tarama işi
  veritabani.py    SQLite: yazicilar, olaylar
  olaylar.py       durum geçişi → olay; abone modeli (uyarı kanalları buraya takılır)
  filo.py          kayıt + bağlantı + tarama + olay orkestrasyonu, arayüz yayını (≤1/s/yazıcı)
  kullanicilar.py  roller, parola hash'i, oturumlar, giriş kilidi
  web.py           aiohttp: kimlik/rol ara katmanı, statik arayüz, REST API, /ws yayını
  yukleme.py       HTTP dosya yükleme (/upload), /info model sorgusu, güvenli dosya adı
  telemetri_kayit.py  yazıcı başına SQLite: 1 sn örnekleme, değişim günlüğü, saklama
  hata_kodlari.py  Creality hata kodu tablosu (veri/hata_kodlari.json) → anlamlı metin
  telegram.py      Telegram bildirim kanalı (OlayMerkezi abonesi, toplu gönderim, 429 uyumu)
web/               index.html, css/stil.css, js/uygulama.js (bağımlılıksız)
araclar/sahte_yazici.py   K2 simülatörü
testler/           birim ve uçtan uca testler
```

### REST API

| Uç | İşlev |
|---|---|
| `GET /api/kurulum`, `POST /api/kurulum` | ilk yönetici kurulumu (yalnız kullanıcı yokken) |
| `POST /api/giris`, `POST /api/cikis`, `GET /api/ben`, `PUT /api/ben/parola`, `PUT /api/ben/tercihler` | oturum, kendi parolası ve tercihleri (tema) |
| `GET/POST /api/kullanicilar`, `PUT/DELETE /api/kullanicilar/{id}` | kullanıcı yönetimi (sistem yöneticisi) |
| `GET /api/kullanicilar/{id}/gecmis`, `GET /api/kullanicilar/gecmis` | işlem geçmişi (sistem yöneticisi) |
| `GET /api/surum` | ürün, sürüm, firma |
| `GET /api/yazicilar` | tüm yazıcılar + canlı özet + durum sayıları |
| `POST /api/yazicilar` | `{ad, ip, port?, grup?, notlar?}` |
| `POST /api/yazicilar/toplu` | `{yazicilar:[{ip, ad, port, model, hostname, grup}]}` |
| `GET/PUT/DELETE /api/yazicilar/{id}` | ayrıntı (+ham, +olaylar) / güncelle / sil |
| `GET /api/yazicilar/{id}/telemetri?baslangic=&bitis=&adim=&limit=` | telemetri örnekleri (adim: seyreltme sn) |
| `GET /api/yazicilar/{id}/degisimler`, `GET /api/yazicilar/{id}/hatalar` | değişim ve hata geçmişi |
| `GET /api/hata_kodlari`, `PUT/DELETE /api/hata_kodlari/{kod}`, `POST /api/hata_kodlari/ice_aktar` | hata kodu tablosu (yazma: sistem yöneticisi) |
| `GET /api/yazicilar/{id}/kamera`, `POST /api/yazicilar/{id}/kamera/kayit` | sunucu taraflı kare (kamera_url) / tarayıcı WebRTC işlem kaydı |
| `POST /api/yazicilar/{id}/dosya` | multipart `file` (+`baslat`=1/0): yükle ve yazdır (yazıcı yöneticisi) |
| `POST /api/yazicilar/{id}/komut` | `{komut: duraklat\|surdur\|durdur\|isik\|nozul\|tabla\|fan, deger?}` |
| `GET /api/aglar` | makinedeki alt ağlar |
| `POST /api/tarama`, `GET /api/tarama`, `POST /api/tarama/iptal` | tarama işi |
| `GET /api/olaylar?limit=` | son olaylar |
| `GET/PUT /api/ayarlar/telegram` | bildirim ayarları (belirteç maskelenir; boş belirteç mevcut olanı korur) |
| `POST /api/ayarlar/telegram/test` | test mesajı `{token?, sohbetler?}` |
| `POST /api/ayarlar/telegram/sohbetler` | bota yazan sohbetleri listeler `{token?}` |
| `WS /ws` | `anlik`, `yazici`, `yazici_silindi`, `olay`, `tarama` mesajları |

## K2 yerel protokolü (topluluk gözlemi)

Creality bu arayüzü belgelememiştir. Aşağıdakiler Home Assistant entegrasyonları
(`ha_creality_ws`, `creality_assistant`, `ha-creality-lan`) ve `creality-cfs-panel`
belgelerinden derlenmiştir; tamamı `creamanage/k2_protokol.py` içinde tek yerde tutulur.

- Uç: `ws://<ip>:9999`, metin çerçeveleri, alt protokol `wsslicer`. Parola yoktur.
- Yazıcı JSON telemetri **iter**; yalnız değişen alanlar gelebilir → istemci birleştirir.
- `{"ModeCode":"heart_beat"}` gelince düz metin `ok` gönderilir; 40 sn sessizlik = kopuk.
- Veri isteği: `{"method":"get","params":{"ReqPrinterPara":1}}`, `{"boxsInfo":1}` (CFS).
- Komut: `{"method":"set","params":{"pause":1}}`, `{"pause":0}`, `{"stop":1}`,
  `{"lightSw":1}`, `{"nozzleTempControl":220}`, `{"bedTempControl":{"num":0,"val":60}}`,
  `{"fan":100}`.
- Alanlar: `hostname, model, modelVersion, state, deviceState, printFileName,
  printProgress, printLeftTime, printJobTime, layer, TotalLayer, nozzleTemp,
  targetNozzleTemp, bedTemp0, targetBedTemp0, boxTemp, targetBoxTemp, fanPct, lightSw,
  curFeedratePct, materialStatus, err{errcode,key}, boxsInfo`.
- **Doğrulanmalı:** `state` kod tablosu (0 boşta, 1 basıyor, 2 tamamlandı, 4 durduruldu,
  5 duraklatıldı). Durum türetme bu yüzden öncelikle dosya adı + ilerleme + pause
  sinyallerine dayanır; ham `state` arayüzde ayrıca gösterilir. İlk gerçek K2 Plus'ta
  ham telemetri panelden okunup tablo kesinleştirilmelidir.
- Firmware güncellemesi alan adlarını değiştirebilir; yalnız `k2_protokol.py` güncellenir.

**Dosya yükleme (Creality Print / OrcaSlicer'ın kullandığı yol):** `POST http://<ip>/upload/<ad>`
multipart, alan `file` (80 başarısızsa 4408 denenir; çalışan port kaydedilir). Dosya K2
ailesinde `/mnt/UDISK/printer_data/gcodes/` altına düşer; dizin, yazıcının bildirdiği
dosya yolundan otomatik öğrenilir. Baskı `{"opGcodeFile":"printprt:<tam yol>"}` ile
başlar. `GET http://<ip>/info` model kodunu verir (F008 = K2 Plus). CFS çok renkli baskı
için Creality Print `colorMatch` + `multiColorPrint` mesajlarını kullanır; bu sürümde
G-code yazıcıya sliced haliyle gönderilir, slot eşlemesi ileride eklenecek.

Kamera: K2 ailesi WebRTC — `POST http://<ip>:8000/call/webrtc_local`, gövde
`base64(JSON{type:"offer", sdp})`, yanıt `base64(JSON{type:"answer", sdp})`, `Content-Type:
plain/text`. Sürekli izleme için go2rtc: `webrtc:http://<ip>:8000/call/webrtc_local#format=creality`.

## Yol haritası

1. **Uyarı sistemi, devamı:** e-posta / web push / sesli uyarı kanalları
   (`olaylar.OlayMerkezi.abone_ol` ile eklenir); kural motoru (örn. "X dk çevrimdışı");
   sessize alma ve vardiya saatleri. Telegram kanalı 0.2.0'da geldi.
2. Gerçek K2 Plus ile alan/durum doğrulaması, CFS (boxsInfo) kutu-slot görünümü.
3. Canlı kamera akışı (go2rtc ile).
4. HTTPS (ters vekil), oturum listesi ve uzaktan kapatma.
5. CFS slot eşlemesi (colorMatch), iş kuyruğu, toplu yükleme (aynı dosyayı N yazıcıya).
6. Geçmiş raporları: yazıcı kullanım oranı, baskı süreleri, hata sıklığı.
7. Kurulum paketleri (`.deb`, Windows kurulum) ve systemd servisi.
