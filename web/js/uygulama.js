/* CREAMANAGE arayüzü — bağımlılıksız, tek dosya. */
(function () {
  "use strict";

  const DURUM_AD = {
    basiyor: "Basıyor", bosta: "Boşta", duraklatildi: "Duraklatıldı", tamamlandi: "Tamamlandı",
    hata: "Hata", hazirlaniyor: "Hazırlanıyor", cevrimdisi: "Çevrimdışı",
  };
  const DURUM_SIRA = ["basiyor", "duraklatildi", "hata", "hazirlaniyor", "tamamlandi", "bosta", "cevrimdisi"];

  const $ = (s, k) => (k || document).querySelector(s);
  const $$ = (s, k) => Array.from((k || document).querySelectorAll(s));

  const MODULLER = { yazicilar: "Yazıcılar", dosya_listesi: "Dosya Listesi", dosya_yoneticisi: "Dosya Yöneticisi",
    olaylar: "Olaylar", bildirimler: "Bildirimler", kullanicilar: "Kullanıcılar", hata_kodlari: "Hata Kodları" };
  const MODUL_GORUNUM = { yazicilar: "kart", dosya_listesi: "sade", dosya_yoneticisi: "yukle" };
  // ---------- yenileme aralığı: sunucudan gelen güncellemeler tamponlanır, seçilen aralıkta ekrana uygulanır ----------
  const bekleyenGuncelleme = new Map();
  let yenilemeZamanlayici = null, sonYenileme = 0;
  function yenilemeUygula() {
    if (!bekleyenGuncelleme.size) return;
    const liste = Array.from(bekleyenGuncelleme.values()); bekleyenGuncelleme.clear();
    if (liste.length > 8) cizHepsi(); else liste.forEach(y => cizKart(y));
    cizSayaclar(); cizGruplar();
    const acik = liste.find(y => y.id === st.acikYazici); if (acik) ayrintiDoldur(acik);
    sonYenileme = Date.now(); yenilemeDurum();
  }
  function yenilemeDurum() { const d = $("#yenileme-durum"); if (d) d.textContent = sonYenileme ? new Date(sonYenileme).toLocaleTimeString("tr-TR") : ""; }
  function yenilemeKur(sn) {
    st.yenilemeSn = sn; $("#yenileme-sn").value = String(sn);
    clearInterval(yenilemeZamanlayici);
    yenilemeZamanlayici = setInterval(yenilemeUygula, Math.max(1, sn) * 1000);
  }
  const st = { yazicilar: new Map(), olaylar: [], tarama: null, acikYazici: null, ws: null, gorunum: "kart", ben: null, modul: "yazicilar", yenilemeSn: 1 };
  try { const m = localStorage.getItem("creamanage.modul"); if (MODULLER[m]) st.modul = m; } catch (e) { /* özel pencere */ }
  st.gorunum = MODUL_GORUNUM[st.modul] || "kart";

  // ---------- yardımcılar ----------
  function kacis(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function sure(sn) {
    if (sn == null || isNaN(sn)) return "–";
    sn = Math.max(0, Math.round(sn));
    const s = Math.floor(sn / 3600), d = Math.floor((sn % 3600) / 60);
    return s ? `${s} sa ${d} dk` : `${d} dk`;
  }
  function saat(ts) {
    const t = new Date(ts * 1000);
    return t.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  function derece(v, hedef) {
    if (v == null) return "–";
    const a = Number(v).toFixed(0) + "°";
    return hedef ? `${a}/${Number(hedef).toFixed(0)}°` : a;
  }
  function bildir(m, sure_ms) {
    const b = $("#bildirim"); b.textContent = m; b.hidden = false;
    clearTimeout(bildir._t); bildir._t = setTimeout(() => { b.hidden = true; }, sure_ms || 3000);
  }
  async function api(yol, secenek) {
    const r = await fetch(yol, Object.assign({ headers: { "Content-Type": "application/json" } }, secenek || {}));
    let veri = {};
    try { veri = await r.json(); } catch (e) { /* boş gövde */ }
    if (r.status === 401) { location.href = "/giris"; throw new Error("giriş gerekli"); }
    if (!r.ok) throw new Error(veri.hata || (r.status + " " + r.statusText));
    return veri;
  }
  const ROL_SIRA = { gozetmen: 1, yazici_yoneticisi: 2, sistem_yoneticisi: 3 };
  const yetkili = (rol) => st.ben && ROL_SIRA[st.ben.rol] >= ROL_SIRA[rol];
  function basHarfler(ad) {
    const p = String(ad || "?").trim().split(/\s+/).filter(Boolean);
    return ((p[0] || "?")[0] + (p.length > 1 ? p[p.length - 1][0] : "")).toLocaleUpperCase("tr-TR");
  }
  function avatarRenk(metin) { let h = 0; for (const c of String(metin)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return `hsl(${h % 360} 45% 45%)`; }
  // ---------- tema (gece/gündüz), kullanıcı hesabında saklanır ----------
  function temaUygula(tema) {
    if (tema === "acik" || tema === "koyu") document.documentElement.dataset.theme = tema;
    else delete document.documentElement.dataset.theme;
    try { if (tema === "acik" || tema === "koyu") localStorage.setItem("creamanage.tema", tema); else localStorage.removeItem("creamanage.tema"); } catch (e) { /* yok say */ }
  }
  function etkinTema() {
    const t = document.documentElement.dataset.theme;
    if (t === "acik" || t === "koyu") return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "koyu" : "acik";
  }
  async function temaDegistir() {
    const yeni = etkinTema() === "koyu" ? "acik" : "koyu";
    temaUygula(yeni);
    if (st.acikYazici && ayModul === "gecmis" && ayGecmisVeri.length) grafikleriCiz();
    try { await put("/api/ben/tercihler", { tema: yeni }); if (st.ben) st.ben.tercihler = Object.assign({}, st.ben.tercihler, { tema: yeni }); }
    catch (e) { bildir("Tema tercihi kaydedilemedi: " + e.message); }
  }
  $("#btn-tema").addEventListener("click", temaDegistir);
  function rolUygula() {
    $$("[data-rol]").forEach(el => el.classList.toggle("yetkisiz", !yetkili(el.dataset.rol)));
    if (st.ben) {
      const t = (st.ben.tercihler || {}).tema; if (t) temaUygula(t);
      const y = Number((st.ben.tercihler || {}).yenileme_sn); if (y && y !== st.yenilemeSn) yenilemeKur(y);
      $("#ben-ad").textContent = st.ben.ad || st.ben.kullanici_adi; $("#ben-rol").textContent = st.ben.rol_adi;
      const bh = basHarfler(st.ben.ad || st.ben.kullanici_adi), renk = avatarRenk(st.ben.kullanici_adi);
      $$("#avatar, #avatar-buyuk").forEach(a => { a.textContent = bh; a.style.setProperty("--avatar-renk", renk); });
      const uyg = $(`.uyg[data-modul="${st.modul}"]`);
      if (uyg && uyg.dataset.rol && !yetkili(uyg.dataset.rol)) modulAc("yazicilar");
    }
  }
  const post = (yol, govde) => api(yol, { method: "POST", body: JSON.stringify(govde || {}) });
  const put = (yol, govde) => api(yol, { method: "PUT", body: JSON.stringify(govde || {}) });
  const del = (yol) => api(yol, { method: "DELETE" });

  // ---------- WebSocket ----------
  function wsBaglan() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    st.ws = ws;
    ws.onopen = () => rozet(true);
    ws.onclose = () => { rozet(false); setTimeout(() => api("/api/ben").then(wsBaglan).catch(() => {}), 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch (err) { return; }
      if (m.tur === "anlik") {
        if (m.kullanici) { st.ben = m.kullanici; rolUygula(); }
        st.yazicilar = new Map(m.yazicilar.map(y => [y.id, y]));
        st.olaylar = m.olaylar || [];
        st.tarama = m.tarama;
        cizHepsi(); cizOlaylar(); taramaGuncelle();
      } else if (m.tur === "yazici") {
        st.yazicilar.set(m.yazici.id, m.yazici);
        bekleyenGuncelleme.set(m.yazici.id, m.yazici);
        if (st.yenilemeSn <= 1) yenilemeUygula();
      } else if (m.tur === "yazici_silindi") {
        st.yazicilar.delete(m.id); cizHepsi();
        if (st.acikYazici === m.id) kapat("ortu-ayrinti");
      } else if (m.tur === "olay") {
        st.olaylar.unshift(m.olay); st.olaylar = st.olaylar.slice(0, 300); if (st.modul === "olaylar") cizOlaylar();
        if (m.olay.seviye === "kritik" || m.olay.seviye === "uyari") bildir(m.olay.mesaj, 5000);
      } else if (m.tur === "tarama") {
        st.tarama = m.tarama; taramaGuncelle();
      }
    };
  }
  function rozet(bagli) {
    const r = $("#baglanti-rozeti");
    r.textContent = bagli ? "Sunucuya bağlı" : "Sunucu bağlantısı yok";
    r.className = "rozet " + (bagli ? "rozet-bagli" : "rozet-kopuk");
  }

  // ---------- liste / kartlar ----------
  function filtreli() {
    const q = $("#arama").value.trim().toLowerCase();
    const d = $("#filtre-durum").value, g = $("#filtre-grup").value;
    return Array.from(st.yazicilar.values()).filter(y => {
      const c = y.canli || {};
      if (d && c.durum !== d) return false;
      if (g && (y.grup || "") !== g) return false;
      if (q && !(`${y.ad} ${y.ip} ${y.hostname || ""} ${c.dosya || ""} ${y.grup || ""}`.toLowerCase().includes(q))) return false;
      return true;
    }).sort((a, b) => {
      const da = DURUM_SIRA.indexOf((a.canli || {}).durum), db = DURUM_SIRA.indexOf((b.canli || {}).durum);
      return da - db || a.ad.localeCompare(b.ad, "tr");
    });
  }
  function kartHtml(y) {
    const c = y.canli || {}, d = c.durum || "cevrimdisi";
    const ilerleme = c.ilerleme != null ? Math.round(c.ilerleme) : null;
    return `
      <div class="baslik"><span class="ad" title="${kacis(y.ad)}">${kacis(y.ad)}</span><span class="durum">${DURUM_AD[d] || d}</span></div>
      <div class="ip">${kacis(y.ip)}${y.grup ? " · " + kacis(y.grup) : ""}${c.model ? " · " + kacis(c.model) : ""}</div>
      <div class="dosya" title="${kacis(c.dosya_yolu || c.dosya)}">${c.dosya ? kacis(c.dosya) : (d === "cevrimdisi" ? kacis(c.son_hata || "bağlantı bekleniyor") : "")}</div>
      <progress max="100" value="${ilerleme == null ? 0 : ilerleme}"></progress>
      <div class="satir-bilgi"><span>${ilerleme == null ? "" : "%" + ilerleme}</span><span>${c.katman != null && c.toplam_katman ? `katman ${c.katman}/${c.toplam_katman}` : ""}</span><span>${c.kalan_sn != null && d === "basiyor" ? "kalan " + sure(c.kalan_sn) : ""}</span></div>
      <div class="sicaklik"><span>Nozul <b>${derece(c.nozul, c.nozul_hedef)}</b></span><span>Tabla <b>${derece(c.tabla, c.tabla_hedef)}</b></span><span>Kabin <b>${derece(c.kabin, c.kabin_hedef)}</b></span>${c.filament_yok ? '<span class="olay-kritik">Filament yok</span>' : ""}</div>`;
  }
  const miniCubuk = (yuzde) => `<span class="mini-cubuk"><i style="width:${Math.max(0, Math.min(100, yuzde))}%"></i></span>`;
  function sadeSatirHtml(y) {
    const c = y.canli || {}, d = c.durum || "cevrimdisi";
    const aktif = c.ilerleme != null && d !== "bosta" && d !== "cevrimdisi";
    const ilerleme = aktif ? Math.round(c.ilerleme) : null;
    return `<td class="ad" title="${kacis(y.ip)} · ${DURUM_AD[d] || d}">${kacis(y.ad)}</td>` +
      `<td title="${kacis(c.dosya_yolu || c.dosya || "")}">${c.dosya ? kacis(c.dosya) : '<span class="ipucu">–</span>'}</td>` +
      `<td class="yuzde">${ilerleme != null ? "%" + ilerleme + miniCubuk(ilerleme) : ""}</td>`;
  }
  function cizSade() {
    $("#sade tbody").innerHTML = filtreli().map(y => {
      const d = (y.canli || {}).durum || "cevrimdisi";
      return `<tr class="${d}" data-id="${y.id}" style="--renk: var(--d-${d})">${sadeSatirHtml(y)}</tr>`;
    }).join("");
  }
  function gorunumUygula() {
    Object.keys(MODULLER).forEach(m => { const el = $("#modul-" + m); if (el) el.hidden = m !== st.modul; });
    $("#yazici-arac").hidden = !MODUL_GORUNUM[st.modul];
    $("#modul-baslik").textContent = MODULLER[st.modul] || "";
    $$(".uyg[data-modul]").forEach(b => b.classList.toggle("aktif", b.dataset.modul === st.modul));
  }
  function modulAc(ad) {
    if (!MODULLER[ad]) return;
    st.modul = ad; st.gorunum = MODUL_GORUNUM[ad] || st.gorunum;
    try { localStorage.setItem("creamanage.modul", ad); } catch (e) { /* yok say */ }
    menuKapat();
    if (MODUL_GORUNUM[ad]) cizHepsi(); else gorunumUygula();
    if (ad === "kullanicilar") kullanicilarAc();
    if (ad === "bildirimler") bildirimAc();
    if (ad === "olaylar") cizOlaylar();
    if (ad === "hata_kodlari") hataKodlariAc();
  }
  function menuKapat() { $("#menu-uygulamalar").hidden = true; $("#menu-hesap").hidden = true; $("#btn-uygulamalar").classList.remove("acik"); }
  const yuklemeler = new Map();   // yazıcı id → {yuzde, metin}
  function yukleKartHtml(y) {
    const c = y.canli || {}, d = c.durum || "cevrimdisi", yk = yuklemeler.get(y.id);
    const yetkiliMi = yetkili("yazici_yoneticisi"), bos = !c.dosya;
    let orta;
    if (yk) orta = `<div class="dosya-metin">${kacis(yk.metin)}<progress max="100" value="${yk.yuzde}"></progress></div>`;
    else if (yetkiliMi) orta = `<button type="button" class="dosya-btn ${bos ? "bos" : ""}" ${d === "cevrimdisi" ? "disabled" : ""} title="${kacis(c.dosya_yolu || "")}">${bos ? "Dosya seç ve yazdır" : kacis(c.dosya)}<small>${d === "cevrimdisi" ? "yazıcı çevrimdışı" : (bos ? "" : "değiştirmek için tıklayın")}</small></button>`;
    else orta = `<div class="dosya-metin" title="${kacis(c.dosya_yolu || "")}">${bos ? '<span class="ipucu">–</span>' : kacis(c.dosya)}</div>`;
    const aktif = c.ilerleme != null && (d === "basiyor" || d === "duraklatildi"), ilerleme = aktif ? Math.round(c.ilerleme) : null;
    return `<div class="bas"><span title="${kacis(y.ad)}">${kacis(y.ad)}</span><span class="durum">${DURUM_AD[d] || d}</span></div>
      <div class="orta">${orta}</div>
      <div class="alt"><div class="alt-satir"><span>${kacis(y.ip)}</span><span>${ilerleme != null ? "%" + ilerleme : ""}${y.grup ? (ilerleme != null ? " · " : "") + kacis(y.grup) : ""}</span></div>${ilerleme != null ? miniCubuk(ilerleme) : ""}</div>`;
  }
  function cizYukle() {
    $("#yukle").innerHTML = filtreli().map(y => {
      const d = (y.canli || {}).durum || "cevrimdisi";
      return `<div class="ykart ${d}" data-id="${y.id}" style="--renk: var(--d-${d})">${yukleKartHtml(y)}</div>`;
    }).join("");
  }
  function cizKart(y) {
    if (st.gorunum === "yukle") {
      const k = $(`#yukle .ykart[data-id="${y.id}"]`), gorunur = filtreli().some(f => f.id === y.id);
      if (!gorunur) { if (k) k.remove(); sonucSayisi(); bosMu(); return; }
      if (!k) { cizHepsi(); return; }
      const d = (y.canli || {}).durum || "cevrimdisi";
      k.className = "ykart " + d; k.style.setProperty("--renk", `var(--d-${d})`); k.innerHTML = yukleKartHtml(y);
      return;
    }
    if (st.gorunum === "sade") {
      const tr = $(`#sade tr[data-id="${y.id}"]`), gorunur = filtreli().some(f => f.id === y.id);
      if (!gorunur) { if (tr) tr.remove(); sonucSayisi(); bosMu(); return; }
      if (!tr) { cizHepsi(); return; }
      const d = (y.canli || {}).durum || "cevrimdisi";
      tr.className = d; tr.style.setProperty("--renk", `var(--d-${d})`); tr.innerHTML = sadeSatirHtml(y);
      return;
    }
    const gorunur = filtreli().some(f => f.id === y.id);
    let k = $(`.kart[data-id="${y.id}"]`);
    if (!gorunur) { if (k) k.remove(); sonucSayisi(); bosMu(); return; }
    if (!k) { cizHepsi(); return; }
    const d = (y.canli || {}).durum || "cevrimdisi";
    k.className = "kart " + d; k.style.setProperty("--renk", `var(--d-${d})`);
    k.innerHTML = kartHtml(y);
  }
  function cizHepsi() {
    gorunumUygula();
    if (!MODUL_GORUNUM[st.modul]) { cizSayaclar(); cizGruplar(); return; }
    if (st.gorunum === "sade") { cizSade(); cizSayaclar(); cizGruplar(); sonucSayisi(); bosMu(); return; }
    if (st.gorunum === "yukle") { cizYukle(); cizSayaclar(); cizGruplar(); sonucSayisi(); bosMu(); return; }
    const kap = $("#kartlar");
    kap.innerHTML = filtreli().map(y => {
      const d = (y.canli || {}).durum || "cevrimdisi";
      return `<div class="kart ${d}" data-id="${y.id}" style="--renk: var(--d-${d})">${kartHtml(y)}</div>`;
    }).join("");
    cizSayaclar(); cizGruplar(); sonucSayisi(); bosMu();
  }
  function bosMu() { $("#bos").hidden = st.yazicilar.size > 0 || st.modul !== "yazicilar"; }
  function sonucSayisi() { $("#sonuc-sayisi").textContent = `${filtreli().length} / ${st.yazicilar.size} yazıcı`; }
  function cizSayaclar() {
    const s = {}; DURUM_SIRA.forEach(d => s[d] = 0);
    st.yazicilar.forEach(y => { const d = (y.canli || {}).durum || "cevrimdisi"; s[d] = (s[d] || 0) + 1; });
    const aktif = $("#filtre-durum").value;
    $("#sayaclar").innerHTML = `<span class="sayac" data-d="">Toplam<b>${st.yazicilar.size}</b></span>` +
      DURUM_SIRA.map(d => `<span class="sayac${aktif === d ? " aktif" : ""}" data-d="${d}" style="--renk: var(--d-${d})">${DURUM_AD[d]}<b>${s[d]}</b></span>`).join("");
  }
  function cizGruplar() {
    const sel = $("#filtre-grup"), mevcut = sel.value;
    const gruplar = Array.from(new Set(Array.from(st.yazicilar.values()).map(y => y.grup).filter(Boolean))).sort();
    sel.innerHTML = '<option value="">Tüm gruplar</option>' + gruplar.map(g => `<option value="${kacis(g)}">${kacis(g)}</option>`).join("");
    sel.value = gruplar.includes(mevcut) ? mevcut : "";
  }
  function cizOlaylar() {
    $("#olay-listesi").innerHTML = st.olaylar.slice(0, 200).map(o =>
      `<li class="olay-${o.seviye}"><time>${saat(o.zaman)}</time>${kacis(o.mesaj)}</li>`).join("") || '<li class="ipucu">Henüz olay yok.</li>';
  }

  // ---------- ayrıntı ----------
  // ---------- yazıcı ayrıntısı: modüller ----------
  const AY_MODULLER = { durum: "Durum Bilgisi", islemler: "İşlemler", hatalar: "Yazıcı Hataları", gecmis: "Geçmiş", ayarlar: "Yazıcı Ayarları" };
  let ayModul = "durum";
  function ayMenuKapat() { $("#ay-menu").hidden = true; $("#ay-menu-btn").classList.remove("acik"); }
  function ayModulAc(ad) {
    const btn = $(`.uyg[data-ay-modul="${ad}"]`);
    if (!AY_MODULLER[ad] || (btn && btn.dataset.rol && !yetkili(btn.dataset.rol))) ad = "durum";
    ayModul = ad; ayMenuKapat();
    Object.keys(AY_MODULLER).forEach(m => { $("#ay-modul-" + m).hidden = m !== ad; });
    $$(".uyg[data-ay-modul]").forEach(b => b.classList.toggle("aktif", b.dataset.ayModul === ad));
    const y = st.yazicilar.get(st.acikYazici); if (!y) return;
    if (ad === "hatalar") ayHatalarYukle(y.id);
    if (ad === "gecmis") ayGecmisYukle(y.id);
  }
  $("#ay-menu-btn").addEventListener("click", (e) => { e.stopPropagation(); const m = $("#ay-menu"), acik = m.hidden; ayMenuKapat(); m.hidden = !acik; $("#ay-menu-btn").classList.toggle("acik", acik); });
  $$(".uyg[data-ay-modul]").forEach(b => b.addEventListener("click", () => ayModulAc(b.dataset.ayModul)));
  document.addEventListener("click", (e) => { if (!e.target.closest("#ay-menu") && !e.target.closest("#ay-menu-btn")) ayMenuKapat(); });
  async function ayrintiAc(id) {
    st.acikYazici = id;
    const y = st.yazicilar.get(id); if (!y) return;
    ayrintiDoldur(y);
    ac("ortu-ayrinti");
    ayModulAc(ayModul);
    try {
      const v = await api(`/api/yazicilar/${id}`);
      st.ayHata = v.hata || null;
      $("#ay-olaylar").innerHTML = v.olaylar.map(o => `<li class="olay-${o.seviye}"><time>${saat(o.zaman)}</time>${kacis(o.mesaj)}</li>`).join("") || "<li class='ipucu'>Olay yok.</li>";
      if (ayModul === "durum") ayrintiDoldur(y);
    } catch (e) { bildir(e.message); }
  }
  const ALAN_AD = { durum: "Durum", baglanti: "Bağlantı", hata_kodu: "Hata kodu", dosya: "Dosya", ip: "IP adresi", filament_yok: "Filament", son_hata: "Bağlantı hatası" };
  const degerAd = (alan, v) => v == null || v === "None" ? "–" : (alan === "durum" ? (DURUM_AD[v] || v) : (alan === "baglanti" ? ({ bagli: "Bağlı", baglaniyor: "Bağlanıyor", kopuk: "Kopuk" }[v] || v) : (alan === "filament_yok" ? (v === "1" ? "Bitti" : "Var") : v)));
  async function ayHatalarYukle(id) {
    const y = st.yazicilar.get(id), c = (y && y.canli) || {};
    const kap = $("#ay-hata-simdi");
    if (c.hata_kodu) {
      const h = st.ayHata || { metin: `kod ${c.hata_kodu}`, bilinen: false };
      kap.innerHTML = `<div class="hata-simdi" style="--renk: var(--d-hata)"><span class="bk-ikon">${IKON.alert}</span><div><b>Şu an hata bildiriyor: ${kacis(h.metin)}</b>
        <div class="ipucu">Kod ${kacis(h.kod || c.hata_anahtari || c.hata_kodu)}${h.sinif ? " · " + kacis(h.sinif) : ""}${h.modul ? " · " + kacis(h.modul) : ""}</div>
        ${h.aciklama ? `<div>${kacis(h.aciklama)}</div>` : ""}${h.cozum ? `<div class="ipucu"><b>Çözüm:</b> ${kacis(h.cozum)}</div>` : ""}
        ${h.bilinen ? "" : `<div class="ipucu">Bu kodun açıklaması tabloda yok. Sunucuda <code>python araclar/hata_kodlari_al.py</code> ile Creality tablosunu indirin.</div>`}</div></div>`;
    } else kap.innerHTML = `<div class="hata-simdi" style="--renk: var(--d-basiyor)"><span class="bk-ikon">${IKON.check}</span><div><b>Şu an hata yok</b><div class="ipucu">Yazıcı sorun bildirmiyor.</div></div></div>`;
    try {
      const v = await api(`/api/yazicilar/${id}/hatalar`);
      const satirlar = [];
      v.hatalar.forEach(h => satirlar.push({ z: h.zaman, olay: h.basladi ? "Hata başladı" : "Hata geçti", kod: h.basladi ? h.yeni : (h.eski || ""), ayrinti: h.basladi ? ((h.aciklama && h.aciklama.metin) || h.baglam || "") : "", kritik: h.basladi }));
      v.olaylar.forEach(o => satirlar.push({ z: o.zaman, olay: EYLEM_OLAY[o.tur] || o.tur, kod: (o.veri && o.veri.kod) || "", ayrinti: o.mesaj, kritik: o.seviye === "kritik" || o.seviye === "major" }));
      satirlar.sort((a, b) => b.z - a.z);
      $("#ay-hata-tablo tbody").innerHTML = satirlar.slice(0, 300).map(r => `<tr class="${r.kritik ? "kritik" : ""}"><td class="zaman">${new Date(r.z * 1000).toLocaleString("tr-TR")}</td><td class="eylem">${kacis(r.olay)}</td><td>${kacis(r.kod)}</td><td>${kacis(r.ayrinti)}</td></tr>`).join("")
        || '<tr><td colspan="4" class="ipucu">Kayıtlı hata yok.</td></tr>';
    } catch (e) { bildir(e.message); }
  }
  const EYLEM_OLAY = { hata: "Hata bildirildi", hata_gecti: "Hata giderildi", filament_yok: "Filament bitti", koptu: "Bağlantı koptu", dis_mudahale: "MAJÖR: yazıcıdan müdahale" };
  let ayGecmisVeri = [];
  async function ayGecmisYukle(id) {
    const aralik = Number($("#ay-gecmis-aralik").value), adim = Number($("#ay-gecmis-adim").value);
    const bas = aralik ? Math.floor(Date.now() / 1000) - aralik : "";
    $$("#ay-grafikler .viz-alan").forEach(k => k.classList.add("yenileniyor"));
    try {
      const [t, d] = await Promise.all([api(`/api/yazicilar/${id}/telemetri?limit=2000&adim=${adim}&baslangic=${bas}`), api(`/api/yazicilar/${id}/degisimler?limit=500&baslangic=${bas}`)]);
      ayGecmisVeri = t.ornekler;
      grafikleriCiz();
      const oz = t.ozet || {};
      $("#ay-gecmis-ozet").textContent = `${t.ornekler.length} örnek gösteriliyor · dosyada ${oz.ornek || 0} örnek, ${oz.degisim || 0} değişim` + (oz.boyut ? ` · ${(oz.boyut / 1024 / 1024).toFixed(1)} MB` : "");
      $("#ay-degisim-tablo tbody").innerHTML = d.degisimler.map(x => `<tr class="${x.alan === "hata_kodu" && x.yeni && x.yeni !== "0" ? "kritik" : ""}"><td class="zaman">${new Date(x.zaman * 1000).toLocaleString("tr-TR")}</td><td class="eylem">${kacis(ALAN_AD[x.alan] || x.alan)}</td><td>${kacis(degerAd(x.alan, x.eski))}</td><td>${kacis(degerAd(x.alan, x.yeni))}</td><td class="ipucu">${kacis(x.baglam || "")}</td></tr>`).join("")
        || '<tr><td colspan="5" class="ipucu">Bu aralıkta değişiklik yok.</td></tr>';
      const d1 = (v) => v == null ? "" : Number(v).toFixed(0);
      $("#ay-telemetri-tablo tbody").innerHTML = t.ornekler.map(o => `<tr><td class="zaman">${new Date(o.zaman * 1000).toLocaleString("tr-TR")}</td><td>${kacis(DURUM_AD[o.durum] || o.durum || "")}</td><td title="${kacis(o.dosya || "")}">${kacis(o.dosya || "")}</td><td>${o.ilerleme == null ? "" : Math.round(o.ilerleme)}</td><td>${o.katman == null ? "" : o.katman + "/" + (o.toplam_katman || "?")}</td><td>${d1(o.nozul)}${o.nozul_hedef ? "/" + d1(o.nozul_hedef) : ""}</td><td>${d1(o.tabla)}${o.tabla_hedef ? "/" + d1(o.tabla_hedef) : ""}</td><td>${d1(o.kabin)}</td><td>${d1(o.fan)}</td><td>${d1(o.hiz_yuzde)}</td><td>${o.kalan_sn == null ? "" : sure(o.kalan_sn)}</td><td>${o.hata_kodu ? kacis(String(o.hata_kodu)) : ""}</td></tr>`).join("")
        || '<tr><td colspan="12" class="ipucu">Bu aralıkta örnek yok.</td></tr>';
    } catch (e) { bildir(e.message); }
  }
  // ---------- grafikler: SVG çizgi grafiği, kesişim çizgisi + ipucu, klavye ----------
  const SVG_NS = "http://www.w3.org/2000/svg";
  function el(ad, nit, metin) { const e = document.createElementNS(SVG_NS, ad); for (const k in (nit || {})) e.setAttribute(k, nit[k]); if (metin != null) e.textContent = metin; return e; }
  function tikDegerleri(min, max, adet) {
    const ham = (max - min) / Math.max(1, adet), buyukluk = Math.pow(10, Math.floor(Math.log10(ham || 1)));
    const aday = [1, 2, 2.5, 5, 10].map(x => x * buyukluk).find(x => (max - min) / x <= adet) || buyukluk * 10;
    const t = []; for (let v = Math.ceil(min / aday) * aday; v <= max + 1e-9; v += aday) t.push(Math.round(v * 1000) / 1000); return t;
  }
  const zamanEtiket = (ts, uzun) => { const d = new Date(ts * 1000); return uzun ? d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }); };
  /** seriler: [{ad, alan, renk, kesik?, alan_dolgu?}] — veri artan zamanlı örnekler; kopuk bağlantıda çizgi kesilir. */
  function cizGrafik(kap, veri, seriler, secenek) {
    const o = Object.assign({ birim: "", min: null, max: null, yuzde: false }, secenek || {});
    kap.innerHTML = "";
    const G = kap.getBoundingClientRect(), W = Math.max(320, G.width), H = Math.max(160, G.height);
    const P = { sol: 40, sag: 56, ust: 10, alt: 24 }, iw = W - P.sol - P.sag, ih = H - P.ust - P.alt;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }); kap.appendChild(svg);
    const noktalar = veri.filter(v => v.zaman != null);
    if (noktalar.length < 2) { svg.appendChild(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "bos" }, "Bu aralıkta çizilecek veri yok")); return null; }
    const t0 = noktalar[0].zaman, t1 = noktalar[noktalar.length - 1].zaman, ts = Math.max(1, t1 - t0);
    let yMin = o.min, yMax = o.max;
    if (yMin == null || yMax == null) {
      const degerler = []; noktalar.forEach(v => seriler.forEach(s => { const d = v[s.alan]; if (d != null && !isNaN(d)) degerler.push(Number(d)); }));
      const dMin = degerler.length ? Math.min(...degerler) : 0, dMax = degerler.length ? Math.max(...degerler) : 1;
      if (yMin == null) yMin = Math.min(0, dMin); if (yMax == null) yMax = dMax <= yMin ? yMin + 1 : dMax * 1.05;
    }
    const tikler = tikDegerleri(yMin, yMax, 4); yMax = Math.max(yMax, tikler[tikler.length - 1] || yMax);
    const X = (t) => P.sol + (t - t0) / ts * iw, Y = (v) => P.ust + ih - (v - yMin) / (yMax - yMin) * ih;
    const grid = el("g", { class: "grid" }), eksen = el("g", { class: "eksen" });
    tikler.forEach(v => { grid.appendChild(el("line", { x1: P.sol, x2: P.sol + iw, y1: Y(v), y2: Y(v) })); svg.appendChild(el("text", { x: P.sol - 6, y: Y(v) + 4, "text-anchor": "end" }, String(v))); });
    svg.appendChild(grid);
    eksen.appendChild(el("line", { x1: P.sol, x2: P.sol + iw, y1: P.ust + ih, y2: P.ust + ih })); svg.appendChild(eksen);
    const uzun = ts > 86400, xAdet = Math.max(2, Math.floor(iw / (uzun ? 110 : 70)));
    for (let i = 0; i <= xAdet; i++) { const t = t0 + ts * i / xAdet; svg.appendChild(el("text", { x: X(t), y: H - 6, "text-anchor": i === 0 ? "start" : (i === xAdet ? "end" : "middle") }, zamanEtiket(t, uzun))); }
    const yollar = {};
    seriler.forEach(s => {
      let d = "", acik = false, son = null;
      noktalar.forEach(v => {
        const deger = v[s.alan], kopuk = v.baglanti && v.baglanti !== "bagli";
        if (deger == null || isNaN(deger) || kopuk) { acik = false; return; }
        const x = X(v.zaman), y = Y(Number(deger));
        d += (acik ? " L" : " M") + x.toFixed(1) + " " + y.toFixed(1); acik = true; son = { x, y, deger: Number(deger) };
      });
      if (s.alan_dolgu && d) { const ilk = d.indexOf("M"); const alanD = d + ` L${X(t1).toFixed(1)} ${Y(yMin).toFixed(1)} L${X(t0).toFixed(1)} ${Y(yMin).toFixed(1)} Z`; svg.appendChild(el("path", { d: alanD, class: "alan", fill: s.renk })); }
      svg.appendChild(el("path", { d: d || "M0 0", class: s.kesik ? "hedef" : "seri", stroke: s.renk }));
      if (son && !s.kesik) { svg.appendChild(el("circle", { cx: son.x, cy: son.y, r: 4, fill: s.renk, class: "nokta" })); svg.appendChild(el("text", { x: son.x + 8, y: son.y + 4, class: "son-etiket" }, (o.yuzde ? "%" : "") + Math.round(son.deger) + (o.yuzde ? "" : o.birim))); }
      yollar[s.alan] = true;
    });
    // kesişim çizgisi + noktalar (etkileşim)
    const kesisim = el("line", { class: "kesisim", y1: P.ust, y2: P.ust + ih, x1: -10, x2: -10, visibility: "hidden" }); svg.appendChild(kesisim);
    const vurgu = seriler.filter(s => !s.kesik).map(s => { const c = el("circle", { r: 4.5, class: "nokta", fill: s.renk, visibility: "hidden" }); svg.appendChild(c); return { s, c }; });
    const ipucu = $("#viz-ipucu"), kok = $("#ay-grafikler");
    function goster(i, px) {
      const v = noktalar[i]; if (!v) return;
      const x = X(v.zaman); kesisim.setAttribute("x1", x); kesisim.setAttribute("x2", x); kesisim.setAttribute("visibility", "visible");
      vurgu.forEach(({ s, c }) => { const d = v[s.alan]; if (d == null || isNaN(d) || (v.baglanti && v.baglanti !== "bagli")) c.setAttribute("visibility", "hidden"); else { c.setAttribute("cx", x); c.setAttribute("cy", Y(Number(d))); c.setAttribute("visibility", "visible"); } });
      ipucu.innerHTML = ""; const z = document.createElement("div"); z.className = "zaman"; z.textContent = new Date(v.zaman * 1000).toLocaleString("tr-TR"); ipucu.appendChild(z);
      seriler.forEach(s => { const d = v[s.alan]; const satir = document.createElement("div"); satir.className = "satir"; const i2 = document.createElement("i"); i2.style.setProperty("--renk", s.renk); if (s.kesik) i2.className = "kesik"; const ad = document.createElement("span"); ad.textContent = s.ad; const b = document.createElement("b"); b.textContent = d == null || isNaN(d) ? "–" : (o.yuzde ? "%" : "") + Math.round(Number(d) * 10) / 10 + (o.yuzde ? "" : o.birim); satir.append(i2, ad, b); ipucu.appendChild(satir); });
      ipucu.hidden = false;
      const R = kok.getBoundingClientRect(), K = kap.getBoundingClientRect(); const solX = K.left - R.left + (px != null ? px : (x / W) * K.width);
      ipucu.style.top = (K.top - R.top + 8) + "px"; ipucu.style.left = Math.min(R.width - ipucu.offsetWidth - 4, Math.max(0, solX + 14)) + "px";
      kap.dataset.i = i;
    }
    function gizle() { kesisim.setAttribute("visibility", "hidden"); vurgu.forEach(({ c }) => c.setAttribute("visibility", "hidden")); ipucu.hidden = true; }
    function enYakin(px) { const K = kap.getBoundingClientRect(); const t = t0 + Math.max(0, Math.min(1, ((px / K.width) * W - P.sol) / iw)) * ts; let lo = 0, hi = noktalar.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (noktalar[m].zaman < t) lo = m + 1; else hi = m; } if (lo > 0 && Math.abs(noktalar[lo - 1].zaman - t) < Math.abs(noktalar[lo].zaman - t)) lo--; return lo; }
    kap.onpointermove = (e) => { const K = kap.getBoundingClientRect(); goster(enYakin(e.clientX - K.left), e.clientX - K.left); };
    kap.onpointerleave = gizle;
    kap.onkeydown = (e) => { if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return; e.preventDefault(); let i = Number(kap.dataset.i || noktalar.length - 1); i = Math.max(0, Math.min(noktalar.length - 1, i + (e.key === "ArrowRight" ? 1 : -1))); goster(i); };
    kap.onfocus = () => goster(Number(kap.dataset.i || noktalar.length - 1)); kap.onblur = gizle;
    return svg;
  }
  const serilerSicaklik = () => { const r = getComputedStyle($("#ay-grafikler")); const s1 = r.getPropertyValue("--seri-1").trim(), s2 = r.getPropertyValue("--seri-2").trim(), s3 = r.getPropertyValue("--seri-3").trim(); return [
    { ad: "Nozul", alan: "nozul", renk: s1 }, { ad: "Nozul hedef", alan: "nozul_hedef", renk: s1, kesik: true },
    { ad: "Tabla", alan: "tabla", renk: s2 }, { ad: "Tabla hedef", alan: "tabla_hedef", renk: s2, kesik: true },
    { ad: "Kabin", alan: "kabin", renk: s3 }, { ad: "Kabin hedef", alan: "kabin_hedef", renk: s3, kesik: true }]; };
  function grafikleriCiz() {
    const veri = ayGecmisVeri.slice().reverse();          // artan zaman
    const seriler = serilerSicaklik();
    $("#lejant-sicaklik").innerHTML = seriler.filter(s => !s.kesik).map(s => `<span><i style="--renk:${s.renk}"></i>${kacis(s.ad)}</span>`).join("") + `<span><i class="kesik" style="--renk:var(--viz-muted)"></i>hedef</span>`;
    const k1 = $("#grafik-sicaklik .viz-alan"), k2 = $("#grafik-ilerleme .viz-alan");
    cizGrafik(k1, veri, seriler, { birim: "°", min: 0 });
    cizGrafik(k2, veri, [{ ad: "İlerleme", alan: "ilerleme", renk: seriler[0].renk, alan_dolgu: true }], { yuzde: true, min: 0, max: 100 });
    k1.classList.remove("yenileniyor"); k2.classList.remove("yenileniyor");
  }
  window.addEventListener("resize", () => { if (st.acikYazici && ayModul === "gecmis" && ayGecmisVeri.length) grafikleriCiz(); });
  ["#ay-gecmis-aralik", "#ay-gecmis-adim"].forEach(s => $(s).addEventListener("change", () => st.acikYazici && ayGecmisYukle(st.acikYazici)));
  $("#ay-gecmis-yenile").addEventListener("click", () => st.acikYazici && ayGecmisYukle(st.acikYazici));
  $("#ay-gecmis-csv").addEventListener("click", () => {
    const y = st.yazicilar.get(st.acikYazici); if (!y || !ayGecmisVeri.length) { bildir("İndirilecek veri yok"); return; }
    const kolon = ["zaman", "durum", "baglanti", "dosya", "ilerleme", "katman", "toplam_katman", "kalan_sn", "gecen_sn", "nozul", "nozul_hedef", "tabla", "tabla_hedef", "kabin", "kabin_hedef", "fan", "hiz_yuzde", "isik", "hata_kodu", "hata_anahtari"];
    const satir = (o) => kolon.map(k => { let v = o[k]; if (k === "zaman") v = new Date(v * 1000).toISOString(); return v == null ? "" : `"${String(v).replace(/"/g, '""')}"`; }).join(";");
    const csv = "\ufeff" + kolon.join(";") + "\n" + ayGecmisVeri.slice().reverse().map(satir).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })); a.download = `${y.ad}_telemetri.csv`; a.click(); URL.revokeObjectURL(a.href);
  });
  $("#ay-dosya-btn").addEventListener("click", () => { yukleHedef = st.acikYazici; $("#dosya-secici").value = ""; $("#dosya-secici").click(); });
  const IK = (yol) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${yol}</svg>`;
  const IKON = {
    printer: IK('<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="9" rx="2"/><path d="M6 15h12v6H6z"/><circle cx="17.5" cy="12.5" r=".8" fill="currentColor"/>'),
    file: IK('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>'),
    progress: IK('<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 9 9" stroke-width="3"/>'),
    layers: IK('<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/><path d="m3 17 9 5 9-5"/>'),
    clock: IK('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    hourglass: IK('<path d="M7 3h10M7 21h10"/><path d="M8 3v3a4 4 0 0 0 8 0V3M8 21v-3a4 4 0 0 1 8 0v3"/><path d="M8 6c0 3 4 5 4 6s-4 3-4 6M16 6c0 3-4 5-4 6s4 3 4 6"/>'),
    gauge: IK('<path d="M4 15a8 8 0 1 1 16 0"/><path d="m12 15 4-5"/><circle cx="12" cy="15" r="1.4" fill="currentColor"/>'),
    nozzle: IK('<path d="M9 3h6v8l3 3v2H6v-2l3-3z"/><path d="M11 16v3M13 16v3"/><path d="M12 19v2"/>'),
    bed: IK('<rect x="3" y="14" width="18" height="4" rx="1"/><path d="M6 14v-3M12 14v-3M18 14v-3"/><path d="M7 7c1 1 1 2 0 3M12 7c1 1 1 2 0 3M17 7c1 1 1 2 0 3"/>'),
    box: IK('<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>'),
    fan: IK('<circle cx="12" cy="12" r="2"/><path d="M12 10c0-3-1.5-6-4-6S6 8 9 10"/><path d="M14 12c3 0 6-1.5 6-4s-4-2-6 1"/><path d="M12 14c0 3 1.5 6 4 6s2-4-1-6"/><path d="M10 12c-3 0-6 1.5-6 4s4 2 6-1"/>'),
    bulb: IK('<path d="M9 18h6M10 21h4"/><path d="M8 13a6 6 0 1 1 8 0c-1 1-1.5 2-1.5 3h-5c0-1-.5-2-1.5-3z"/>'),
    'bulb-off': IK('<path d="M9 18h6M10 21h4"/><path d="M8 13a6 6 0 1 1 8 0c-1 1-1.5 2-1.5 3h-5c0-1-.5-2-1.5-3z"/><path d="m4 4 16 16"/>'),
    spool: IK('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 4v5M12 15v5M4 12h5M15 12h5"/>'),
    wifi: IK('<path d="M2 8.5a16 16 0 0 1 20 0"/><path d="M5.5 12a11 11 0 0 1 13 0"/><path d="M9 15.5a5.5 5.5 0 0 1 6 0"/><circle cx="12" cy="19" r="1" fill="currentColor"/>'),
    alert: IK('<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17.5v.5"/>'),
    check: IK('<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>'),
    cpu: IK('<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    hash: IK('<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>'),
    pause: IK('<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>'),
    play: IK('<path d="M6 4v16l14-8-14-8z"/>'),
    x: IK('<path d="M6 6l12 12M18 6 6 18"/>'),
    tag: IK('<path d="M3 12V4h8l10 10-8 8L3 12z"/><circle cx="7.5" cy="8.5" r="1.2" fill="currentColor"/>'),
  };
  $$(".ki[data-ikon]").forEach(el => { el.innerHTML = IKON[el.dataset.ikon] || ""; });
  function bilgiKart(ikon, etiket, deger, secenek) {
    const o = secenek || {}, renk = o.renk ? `style="--renk: ${o.renk}"` : "";
    const bos = deger == null || deger === "";
    return `<div class="bilgi-kart ${o.genis ? "genis" : ""} ${bos && o.pasifBos !== false ? "pasif" : ""}" ${renk} title="${kacis(o.ipucu || "")}">
      <span class="bk-ikon">${IKON[ikon] || ""}</span>
      <span class="bk-etiket">${kacis(etiket)}</span>
      <span class="bk-deger">${bos ? "–" : kacis(deger)}${o.alt ? `<small>${kacis(o.alt)}</small>` : ""}</span>
      ${o.yuzde != null ? `<span class="bk-cubuk"><i style="width:${Math.max(0, Math.min(100, o.yuzde))}%"></i></span>` : ""}
    </div>`;
  }
  function ayrintiDoldur(y) {
    const c = y.canli || {}, d = c.durum || "cevrimdisi", renk = `var(--d-${d})`;
    $("#ay-baslik").textContent = y.ad;
    $("#ay-altbaslik").textContent = [y.ip, c.model_adi || c.model || y.model, y.grup].filter(Boolean).join(" · ");
    $("#ay-ikon").innerHTML = IKON.printer; $("#ay-ikon").style.setProperty("--renk", renk);
    const dr = $("#ay-durum"); dr.textContent = DURUM_AD[d] || d; dr.style.setProperty("--renk", renk);
    $("#ay-alt-bilgi").textContent = [c.baglanti === "bagli" ? "Bağlı" : (c.baglanti === "baglaniyor" ? "Bağlanıyor" : "Bağlantı yok"), c.son_veri ? "son veri " + saat(c.son_veri) : "", c.dosya ? c.dosya : ""].filter(Boolean).join(" · ");
    $("#ay-alt-sag").textContent = [c.model_adi || c.model || "", c.yazilim_surumu ? "yazılım " + c.yazilim_surumu : "", c.hostname || y.hostname || ""].filter(Boolean).join(" · ");
    $("#ay-teknik").innerHTML = [["Model", c.model_adi || c.model || "–"], ["Model kodu", c.model || "–"], ["Yazılım", c.yazilim_surumu || "–"], ["Hostname", c.hostname || y.hostname || "–"], ["Ham durum", c.state_kodu != null ? `${c.state_kodu} / deviceState ${c.device_state}` : "–"], ["Yükleme dizini", y.gcode_dizini || "varsayılan"]].map(([k, v]) => `<div><b>${k}:</b> ${kacis(v)}</div>`).join("");
    const isitiyor = (v, h) => (h && v != null && v < h - 2) ? "var(--d-duraklatildi)" : (h ? "var(--d-hata)" : "var(--soluk)");
    const ilerleme = c.ilerleme != null ? Math.round(c.ilerleme) : null;
    $("#ay-kartlar").innerHTML = [
      bilgiKart("file", "Dosya", c.dosya, { genis: true, ipucu: c.dosya_yolu, pasifBos: true }),
      bilgiKart("progress", "İlerleme", ilerleme != null ? "%" + ilerleme : null, { yuzde: ilerleme, renk, alt: c.katman != null && c.toplam_katman ? `katman ${c.katman} / ${c.toplam_katman}` : "" }),
      bilgiKart("hourglass", "Kalan süre", c.kalan_sn != null && d !== "bosta" ? sure(c.kalan_sn) : null, { renk: "var(--birincil)" }),
      bilgiKart("clock", "Geçen süre", c.gecen_sn != null && d !== "bosta" ? sure(c.gecen_sn) : null, { renk: "var(--birincil)" }),
      bilgiKart("nozzle", "Nozul", c.nozul != null ? Number(c.nozul).toFixed(0) + "°" : null, { alt: c.nozul_hedef ? `hedef ${Number(c.nozul_hedef).toFixed(0)}°` : "hedef yok", renk: isitiyor(c.nozul, c.nozul_hedef) }),
      bilgiKart("bed", "Tabla", c.tabla != null ? Number(c.tabla).toFixed(0) + "°" : null, { alt: c.tabla_hedef ? `hedef ${Number(c.tabla_hedef).toFixed(0)}°` : "hedef yok", renk: isitiyor(c.tabla, c.tabla_hedef) }),
      bilgiKart("box", "Kabin", c.kabin != null ? Number(c.kabin).toFixed(0) + "°" : null, { alt: c.kabin_hedef ? `hedef ${Number(c.kabin_hedef).toFixed(0)}°` : "", renk: isitiyor(c.kabin, c.kabin_hedef) }),
      bilgiKart("fan", "Fan", c.fan != null ? "%" + c.fan : null, { renk: c.fan ? "var(--d-tamamlandi)" : "var(--soluk)", yuzde: c.fan != null ? Number(c.fan) : null }),
      bilgiKart("gauge", "Hız", c.hiz_yuzde != null ? "%" + c.hiz_yuzde : null, { renk: "var(--d-hazirlaniyor)", yuzde: c.hiz_yuzde != null ? Math.min(100, Number(c.hiz_yuzde)) : null }),
      bilgiKart(c.isik ? "bulb" : "bulb-off", "Işık", c.isik == null ? null : (c.isik ? "Açık" : "Kapalı"), { renk: c.isik ? "var(--d-duraklatildi)" : "var(--soluk)" }),
      bilgiKart("spool", "CFS", c.cfs_bagli ? "Bağlı" : "Yok", { renk: c.cfs_bagli ? "var(--d-basiyor)" : "var(--soluk)", pasifBos: false }),
      bilgiKart("wifi", "Bağlantı", c.baglanti === "bagli" ? "Bağlı" : (c.baglanti === "baglaniyor" ? "Bağlanıyor" : "Kopuk"), { alt: c.son_veri ? "son veri " + saat(c.son_veri) : (c.son_hata || ""), renk: c.baglanti === "bagli" ? "var(--d-basiyor)" : "var(--d-hata)", pasifBos: false }),
      bilgiKart(c.hata_kodu ? "alert" : "check", "Hata", c.hata_kodu ? ((st.ayHata && st.ayHata.bilinen) ? st.ayHata.metin : `Kod ${c.hata_anahtari || c.hata_kodu}`) : "Yok", { alt: c.hata_kodu ? (st.ayHata && st.ayHata.sinif ? st.ayHata.sinif + " · kod " + (c.hata_anahtari || c.hata_kodu) : "ayrıntı: Yazıcı Hataları") : "sorun bildirilmedi", renk: c.hata_kodu ? "var(--d-hata)" : "var(--d-basiyor)", pasifBos: false, genis: !!c.hata_kodu }),
      bilgiKart("cpu", "Model", c.model_adi || c.model || y.model, { alt: c.yazilim_surumu ? "yazılım " + c.yazilim_surumu : (c.model || ""), renk: "var(--soluk)" }),
      bilgiKart("tag", "Grup", y.grup, { alt: y.notlar || "", renk: "var(--soluk)" }),
    ].join("");
    const ipucu = { basiyor: "Baskı sürüyor: Durdur ile duraklatabilir, İptal Et ile sonlandırabilirsiniz.",
      duraklatildi: "Baskı duraklatıldı: Başlat ile sürdürün ya da İptal Et ile sonlandırın.",
      cevrimdisi: "Yazıcı çevrimdışı; komut gönderilemez.", bosta: "Yazıcı boşta; yeni baskı yazıcıdan ya da Creality Print'ten başlatılır.",
      tamamlandi: "Baskı tamamlandı.", hata: "Yazıcı hata bildiriyor; yazıcı ekranını kontrol edin.", hazirlaniyor: "Yazıcı hazırlanıyor (eksen sıfırlama)." };
    $("#ay-komut-ipucu").textContent = ipucu[c.durum] || "";
    $$("#ortu-ayrinti [data-komut]").forEach(b => {
      const k = b.dataset.komut, d = c.durum;
      b.disabled = d === "cevrimdisi" || (k === "duraklat" && d !== "basiyor") || (k === "surdur" && d !== "duraklatildi") || (k === "durdur" && !["basiyor", "duraklatildi", "hazirlaniyor"].includes(d));
    });
    const f = $("#ay-form");
    if (!f.dataset.id || Number(f.dataset.id) !== y.id) {
      f.dataset.id = y.id; f.ad.value = y.ad; f.ip.value = y.ip; f.port.value = y.port; f.http_port.value = y.http_port || 80;
      f.grup.value = y.grup || ""; f.notlar.value = y.notlar || ""; f.etkin.checked = !!y.etkin;
    }
  }
  $("#ay-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, id = Number(f.dataset.id);
    try {
      await put(`/api/yazicilar/${id}`, { ad: f.ad.value, ip: f.ip.value, port: Number(f.port.value) || 9999, http_port: Number(f.http_port.value) || 80, grup: f.grup.value, notlar: f.notlar.value, etkin: f.etkin.checked });
      bildir("Kaydedildi");
    } catch (err) { bildir(err.message); }
  });
  $("#ay-sil").addEventListener("click", async () => {
    const id = Number($("#ay-form").dataset.id), y = st.yazicilar.get(id);
    if (!y || !confirm(`${y.ad} (${y.ip}) silinsin mi?`)) return;
    try { await del(`/api/yazicilar/${id}`); kapat("ortu-ayrinti"); } catch (err) { bildir(err.message); }
  });
  $$("#ortu-ayrinti [data-komut]").forEach(b => b.addEventListener("click", async () => {
    const id = st.acikYazici, komut = b.dataset.komut;
    if (komut === "durdur" && !confirm("Baskı iptal edilsin mi? Bu işlem geri alınamaz.")) return;
    try {
      const v = await post(`/api/yazicilar/${id}/komut`, { komut, deger: b.dataset.deger != null ? Number(b.dataset.deger) : null });
      bildir(v.gonderildi ? "Komut gönderildi" : "Gönderilemedi: yazıcı bağlı değil");
    } catch (err) { bildir(err.message); }
  }));

  // ---------- sihirbaz ----------
  function adim(n) {
    $$("#ortu-sihirbaz .adim").forEach(s => s.hidden = Number(s.dataset.adim) !== n);
    $$("#ortu-sihirbaz .adimlar li").forEach(l => l.classList.toggle("aktif", Number(l.dataset.adim) === n));
  }
  async function sihirbazAc() {
    ac("ortu-sihirbaz");
    if (st.tarama && ["hazir", "port", "kimlik"].includes(st.tarama.asama)) { adim(2); taramaGuncelle(); return; }
    adim(1);
    try {
      const v = await api("/api/aglar");
      $("#ag-listesi").innerHTML = v.aglar.map((a, i) =>
        `<label><input type="radio" name="ag" value="${kacis(a.cidr)}" ${i === 0 ? "checked" : ""}> ${kacis(a.cidr)} <small>${kacis(a.arayuz || "")} · bu makine ${kacis(a.ip)} · ${a.host_sayisi} adres</small></label>`).join("") ||
        '<p class="ipucu">Arayüz bulunamadı; CIDR girin.</p>';
      if (v.aglar[0] && !$("#cidr").value) $("#cidr").value = v.aglar[0].cidr;
      $$("input[name=ag]").forEach(r => r.addEventListener("change", () => { $("#cidr").value = r.value; }));
    } catch (e) { bildir(e.message); }
  }
  $("#btn-tara").addEventListener("click", async () => {
    const cidr = $("#cidr").value.trim(), port = Number($("#tarama-port").value) || 9999;
    if (!cidr) { bildir("CIDR girin"); return; }
    try { await post("/api/tarama", { cidr, port }); adim(2); $("#btn-tarama-ileri").disabled = true; }
    catch (e) { bildir(e.message); }
  });
  $("#btn-tarama-iptal").addEventListener("click", () => post("/api/tarama/iptal").catch(() => {}));
  $("#btn-tarama-ileri").addEventListener("click", () => { adim(3); sonucCiz(); });
  $("#btn-yeniden-tara").addEventListener("click", () => adim(1));
  $("#btn-elle-ekle").addEventListener("click", async () => {
    const ip = $("#elle-ip").value.trim(), ad = $("#elle-ad").value.trim();
    if (!ip) { bildir("IP girin"); return; }
    try { await post("/api/yazicilar", { ip, ad, port: Number($("#tarama-port").value) || 9999 }); bildir("Eklendi"); $("#elle-ip").value = ""; $("#elle-ad").value = ""; }
    catch (e) { bildir(e.message); }
  });
  function taramaGuncelle() {
    const t = st.tarama; if (!t) return;
    const yuzde = t.toplam ? Math.round(100 * t.taranan / t.toplam) : 0;
    $("#tarama-cubuk").value = t.asama === "port" ? yuzde : (t.asama === "hazir" ? 0 : 100);
    const metin = {
      hazir: "Hazırlanıyor…", port: `${t.cidr} taranıyor: ${t.taranan} / ${t.toplam} adres, ${t.bulunan.length} açık port`,
      kimlik: "Yanıt veren cihazlara kimlik soruluyor…", bitti: `Tarama bitti: ${t.bulunan.length} yazıcı bulundu`,
      iptal: "Tarama iptal edildi", hata: "Hata: " + t.hata,
    }[t.asama] || t.asama;
    $("#tarama-metin").textContent = metin;
    $("#tarama-ipucu").textContent = t.asama === "port" ? "Tipik bir /24 ağ 5–10 saniyede taranır." : "";
    const bitti = ["bitti", "iptal", "hata"].includes(t.asama);
    $("#btn-tarama-ileri").disabled = !bitti;
    $("#btn-tarama-iptal").disabled = bitti;
    if (bitti && !$("#ortu-sihirbaz").hidden && !$('#ortu-sihirbaz .adim[data-adim="2"]').hidden && t.asama === "bitti") { adim(3); sonucCiz(); }
  }
  function sonucCiz() {
    const t = st.tarama, tb = $("#sonuc-tablo tbody");
    if (!t) return;
    $("#sonuc-metin").textContent = t.bulunan.length ? `${t.cidr} içinde ${t.bulunan.length} yazıcı bulundu. Eklemek istediklerinizi seçin, ad verin.` : "Bu ağda yanıt veren yazıcı bulunamadı. Yazıcıların açık ve aynı ağda olduğundan emin olun.";
    tb.innerHTML = t.bulunan.map(b => `
      <tr class="${b.kayitli ? "kayitli" : ""}" data-ip="${kacis(b.ip)}">
        <td><input type="checkbox" class="sec" ${b.kayitli ? "disabled" : "checked"}></td>
        <td>${kacis(b.ip)}</td><td>${kacis(b.hostname || "–")}</td><td>${kacis(b.model || "–")}</td>
        <td><input type="text" class="ad" value="${kacis(b.hostname || b.ip)}" ${b.kayitli ? "disabled" : ""}></td>
        <td><input type="text" class="grup" placeholder="isteğe bağlı" ${b.kayitli ? "disabled" : ""}></td>
        <td>${b.kayitli ? "Zaten kayıtlı" : (b.hata ? "Kimlik alınamadı" : "Yeni")}</td>
      </tr>`).join("");
  }
  $("#tumu-sec").addEventListener("change", (e) => $$("#sonuc-tablo .sec:not(:disabled)").forEach(c => c.checked = e.target.checked));
  $("#btn-ekle").addEventListener("click", async () => {
    const secilen = $$("#sonuc-tablo tbody tr").filter(tr => $(".sec", tr).checked && !$(".sec", tr).disabled).map(tr => {
      const b = st.tarama.bulunan.find(x => x.ip === tr.dataset.ip) || {};
      return { ip: tr.dataset.ip, ad: $(".ad", tr).value, grup: $(".grup", tr).value, port: b.port, model: b.model, hostname: b.hostname };
    });
    if (!secilen.length) { bildir("Seçim yapın"); return; }
    try {
      const v = await post("/api/yazicilar/toplu", { yazicilar: secilen });
      bildir(`${v.eklenen.length} yazıcı eklendi${v.atlanan.length ? ", " + v.atlanan.length + " atlandı" : ""}`);
      kapat("ortu-sihirbaz");
    } catch (e) { bildir(e.message); }
  });

  // ---------- Telegram bildirimleri ----------
  let tgAyar = null;
  async function bildirimAc() {
    try { tgAyar = (await api("/api/ayarlar/telegram")).telegram; tgDoldur(); }
    catch (e) { bildir(e.message); }
  }
  function tgDoldur() {
    const f = $("#tg-form"), a = tgAyar;
    f.token.value = "";
    f.token.placeholder = a.token_var ? `kayıtlı: ${a.token_maske} (değiştirmek için yenisini yazın)` : "123456789:AA…";
    const td = $("#tg-token-durum");
    if (!a.token_var) { td.textContent = "Belirteç girilmemiş."; td.className = "ipucu"; }
    else if (!a.token_gecerli) { td.textContent = `Kayıtlı belirteç (${a.token_maske}) geçersiz biçimde! BotFather'ın verdiği satırı yeniden yapıştırıp kaydedin.`; td.className = "ipucu olay-kritik"; }
    else { td.textContent = "Belirteç kayıtlı" + (a.bot_adi ? ` · bot @${a.bot_adi}` : "") + "."; td.className = "ipucu"; }
    f.sohbetler.value = a.sohbetler.join(", ");
    f.yonetici_sohbetler.value = (a.yonetici_sohbetler || []).join(", ");
    f.etkin.checked = a.etkin;
    $("#tg-olaylar").innerHTML = a.secilebilir.map(o =>
      `<label><input type="checkbox" name="olay" value="${o.tur}" ${a.olaylar.includes(o.tur) ? "checked" : ""}> ${kacis(o.ad)}</label>`).join("");
    $("#tg-sohbet-liste").innerHTML = "";
    tgDurum();
  }
  function tgDurum() {
    const a = tgAyar, d = $("#tg-durum");
    if (!a) return;
    if (a.son_hata) { d.textContent = "Son hata: " + a.son_hata; d.className = "ipucu olay-kritik"; }
    else if (a.son_gonderim) { d.textContent = `Son gönderim ${saat(a.son_gonderim)} · toplam ${a.gonderilen}`; d.className = "ipucu"; }
    else { d.textContent = a.etkin ? "Henüz gönderim yok." : "Devre dışı."; d.className = "ipucu"; }
  }
  function tgForm() {
    const f = $("#tg-form");
    return { token: f.token.value.trim(), sohbetler: f.sohbetler.value, yonetici_sohbetler: f.yonetici_sohbetler.value, etkin: f.etkin.checked,
             olaylar: $$("#tg-olaylar input:checked").map(i => i.value) };
  }
  $("#tg-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await put("/api/ayarlar/telegram", tgForm());
      tgAyar = r.telegram; tgDoldur();
      bildir(r.uyari ? r.uyari : "Bildirim ayarları kaydedildi" + (tgAyar.bot_adi ? ` · bot @${tgAyar.bot_adi} doğrulandı` : ""), r.uyari ? 8000 : 4000);
    } catch (err) { bildir(err.message, 8000); }
  });
  $("#tg-test").addEventListener("click", async () => {
    const v = tgForm(), b = $("#tg-test"); b.disabled = true;
    try {
      const r = await post("/api/ayarlar/telegram/test", { token: v.token, sohbetler: v.sohbetler.split(",").map(s => s.trim()).filter(Boolean) });
      bildir(r.basarili ? "Test mesajı gönderildi, Telegram'ı kontrol edin" : "Gönderilemedi: " + r.hatalar.join("; "), 6000);
    } catch (err) { bildir(err.message, 6000); }
    finally { b.disabled = false; }
  });
  $("#tg-sohbet-bul").addEventListener("click", async () => {
    const b = $("#tg-sohbet-bul"); b.disabled = true;
    try {
      const r = await post("/api/ayarlar/telegram/sohbetler", { token: tgForm().token });
      const kap = $("#tg-sohbet-liste");
      if (!r.sohbetler.length) { kap.innerHTML = `<p class="ipucu">Bot @${kacis(r.bot.kullanici_adi)} bulundu ama henüz mesaj almamış. Telegram'da bota /start yazıp yeniden deneyin.</p>`; return; }
      kap.innerHTML = `<p class="ipucu">Bot @${kacis(r.bot.kullanici_adi)} · bota yazan sohbetler (eklemek için tıklayın):</p>` +
        r.sohbetler.map(s => `<label><input type="checkbox" data-id="${kacis(s.id)}"> ${kacis(s.ad)} <small>${kacis(s.tur)} · ${kacis(s.id)}</small></label>`).join("");
      $$("#tg-sohbet-liste input").forEach(i => i.addEventListener("change", () => {
        const f = $("#tg-form"), mevcut = f.sohbetler.value.split(",").map(x => x.trim()).filter(Boolean);
        const id = i.dataset.id, idx = mevcut.indexOf(id);
        if (i.checked && idx < 0) mevcut.push(id); if (!i.checked && idx >= 0) mevcut.splice(idx, 1);
        f.sohbetler.value = mevcut.join(", ");
      }));
    } catch (err) { bildir(err.message, 6000); }
    finally { b.disabled = false; }
  });

  // ---------- kullanıcılar ----------
  let roller = {};
  async function kullanicilarAc() {
    try { const v = await api("/api/kullanicilar"); roller = v.roller; kullaniciTablo(v.kullanicilar); }
    catch (e) { bildir(e.message); }
  }
  function kullaniciTablo(liste) {
    $("#kullanici-tablo tbody").innerHTML = liste.map(k => {
      const ben = st.ben && k.id === st.ben.id;
      const rolSec = Object.entries(roller).map(([r, a]) => `<option value="${r}" ${k.rol === r ? "selected" : ""}>${kacis(a)}</option>`).join("");
      return `<tr data-id="${k.id}">
        <td>${kacis(k.kullanici_adi)}${ben ? ' <small class="ipucu">(siz)</small>' : ""}</td>
        <td><input type="text" class="ad" value="${kacis(k.ad)}"></td>
        <td><select class="rol" ${ben ? "disabled" : ""}>${rolSec}</select></td>
        <td><input type="checkbox" class="etkin" ${k.etkin ? "checked" : ""} ${ben ? "disabled" : ""}></td>
        <td class="ipucu">${k.son_giris ? new Date(k.son_giris * 1000).toLocaleString("tr-TR") : "–"}</td>
        <td class="eylem"><button class="btn" data-eylem="gecmis">Geçmiş</button> <button class="btn" data-eylem="kaydet">Kaydet</button> <button class="btn" data-eylem="parola">Parola</button> ${ben ? "" : '<button class="btn btn-tehlike" data-eylem="sil">Sil</button>'}</td>
      </tr>`;
    }).join("");
  }
  $("#kullanici-tablo").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-eylem]"); if (!b) return;
    const tr = b.closest("tr"), id = Number(tr.dataset.id), ben = st.ben && id === st.ben.id;
    try {
      if (b.dataset.eylem === "gecmis") { await gecmisAc(id); return; }
      if (b.dataset.eylem === "kaydet") {
        const govde = { ad: $(".ad", tr).value };
        if (!ben) { govde.rol = $(".rol", tr).value; govde.etkin = $(".etkin", tr).checked; }
        await put(`/api/kullanicilar/${id}`, govde); bildir("Kaydedildi");
      } else if (b.dataset.eylem === "parola") {
        const p = prompt("Bu kullanıcı için yeni parola (en az 8 karakter):"); if (!p) return;
        await put(`/api/kullanicilar/${id}`, { parola: p }); bildir("Parola değiştirildi; kullanıcının oturumları kapatıldı");
      } else if (b.dataset.eylem === "sil") {
        if (!confirm(`${$("td", tr).textContent.trim()} silinsin mi?`)) return;
        await del(`/api/kullanicilar/${id}`); bildir("Silindi");
      }
      kullaniciTablo((await api("/api/kullanicilar")).kullanicilar);
    } catch (err) { bildir(err.message, 6000); }
  });
  $("#yeni-kullanici").addEventListener("submit", async (e) => {
    e.preventDefault(); const f = e.target;
    try {
      await post("/api/kullanicilar", { kullanici_adi: f.kullanici_adi.value.trim(), ad: f.ad.value.trim(), rol: f.rol.value, parola: f.parola.value });
      f.reset(); bildir("Kullanıcı eklendi"); kullaniciTablo((await api("/api/kullanicilar")).kullanicilar);
    } catch (err) { bildir(err.message, 6000); }
  });
  const EYLEM_AD_EK = {};
  const EYLEM_AD = { giris: "Giriş yaptı", giris_basarisiz: "Başarısız giriş", cikis: "Çıkış yaptı", kurulum: "İlk kurulum",
    parola_degistirdi: "Parolasını değiştirdi", kullanici_ekledi: "Kullanıcı ekledi", kullanici_guncelledi: "Kullanıcı güncelledi", kullanici_sildi: "Kullanıcı sildi",
    yazici_ekledi: "Yazıcı ekledi", yazici_guncelledi: "Yazıcı güncelledi", yazici_sildi: "Yazıcı sildi", tarama_baslatti: "Ağ taraması başlattı",
    bildirim_ayarladi: "Bildirim ayarı değiştirdi", bildirim_test: "Bildirim testi gönderdi", tarama_iptal: "Ağ taramasını iptal etti", komut_duraklat: "Baskıyı durdurdu (duraklattı)", komut_surdur: "Baskıyı başlattı (sürdürdü)",
    komut_durdur: "Baskıyı iptal etti", komut_isik: "Işığı değiştirdi", komut_nozul: "Nozul sıcaklığı ayarladı", komut_tabla: "Tabla sıcaklığı ayarladı",
    komut_fan: "Fan ayarladı", dosya_yukledi: "Dosya yükledi ve yazdırdı", dosya_yukleme_hatasi: "Dosya yükleme HATASI", hata_kodu_kaydetti: "Hata kodu ekledi/güncelledi", hata_kodu_sildi: "Hata kodu sildi", hata_kodu_ice_aktardi: "Hata kodu tablosu içe aktardı" };
  async function gecmisAc(id) {
    try {
      const v = await api(id == null ? "/api/kullanicilar/gecmis?limit=1000" : `/api/kullanicilar/${id}/gecmis`);
      $("#gecmis-baslik").textContent = id == null ? "Tüm kullanıcıların işlem geçmişi" : `İşlem geçmişi — ${v.kullanici.ad || v.kullanici.kullanici_adi} (${v.kullanici.kullanici_adi})`;
      $("#gecmis-tablo tbody").innerHTML = v.gecmis.map(g => `<tr class="${g.eylem === "komut_durdur" || g.eylem === "giris_basarisiz" ? "kritik" : ""}">
        <td class="zaman">${new Date(g.zaman * 1000).toLocaleString("tr-TR")}</td><td>${kacis(g.kullanici_adi)}</td>
        <td class="eylem">${kacis(EYLEM_AD[g.eylem] || g.eylem)}</td><td>${kacis(g.hedef)}</td><td>${kacis(g.ayrinti)}</td><td class="ipucu">${kacis(g.ip)}</td></tr>`).join("")
        || '<tr><td colspan="6" class="ipucu">Henüz kayıt yok.</td></tr>';
      ac("ortu-gecmis");
    } catch (e) { bildir(e.message); }
  }
  $("#btn-tum-gecmis").addEventListener("click", () => gecmisAc(null));
  $("#btn-parola").addEventListener("click", () => { menuKapat(); $("#parola-form").reset(); ac("ortu-parola"); });
  $("#parola-form").addEventListener("submit", async (e) => {
    e.preventDefault(); const f = e.target;
    if (f.yeni.value !== f.yeni2.value) { bildir("Yeni parolalar eşleşmiyor"); return; }
    try { await put("/api/ben/parola", { eski: f.eski.value, yeni: f.yeni.value }); kapat("ortu-parola"); bildir("Parolanız değiştirildi"); }
    catch (err) { bildir(err.message, 6000); }
  });
  $("#btn-cikis").addEventListener("click", async () => {
    if (st.ws) { st.ws.onclose = null; st.ws.close(); }
    try { await post("/api/cikis"); } finally { location.href = "/giris"; }
  });

  // ---------- hata kodları yönetimi (sistem yöneticisi) ----------
  let hkListe = [];
  async function hataKodlariAc() {
    try { const v = await api("/api/hata_kodlari"); hkListe = v.liste; hkBilgi(v.bilgi); hkTablo(); }
    catch (e) { bildir(e.message); }
  }
  function hkBilgi(b) { $("#hk-bilgi").textContent = `${b.adet} kod · kaynak: ${b.kaynak || "–"} · güncelleme: ${b.guncelleme || "–"}`; }
  function hkTablo() {
    const q = $("#hk-arama").value.trim().toLowerCase();
    const liste = hkListe.filter(k => !q || `${k.kod} ${k.tam_kod} ${k.baslik} ${k.modul} ${k.aciklama} ${k.cozum}`.toLowerCase().includes(q));
    $("#hk-tablo tbody").innerHTML = liste.map(k => `<tr data-kod="${kacis(k.kod)}">
      <td class="kod"><input name="tam_kod" value="${kacis(k.tam_kod || k.kod)}"><div class="ipucu">${kacis(k.kod)}</div></td>
      <td><input name="modul" value="${kacis(k.modul || "")}"></td>
      <td><textarea name="baslik">${kacis(k.baslik || "")}</textarea></td>
      <td><textarea name="aciklama">${kacis(k.aciklama || "")}</textarea></td>
      <td><textarea name="cozum">${kacis(k.cozum || "")}</textarea></td>
      <td class="eylem"><button class="btn" data-eylem="kaydet">Kaydet</button> <button class="btn btn-tehlike" data-eylem="sil">Sil</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="ipucu">${q ? "Eşleşen kod yok." : "Tablo boş."}</td></tr>`;
  }
  $("#hk-arama").addEventListener("input", hkTablo);
  $("#hk-tablo").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-eylem]"); if (!b) return;
    const tr = b.closest("tr"), kod = tr.dataset.kod;
    try {
      if (b.dataset.eylem === "sil") { if (!confirm(`${kod} kodu tablodan silinsin mi?`)) return; const v = await del(`/api/hata_kodlari/${kod}`); hkBilgi(v.bilgi); bildir("Silindi"); }
      else { const g = {}; tr.querySelectorAll("input,textarea").forEach(i => g[i.name] = i.value); const v = await put(`/api/hata_kodlari/${kod}`, g); hkBilgi(v.bilgi); bildir(`${v.kayit.tam_kod} kaydedildi`); }
      hkListe = (await api("/api/hata_kodlari")).liste; hkTablo();
    } catch (err) { bildir(err.message, 6000); }
  });
  $("#hk-yeni").addEventListener("submit", async (e) => {
    e.preventDefault(); const f = e.target;
    try {
      const v = await put(`/api/hata_kodlari/${encodeURIComponent(f.tam_kod.value.trim())}`, { tam_kod: f.tam_kod.value.trim().toUpperCase(), modul: f.modul.value, baslik: f.baslik.value, cozum: f.cozum.value });
      hkBilgi(v.bilgi); f.reset(); bildir(`${v.kayit.tam_kod} eklendi`); hkListe = (await api("/api/hata_kodlari")).liste; hkTablo();
    } catch (err) { bildir(err.message, 6000); }
  });
  $("#hk-dosya").addEventListener("change", async () => {
    const dosya = $("#hk-dosya").files[0]; if (!dosya) return;
    const fd = new FormData(); fd.append("file", dosya, dosya.name);
    try {
      const r = await fetch("/api/hata_kodlari/ice_aktar", { method: "POST", body: fd }); const v = await r.json();
      if (!r.ok) throw new Error(v.hata || r.statusText);
      bildir(`${v.alinan} kod alındı, tabloda ${v.toplam} kod`, 6000); hkBilgi(v.bilgi); hkListe = (await api("/api/hata_kodlari")).liste; hkTablo();
    } catch (err) { bildir(err.message, 8000); }
    $("#hk-dosya").value = "";
  });
  $("#yenileme-sn").addEventListener("change", async () => {
    const sn = Number($("#yenileme-sn").value) || 1; yenilemeKur(sn); yenilemeUygula();
    try { await put("/api/ben/tercihler", { yenileme_sn: sn }); if (st.ben) st.ben.tercihler = Object.assign({}, st.ben.tercihler, { yenileme_sn: sn }); } catch (e) { bildir(e.message); }
  });
  yenilemeKur(1);

  // ---------- genel ----------
  function ac(id) { $("#" + id).hidden = false; }
  function kapat(id) { $("#" + id).hidden = true; if (id === "ortu-ayrinti") { st.acikYazici = null; st.ayHata = null; $("#ay-form").dataset.id = ""; ayMenuKapat(); } }
  $$("[data-kapat]").forEach(b => b.addEventListener("click", () => kapat(b.dataset.kapat)));
  $$(".ortu").forEach(o => o.addEventListener("click", (e) => { if (e.target === o) kapat(o.id); }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".ortu").forEach(o => { if (!o.hidden) kapat(o.id); }); });
  $("#kartlar").addEventListener("click", (e) => { const k = e.target.closest(".kart"); if (k) ayrintiAc(Number(k.dataset.id)); });
  $("#sade").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) ayrintiAc(Number(tr.dataset.id)); });
  let yukleHedef = null;
  $("#yukle").addEventListener("click", (e) => {
    const b = e.target.closest(".dosya-btn");
    const k = e.target.closest(".ykart"); if (!k) return;
    if (b && !b.disabled) { yukleHedef = Number(k.dataset.id); $("#dosya-secici").value = ""; $("#dosya-secici").click(); return; }
    if (!b) ayrintiAc(Number(k.dataset.id));
  });
  $("#dosya-secici").addEventListener("change", () => {
    const dosya = $("#dosya-secici").files[0], id = yukleHedef, y = st.yazicilar.get(id);
    if (!dosya || !y) return;
    const c = y.canli || {}, mesaj = (c.durum === "basiyor" || c.durum === "duraklatildi")
      ? `DİKKAT: ${y.ad} şu an "${c.dosya}" basıyor (%${Math.round(c.ilerleme || 0)}).\n\nBu işlem mevcut işlemi durduracak ve "${dosya.name}" dosyasını yazdırmaya başlayacak.\n\nDevam edilsin mi?`
      : `${y.ad} yazıcısına "${dosya.name}" yüklenip yazdırılacak.\n\nBu işlem mevcut işlemi durduracak. Devam edilsin mi?`;
    if (!confirm(mesaj)) return;
    dosyaYukle(id, dosya);
  });
  function dosyaYukle(id, dosya) {
    const y = st.yazicilar.get(id); if (!y) return;
    yuklemeler.set(id, { yuzde: 0, metin: `Yükleniyor: ${dosya.name}` }); cizKart(y);
    const fd = new FormData(); fd.append("file", dosya, dosya.name); fd.append("baslat", "1");
    const xhr = new XMLHttpRequest(); xhr.open("POST", `/api/yazicilar/${id}/dosya`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { yuklemeler.set(id, { yuzde: Math.round(100 * e.loaded / e.total), metin: `Yükleniyor: ${dosya.name} (%${Math.round(100 * e.loaded / e.total)})` }); cizKart(st.yazicilar.get(id)); } };
    xhr.onload = () => {
      yuklemeler.delete(id); cizKart(st.yazicilar.get(id));
      let v = {}; try { v = JSON.parse(xhr.responseText); } catch (e) { /* boş */ }
      if (xhr.status === 401) { location.href = "/giris"; return; }
      if (xhr.status >= 200 && xhr.status < 300) bildir(v.baslatildi ? `${y.ad}: ${v.dosya_adi} yüklendi, baskı başlatıldı` : `${y.ad}: ${v.dosya_adi} yüklendi ama baskı başlatılamadı (bağlantı yok)`, 6000);
      else bildir(`${y.ad}: yükleme başarısız — ${v.hata || xhr.statusText}`, 8000);
    };
    xhr.onerror = () => { yuklemeler.delete(id); cizKart(st.yazicilar.get(id)); bildir(`${y.ad}: yükleme sırasında ağ hatası`, 8000); };
    xhr.send(fd);
  }
  $$(".uyg[data-modul]").forEach(b => b.addEventListener("click", () => modulAc(b.dataset.modul)));
  $("#btn-uygulamalar").addEventListener("click", (e) => { e.stopPropagation(); const m = $("#menu-uygulamalar"), acik = m.hidden; menuKapat(); m.hidden = !acik; $("#btn-uygulamalar").classList.toggle("acik", acik); });
  $("#btn-avatar").addEventListener("click", (e) => { e.stopPropagation(); const m = $("#menu-hesap"), acik = m.hidden; menuKapat(); m.hidden = !acik; });
  document.addEventListener("click", (e) => { if (!e.target.closest(".acilir")) menuKapat(); });
  $("#sayaclar").addEventListener("click", (e) => { const s = e.target.closest(".sayac"); if (!s) return; $("#filtre-durum").value = s.dataset.d || ""; if (!MODUL_GORUNUM[st.modul]) modulAc("yazicilar"); else cizHepsi(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") menuKapat(); });
  ["#arama", "#filtre-durum", "#filtre-grup"].forEach(s => $(s).addEventListener("input", cizHepsi));
  $("#btn-sihirbaz").addEventListener("click", sihirbazAc);
  $("#btn-sihirbaz-2").addEventListener("click", sihirbazAc);

  api("/api/surum").then(v => { $("#surum").textContent = `${v.urun} ${v.surum}`; }).catch(() => {});
  api("/api/ben").then(v => { st.ben = v.kullanici; rolUygula(); wsBaglan(); }).catch(() => {});
})();
