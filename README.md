# CreaManage

Creality **K2 Plus (Combo)** 3D yazıcı filosunu (hedef: 56 cihaz) yerel ağ üzerinden
**tek merkezden izleyen** web tabanlı yazılım. **Gökkubbe Teknoloji Anonim Şirketi.**

Yazıcılara müdahale gerekmez: stok Creality yazılımının yerel ağda sunduğu
**WebSocket 9999** arayüzü kullanılır (root, Moonraker, bulut yok). Garanti korunur.

## Sürüm 0.2.0 — ne yapar

- **Ağ tarama sihirbazı:** makinedeki alt ağları listeler, seçilen CIDR'da 9999 portunu
  paralel yoklar, yanıt verenlere WebSocket ile kimlik (hostname, model) sorar; bulunanları
  ad ve grup vererek toplu ekler. Elle IP ile ekleme de vardır.
- **Canlı gösterge paneli:** her yazıcı için durum (basıyor / boşta / duraklatıldı /
  tamamlandı / hata / hazırlanıyor / çevrimdışı), dosya, ilerleme, katman, kalan süre,
  nozul/tabla/kabin sıcaklıkları. Durum sayaçları, arama, durum ve grup filtresi.
- **Ayrıntı paneli:** tüm alanlar, ham telemetri, yazıcıya özel olay geçmişi, düzenleme
  (ad, IP, port, grup, not, bağlantı etkin/kapalı), silme.
- **Temel komutlar:** duraklat, sürdür, durdur, ışık aç/kapat. (API'de ayrıca nozul,
  tabla, fan.)
- **Olay akışı:** bağlantı kuruldu/koptu, baskı başladı/bitti/duraklatıldı, hata,
  filament bitti. SQLite'a yazılır, arayüze anlık itilir.
- **Telegram bildirimleri:** hata oluştuğunda ve baskı tamamlandığında (isteğe bağlı:
  filament bitti, bağlantı koptu/kuruldu, hata giderildi, duraklatıldı, başladı) seçilen
  kişi ya da gruplara mesaj. Aynı anda oluşan olaylar tek mesajda toplanır.
- **Kalıcı kayıt:** `creamanage.sqlite` (yazıcılar + olaylar + ayarlar). Depoya girmez.

## Kurulum ve çalıştırma

Gereksinim: Python ≥ 3.11 ve `aiohttp` (tek bağımlılık). Windows ve Linux'ta çalışır.

```bash
git clone https://github.com/goktalay/creamanage.git
cd creamanage
pip3 install -r requirements.txt
python3 main.py --port 8090          # http://<sunucu>:8090/
```

Ortam değişkenleri: `CREAMANAGE_HOST`, `CREAMANAGE_PORT`, `CREAMANAGE_VERITABANI`,
`CREAMANAGE_LOG`. Komut satırı: `--host`, `--port`, `--veritabani`, `--log`.

Sunucu, yazıcılarla **aynı yerel ağda** (ya da 9999 portuna yönlendirilmiş bir ağda)
olmalıdır. Tarama için alt ağ en fazla /20 (4096 adres) olabilir.

### Telegram bildirimlerini açma

1. Telegram'da **@BotFather**'a `/newbot` yazın, bot adı verin; verdiği belirteci
   (`123456789:AA…`) kopyalayın.
2. Bildirim alacak kişi bota bir kez `/start` yazsın. Grup için botu gruba ekleyin ve
   grupta bir mesaj yazın.
3. CreaManage'de sağ üstte **Bildirimler** → belirteci yapıştırın → **Sohbetleri Bul** →
   listeden kişiyi/grubu işaretleyin → hangi olaylarda bildirim istediğinizi seçin →
   **Telegram bildirimleri etkin** → **Kaydet**. **Test Mesajı Gönder** ile doğrulayın.

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
python3 -m unittest -v test_k2_protokol test_filo_uctan_uca test_telegram
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
  web.py           aiohttp: statik arayüz, REST API, /ws tarayıcı yayını
  telegram.py      Telegram bildirim kanalı (OlayMerkezi abonesi, toplu gönderim, 429 uyumu)
web/               index.html, css/stil.css, js/uygulama.js (bağımlılıksız)
araclar/sahte_yazici.py   K2 simülatörü
testler/           birim ve uçtan uca testler
```

### REST API

| Uç | İşlev |
|---|---|
| `GET /api/surum` | ürün, sürüm, firma |
| `GET /api/yazicilar` | tüm yazıcılar + canlı özet + durum sayıları |
| `POST /api/yazicilar` | `{ad, ip, port?, grup?, notlar?}` |
| `POST /api/yazicilar/toplu` | `{yazicilar:[{ip, ad, port, model, hostname, grup}]}` |
| `GET/PUT/DELETE /api/yazicilar/{id}` | ayrıntı (+ham, +olaylar) / güncelle / sil |
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

Kamera: K2 ailesi WebRTC (`http://<ip>:8000/call/webrtc_local`); bu sürümde yok.

## Yol haritası

1. **Uyarı sistemi, devamı:** e-posta / web push / sesli uyarı kanalları
   (`olaylar.OlayMerkezi.abone_ol` ile eklenir); kural motoru (örn. "X dk çevrimdışı");
   sessize alma ve vardiya saatleri. Telegram kanalı 0.2.0'da geldi.
2. Gerçek K2 Plus ile alan/durum doğrulaması, CFS (boxsInfo) kutu-slot görünümü.
3. Kamera önizlemesi (WebRTC → go2rtc).
4. Kullanıcı girişi ve yetki (izle / komut ver), HTTPS.
5. Dosya gönderme ve baskı başlatma (HTTP yükleme + `opGcodeFile`), iş kuyruğu.
6. Geçmiş raporları: yazıcı kullanım oranı, baskı süreleri, hata sıklığı.
7. Kurulum paketleri (`.deb`, Windows kurulum) ve systemd servisi.
