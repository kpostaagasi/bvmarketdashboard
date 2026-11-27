"""EİB (Ege İhracatçı Birlikleri) Su Ürünleri ve Hayvansal Mamuller
İhracatçıları Birliği (ESÜHMİB) aylık ihracat istatistiği istemcisi.

Kaynak sayfası (`https://www.eib.org.tr/Sayfa.Asp?id=AF5247B95C`, "İstatistikler")
JS ile render ediliyor (SPA) — ama arkasındaki içerik `requests` ile de
çekilebiliyor: sayfanın kendi `assets/api.js`'i içeriği
`GET /Sayfa_Icerik_JSON.Asp?SI_Id=AF5247B95C` ile çekiyor ve dönen JSON'un
`icerik` alanı, yıl başına `<h3>YIL</h3>` ile bölünmüş, ay başına kısa
bağlantılar (`eib.li/XXXXX`) taşıyan düz HTML. Bir kısa bağlantı bozuk geldi
(ölçüldü, Şubat 2024: `http://https//eib.li/BE6FE`) — `_eib_li_duzelt`
kod kısmını regex ile çıkarıp temiz URL'i yeniden kurar.

Her ayın "EİB Aylık" bağlantısı KÜMÜLATİFTİR: örn. Ağustos 2026 dosyası
Ocak–Ağustos 2026'nın TAMAMINI (ay ay) taşır, tek dosya indirmek o yılın
o ana kadarki tüm aylarını verir (ölçüldü: Ağustos dosyasının ham veri
sayfasında "Aylar" sütununda OCAK..AĞUSTOS'un hepsi var). Bu yüzden yıl
başına TEK indirme yeterli — tim.py'deki "yıl başına tek bülten" deseniyle
aynı mantık: geçmiş yıllar için ARALIK, cari yıl için yayımlanan en son ay.

Ham veri her yılın dosyasında AYRI bir sayfada ("GTIP ULKE GB TARIH" ya da
"Sayfa1" — sayfa ADI yıldan yıla değişiyor, bu yüzden `_ham_veri_sayfasini_bul`
başlık satırının ilk hücresi "AYLAR" olan sayfayı arar) satır bazlı GTİP
kayıtları olarak geliyor: `Aylar, ürün grubu, alt grup 1, ..., AGIRLIK
(KG), FOBUSD, ...`. "ürün grubu" == "SU ÜRÜNLERİ" olan satırların "alt
grup 1"i Levrek/Çipura/Türk Somonu/Alabalık/Kaya Levreği/Diğer Su
Ürünleri/(nadiren) Orkinos gibi ürünlere ayrılıyor.

**Format kırılması (ölçüldü 2026-09-18): "alt grup 1" kırılımı yalnızca
2025 Ocak'tan itibaren var.** 2024 dosyasında "alt grup 1" sütunu SU
ÜRÜNLERİ'yi tekrarlıyor (gerçek kırılım yok) ve ham veri sayfası farklı bir
şema taşıyor (ekstra "alt grup 3" sütunu, TİM/EPDK tarzı bir format
değişimi). Bu yüzden `ILK_YIL = 2025` — TİM/EPDK'nın "yalnızca stabil
formatın geçerli olduğu pencere" ilkesiyle aynı karar.

Ürün kırılımı: Levrek/Çipura/Türk Somonu/Alabalık/Kaya Levreği DOĞRUDAN
izlenir; geri kalan HER ŞEY (kaynağın kendi "Diğer Su Ürünleri" satırı dahil,
nadiren görülen Orkinos gibi kalemler dahil) `DİĞER SU ÜRÜNLERİ` = SU
ÜRÜNLERİ toplamı − 5 adlandırılmış ürün olarak HESAPLANIR — kaynak yeni bir
ürün eklerse (Orkinos gibi) adaptör değişmeden otomatik "diğer"e düşer.
Ölçüldü (Ağustos 2026): Levrek 56.4262 mn$, Çipura 42.9848 mn$ — MarketVisuals
`eib_balikcilik.html` referans değerleriyle birebir.

Hayvansal 8 ana grup (Kanatlı, Yumurta, Süt ve Süt Ürünleri, Sosis ve
Benzeri Ürünler, Bal, Diğer, Canlı Hayvan, Kırmızı Et ve Sakatat) doğrudan
"ürün grubu" adlarıyla izlenir. `HAYVANSAL_TOPLAM` bu 8 grubun TOPLANMASIYLA
hesaplanır (kaynağın "Genel Toplam"ı SU ÜRÜNLERİ'ni de içerdiğinden
doğrudan kullanılamaz — ihracat-il/ihracat-ulke'deki "toplamı adaptör
hesaplar" deseniyle aynı).

# ponytail: "DİĞER ETLER" grubu bilinçli DIŞARIDA bırakıldı — yıl içinde
yalnızca birkaç ayda satırı var (ör. Haziran 2026), kalan aylarda satırın
kendisi YOK (sıfır değil, yokluk — kaynak sıfır satırı hiç yazmıyor). Sürekli
bir seri olarak izlenemeyecek kadar seyrek; HAYVANSAL_TOPLAM o birkaç ayda
birkaç bin dolar eksik kalabilir. Kaynak sürekli aylık satır yayımlamaya
başlarsa `HAYVANSAL_GRUPLARI`'na eklenir.

Ağustos 2026 ölçümü (kaynakla birebir): SU ÜRÜNLERİ toplam FOBUSD
146.033.708,42 (146,0337 mn$), AGIRLIK 17.242.615,26 kg (17,2426 bin ton);
HAYVANSAL_TOPLAM FOBUSD 29.949.152,00 (29,9492 mn$), AGIRLIK 19.326.789,59 kg
(19,3268 bin ton); Kanatlı 14.893.488,38 (14,8935 mn$); Yumurta
8.610.178,29 (8,6102 mn$); Süt ve Süt Ürünleri 2.982.044,51 (2,9820 mn$).

Ham AGIRLIK KG'dir — EPDK'daki gibi adaptör TONA çevirir (/1000); "Bin ton"
gösterimi katalogdaki `olcek: 0.001` ile. FOBUSD zaten USD; "Milyon USD"
gösterimi `olcek: 0.000001` ile.

**Sessiz atlama yok (teslim notu bakım işi, 2026-11-27).** 2026-11-13
taraması bu adaptörü "bir ayı okuyamayınca sessizce atlıyor" diye işaretledi;
canlı kaynakta doğrulandı: 2026 Eylül/Ekim etiketleri `Eyl&uuml;l:&nbsp;` ve
`Ekim:&nbsp;` (HTML entity + bölünmez boşluk) olarak yazılıyor, eski regex ve
`AY_ESLEME` bunları tanımadığı için cari yıl Ağustos dosyasında kalıyordu —
CSV'ler 2026-08'de bitiyordu, Eylül ve Ekim yayımlanmış ama panoda yoktu.
Kural artık şu: "henüz yayımlanmadı" (cari yılın başlığı/ayları henüz yok;
yeni biten yılın Aralık dosyası `ARALIK_YAYIN_TOLERANSI_AY` ay boyunca
gelmemiş olabilir; cari yılın başlığı/ayları yalnızca
`CARI_YIL_YAYIN_TOLERANSI_AY` ay boyunca yok sayılabilir) sessiz ve
meşrudur; "var ama okunamadı" (tanınmayan ay etiketi, ayrışmayan bağlantı,
ayrışmayan `<h3>` yıl başlığı, aynı yılda iki kez geçen ay etiketi, geçmiş
yılın ya da toleransı geçmiş cari yılın başlığı/Aralığı yok, kümülatif
dosyada eksik ay, tanınmayan "Aylar" değeri, herhangi bir ayda satırı
olmayan izlenen kalem) adı ve dönemiyle yükseltilir.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import date
from io import BytesIO

import openpyxl
import pandas as pd
import requests

from ingest.http import durum_kodu_yukselt

from core.catalog import GECERLI_EIB_KALEMLERI, GECERLI_EIB_OLCUTLERI

ISTATISTIK_SI_ID = "AF5247B95C"
ICERIK_URL = "https://www.eib.org.tr/Sayfa_Icerik_JSON.Asp"
ZAMAN_ASIMI = 60

# Kaynak HTML'inin `<strong>Ay: </strong>` etiketleriyle yazdığı biçim
# (başlık-harfli); XLSX'teki "Aylar" sütunu BÜYÜK harfli — ikisi burada
# eşlenir, Türkçe İ/I büyütme tuzağına (`str.upper()`) düşmeden.
AY_ESLEME = {
    "Ocak": "OCAK", "Şubat": "ŞUBAT", "Mart": "MART", "Nisan": "NİSAN",
    "Mayıs": "MAYIS", "Haziran": "HAZİRAN", "Temmuz": "TEMMUZ",
    "Ağustos": "AĞUSTOS", "Eylül": "EYLÜL", "Ekim": "EKİM",
    "Kasım": "KASIM", "Aralık": "ARALIK",
}
AY_ADLARI = tuple(AY_ESLEME.values())
AY_NO = {ad: i + 1 for i, ad in enumerate(AY_ADLARI)}

# Su ürünleri kırılımı yalnızca 2025 Ocak'tan itibaren var (bkz. modül
# docstring'i) — 2024 ve öncesi farklı/eksik şema taşıyor.
ILK_YIL = 2025

# Yeni biten yılın ARALIK (yıl sonu kümülatif) dosyası Ocak başında hemen
# yayımlanmayabilir: `bugun.month <= ARALIK_YAYIN_TOLERANSI_AY` iken geçen
# yılın en son yayımlanan ayına düşmek "henüz yayımlanmadı" sayılır. Bu
# süreden sonra geçmiş bir yılda ARALIK yoksa yükseltilir — o yılın son
# aylarının sessizce eksik kalmasının tek yolu buydu. (Ölçüldü 2026-11-27:
# kaynak aylık dosyaları ertesi ayın ilk haftalarında ekliyor; 3 ay bol pay.)
ARALIK_YAYIN_TOLERANSI_AY = 3

# Cari yılın `<h3>YIL</h3>` başlığı ya da ilk ay (Ocak) bağlantısı yılın
# başında henüz olmayabilir: `bugun.month <= CARI_YIL_YAYIN_TOLERANSI_AY`
# iken cari yılın hiç görünmemesi "henüz yayımlanmadı" sayılır. Bu süreden
# sonra cari yılın başlığı/ayları yoksa yükseltilir — başlık biçimi
# değişirse (`<h3 class=..>2026</h3>` gibi) cari yılın tamamı sessizce
# düşer, CSV'ler bir önceki Aralık'ta biterdi (bağımsız doğrulama itirazı,
# 2026-11-27: o gün 22 satırın 10'u, `VeriKisaldiHatasi` eşiğinin altında).
# Kanıt: yukarıdaki ölçüm — Ocak dosyası Şubat'ın ilk haftalarında geliyor;
# 3 ay bol pay, `ARALIK_YAYIN_TOLERANSI_AY` ile aynı gerekçe.
CARI_YIL_YAYIN_TOLERANSI_AY = 3

SU_URUNLERI_GRUBU = "SU ÜRÜNLERİ"
SU_URUNLERI_ADLARI = ("LEVREK", "ÇİPURA", "TÜRK SOMONU", "ALABALIK", "KAYA LEVREĞİ")
DIGER_SU_URUNLERI = "DİĞER SU ÜRÜNLERİ"

HAYVANSAL_GRUPLARI = (
    "KANATLI", "YUMURTA", "SÜT VE SÜT ÜRÜNLERİ",
    "SOSİS VE BENZERİ ÜRÜNLER (KIRMIZI ET VE KANATLI)",
    "BAL", "DİĞER", "CANLI HAYVAN", "KIRMIZI ET VE SAKATAT",
)
HAYVANSAL_TOPLAM = "HAYVANSAL_TOPLAM"

assert set(SU_URUNLERI_ADLARI) | {SU_URUNLERI_GRUBU, DIGER_SU_URUNLERI} | set(HAYVANSAL_GRUPLARI) | {HAYVANSAL_TOPLAM} == GECERLI_EIB_KALEMLERI
assert {"fobusd", "agirlik"} == GECERLI_EIB_OLCUTLERI


def _eib_li_duzelt(ham_url: str) -> str:
    """Bazı kaynak bağlantıları bozuk geliyor (ölçüldü, Şubat 2024:
    `http://https//eib.li/BE6FE`). Kısa linkin kod kısmı regex ile çıkarılıp
    temiz `https://eib.li/<kod>` yeniden kurulur."""
    m = re.search(r"eib\.li/([A-Za-z0-9]+)", ham_url)
    if not m:
        raise RuntimeError(f"EİB: tanınmayan bağlantı biçimi: {ham_url!r}")
    return f"https://eib.li/{m.group(1)}"


def yillara_ayir(icerik_html: str) -> dict[str, str]:
    """`<h3>YIL</h3>` başlıklarına göre yıl bazlı HTML dilimlerine böler.

    Sayfadaki her `<h3` bir yıl başlığıdır (ölçüldü 2026-11-27: 12 başlık,
    2015–2026, hepsi katı biçimde). Katı desenle ayrışmayan bir başlık varsa
    o yılın bloğu bir önceki dilime karışıp sessizce kaybolurdu — yükseltilir.
    """
    parcalar = re.split(r"<h3>(\d{4})</h3>", icerik_html)
    toplam_baslik = len(re.findall(r"<h3\b", icerik_html, re.I))
    ayrisan = (len(parcalar) - 1) // 2
    if toplam_baslik != ayrisan:
        taninmayan = [b for b in re.findall(r"<h3\b.*?</h3>", icerik_html, re.I | re.S)
                      if not re.fullmatch(r"<h3>\d{4}</h3>", b)]
        raise RuntimeError(
            f"EİB: istatistik sayfasında {toplam_baslik} yıl başlığından yalnızca {ayrisan} "
            f"ayrıştırılabildi (tanınmayan: {taninmayan!r}) — o yılların verisi okunamadı"
        )
    return {parcalar[i]: parcalar[i + 1] for i in range(1, len(parcalar), 2)}


def _metni_normallestir(ham: str) -> str:
    """HTML parçasını düz metne indirir: etiketler atılır, entity'ler çözülür
    (`Eyl&uuml;l` → `Eylül`), bölünmez boşluk (`&nbsp;`) dahil boşluklar
    sadeleşir. Kaynak 2026 Eylül'den itibaren ay etiketlerini entity ile
    yazmaya başladı (ölçüldü 2026-11-27)."""
    metin = html.unescape(re.sub(r"<[^>]+>", "", ham)).replace("\xa0", " ")
    return " ".join(metin.split())


def ay_baglantilarini_cikar(yil_html: str, yil: int | str = "?") -> dict[str, dict[str, str]]:
    """Bir yılın HTML diliminden `{AY_ADI(XLSX biçimi): {ETİKET: url}}` çıkarır.

    Yıl dilimindeki her `<strong>` etiketi bir ay adıdır (ölçüldü 2015–2026).
    Tanınmayan bir etiket ya da ayrışmayan bir bağlantı sessizce atlanmaz:
    eskiden `Eyl&uuml;l:&nbsp;` bu yolla kayboluyordu (modül docstring'i).
    """
    sonuc: dict[str, dict[str, str]] = {}
    for ay_m in re.finditer(r"<strong>(.*?)</strong>(.*?)</p>", yil_html, re.S):
        ay_ham = _metni_normallestir(ay_m.group(1)).rstrip(":").strip()
        ay_adi = AY_ESLEME.get(ay_ham)
        if ay_adi is None:
            raise RuntimeError(
                f"EİB: tanınmayan ay etiketi {ay_m.group(1)!r} — o ayın bağlantıları okunamadı"
            )
        govde = ay_m.group(2)
        linkler: dict[str, str] = {}
        eslesmeler = list(re.finditer(r'<a\b[^>]*?\bhref="([^"]+)"[^>]*>(.*?)</a>', govde, re.S))
        if len(eslesmeler) != len(re.findall(r"<a\b", govde)):
            raise RuntimeError(f"EİB: {ay_ham} bağlantılarının bir kısmı ayrıştırılamadı: {govde!r}")
        for link_m in eslesmeler:
            etiket = _metni_normallestir(link_m.group(2))
            linkler[etiket] = _eib_li_duzelt(link_m.group(1))
        if ay_adi in sonuc:
            # Aynı ay iki kez: biri yanlış etiketli (ör. Kasım'ın "Ekim"
            # yazılması) — üzerine yazmak en yeni ayı sessizce kaybettirirdi.
            raise RuntimeError(
                f"EİB: {yil} {ay_ham} ay etiketi aynı yıl diliminde iki kez geçiyor — "
                f"ay bağlantıları belirsiz, hangisinin doğru olduğu okunamadı"
            )
        sonuc[ay_adi] = linkler
    # Ay bloğu yalnızca `<strong>…</strong>…</p>` ile bulunuyor: başka bir
    # etiketle (`<b>`, `<span>`, öznitelikli `<strong …>`) yazılmış bir ay
    # bloğu yukarıdaki döngüye hiç girmez ve en yeni ay "henüz yayımlanmadı"
    # gibi görünürdü. Ay blokları çıkarıldıktan sonra kalan HTML'de ne bir
    # `<strong` ne de metni olan bir bağlantı kalmalı. Metinsiz `<a>` (ölçüldü
    # 2026-11-27: 2024 diliminde Mayıs'tan önce `<a href=…> </a>`) veri
    # taşımadığı için sayılmaz.
    kalan = re.sub(r"<strong>(.*?)</strong>(.*?)</p>", "", yil_html, flags=re.S)
    kalan_strong = len(re.findall(r"<strong\b", kalan))
    kalan_link = [
        m.group(0)
        for m in re.finditer(r"<a\b[^>]*>(.*?)</a>", kalan, re.S)
        if _metni_normallestir(m.group(1))
    ]
    kapanmamis_link = len(re.findall(r"<a\b", kalan)) - len(re.findall(r"<a\b[^>]*>.*?</a>", kalan, re.S))
    if kalan_strong or kalan_link or kapanmamis_link:
        raise RuntimeError(
            f"EİB: {yil} diliminde ay bloğu olarak ayrıştırılamayan içerik var "
            f"({kalan_strong} <strong>, {len(kalan_link) + kapanmamis_link} bağlantı; "
            f"{len(sonuc)} ay okundu) — o ayların bağlantıları sessizce kaybolurdu: {kalan_link[:3]!r}"
        )
    return sonuc


def hedef_ay_linki(yil: int, ay_linkleri: dict[str, dict[str, str]], bugun: date) -> tuple[str, str] | None:
    """O yılın "EİB Aylık" (Ocak'ta yalnızca "EİB") bağlantısını seçer.

    Geçmiş yıllar için ARALIK (yılın tamamı o dosyada kümülatif), cari yıl
    için yayımlanan EN SON ay (kaynak 404 vermiyor, mevcut ayların listesi
    zaten JSON içeriğinden biliniyor — TİM'deki gibi ayrıca probe gerekmez).
    """
    if not ay_linkleri:
        return None
    mevcut_aylar = [a for a in AY_ADLARI if a in ay_linkleri]
    if not mevcut_aylar:
        return None
    if yil == bugun.year:
        ay = mevcut_aylar[-1]
    elif "ARALIK" in ay_linkleri:
        ay = "ARALIK"
    elif yil == bugun.year - 1 and bugun.month <= ARALIK_YAYIN_TOLERANSI_AY:
        # Henüz yayımlanmadı: yeni biten yılın Aralık dosyası gecikebilir.
        ay = mevcut_aylar[-1]
    else:
        raise RuntimeError(
            f"EİB: {yil} için ARALIK bağlantısı yok (en son {mevcut_aylar[-1]}) — "
            f"{yil} yılının son ayları eksik kalırdı"
        )
    linkler = ay_linkleri[ay]
    url = linkler.get("EİB Aylık") or linkler.get("EİB")
    if url is None:
        raise RuntimeError(f"EİB: {yil} {ay} için 'EİB Aylık' bağlantısı bulunamadı ({sorted(linkler)})")
    return ay, url


def cekilecek_yillar(bugun: date) -> list[int]:
    return list(range(ILK_YIL, bugun.year + 1))


def _ham_veri_sayfasini_bul(kitap):
    """Ham GTİP satır verisini taşıyan sayfayı bulur. Sayfa ADI yıldan yıla
    değişiyor ('GTIP ULKE GB TARIH', 'Sayfa1', ...); başlık satırının ilk
    hücresi 'AYLAR' olan sayfa aranır (büyük/küçük harf toleranslı)."""
    for ad in kitap.sheetnames:
        sayfa = kitap[ad]
        ilk_satir = next(sayfa.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if ilk_satir and ilk_satir[0] and str(ilk_satir[0]).strip().upper() == "AYLAR":
            return sayfa
    raise RuntimeError(f"EİB: ham veri sayfası bulunamadı (sayfalar: {kitap.sheetnames})")


def _sutun_haritasi(baslik_satiri) -> dict[str, int]:
    return {str(h).strip().lower(): i for i, h in enumerate(baslik_satiri) if h}


def _dogrula(aile: dict, su_alt: dict, yil: int) -> None:
    """Kısmi okuma ya da şablon değişimi sessizce geçmemeli."""
    gorulen_urunler = {u for (_, u) in aile.keys()}
    if SU_URUNLERI_GRUBU not in gorulen_urunler:
        raise RuntimeError(f"EİB {yil}: '{SU_URUNLERI_GRUBU}' grubu bulunamadı — şablon değişmiş olabilir")
    if not any(g in gorulen_urunler for g in HAYVANSAL_GRUPLARI):
        raise RuntimeError(f"EİB {yil}: hayvansal ürün gruplarından hiçbiri bulunamadı — şablon değişmiş olabilir")
    gorulen_altlar = {a for (_, a) in su_alt.keys()}
    if not any(ad in gorulen_altlar for ad in SU_URUNLERI_ADLARI):
        raise RuntimeError(f"EİB {yil}: su ürünleri alt kırılımından (Levrek/Çipura/...) hiçbiri bulunamadı")


def yil_verisini_cikar(baytlar: bytes, yil: int, son_ay: str) -> dict[tuple[str, str], dict[str, float]]:
    """Bir yılın ham GTİP satırlarından aile/ürün bazlı aylık noktaları çıkarır.

    `son_ay` indirilen kümülatif dosyanın ayıdır (ör. "EKİM"): dosya OCAK..
    `son_ay` aylarının TAMAMINI taşımalı; eksik ya da fazla ay yükseltilir.

    Dönüş: `{(kalem, ölçüt): {"YYYY-MM-01": değer}}`. `ölçüt` "fobusd" (USD)
    ya da "agirlik" (TON — kaynak KG verir, burada /1000 ile çevrilir).
    """
    kitap = openpyxl.load_workbook(BytesIO(baytlar), data_only=True, read_only=True)
    try:
        sayfa = _ham_veri_sayfasini_bul(kitap)
        satirlar = sayfa.iter_rows(values_only=True)
        baslik = next(satirlar)
        sutun = _sutun_haritasi(baslik)
        ay_i = sutun["aylar"]
        urun_i = sutun["ürün grubu"]
        alt1_i = next((v for k, v in sutun.items() if k.strip() == "alt grup 1"), None)
        if alt1_i is None:
            raise RuntimeError(f"EİB {yil}: 'alt grup 1' sütunu bulunamadı (başlık: {baslik})")
        agirlik_i = sutun["agirlik"]
        fobusd_i = sutun["fobusd"]

        aile: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
        su_alt: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
        for row in satirlar:
            ay = row[ay_i]
            if ay not in AY_NO:
                if all(h is None for h in row):
                    continue  # openpyxl'in sondaki boş satırları
                raise RuntimeError(f"EİB {yil} {son_ay} dosyası: tanınmayan 'Aylar' değeri {ay!r} — satır okunamadı")
            urun = row[urun_i]
            fob = row[fobusd_i] or 0.0
            agr = row[agirlik_i] or 0.0
            aile[(ay, urun)][0] += fob
            aile[(ay, urun)][1] += agr
            if urun == SU_URUNLERI_GRUBU:
                alt1 = row[alt1_i]
                su_alt[(ay, alt1)][0] += fob
                su_alt[(ay, alt1)][1] += agr
    finally:
        kitap.close()

    _dogrula(aile, su_alt, yil)

    beklenen_aylar = AY_ADLARI[: AY_NO[son_ay]]
    gorulen_aylar = {a for (a, _) in aile.keys()}
    if gorulen_aylar != set(beklenen_aylar):
        eksik = [a for a in beklenen_aylar if a not in gorulen_aylar]
        fazla = sorted(gorulen_aylar - set(beklenen_aylar), key=AY_NO.get)
        raise RuntimeError(
            f"EİB {yil} {son_ay} kümülatif dosyası OCAK..{son_ay} aylarını taşımıyor "
            f"(eksik: {eksik}, beklenmeyen: {fazla})"
        )

    # İzlenen her kalemin (8 hayvansal grup + 5 su ürünü) HER ayda satırı
    # olmalı. Ölçüldü 2026-11-27 (2025 ARALIK + 2026 EKİM dosyaları, 22 ay):
    # 13 kalemin hepsi 22 ayın hepsinde satır taşıyor; ihracatın sıfır olduğu
    # aylarda bile kaynak 0 değerli satır yazıyor (Kırmızı Et 2025-02,
    # 2025-11, 2026-03; Canlı Hayvan 2026-03). Satırın YOKLUĞU bu yüzden
    # "sıfır" değil ad değişimi/şablon kayması demektir → yükselt; ne delik
    # bırakılır ne de uydurma 0 yazılır. (DİĞER ETLER bu kuralın dışında:
    # izlenmiyor, modül docstring'i.)
    eksik_satirlar = [
        (ay_adi, kalem)
        for ay_adi in beklenen_aylar
        for kalem, kume in [(g, aile) for g in HAYVANSAL_GRUPLARI]
        + [(ad, su_alt) for ad in SU_URUNLERI_ADLARI]
        if (ay_adi, kalem) not in kume
    ]
    if eksik_satirlar:
        raise RuntimeError(
            f"EİB {yil} {son_ay} dosyası: izlenen kalemlerin satırı yok (ay, kalem): {eksik_satirlar}"
        )
    noktalar: dict[tuple[str, str], dict[str, float]] = {}

    def tarih_yaz(ay_adi: str) -> str:
        return f"{yil:04d}-{AY_NO[ay_adi]:02d}-01"

    def yaz(kalem: str, ay_adi: str, fob: float, agr: float) -> None:
        noktalar.setdefault((kalem, "fobusd"), {})[tarih_yaz(ay_adi)] = fob
        noktalar.setdefault((kalem, "agirlik"), {})[tarih_yaz(ay_adi)] = agr / 1000.0

    for ay_adi in beklenen_aylar:
        toplam = aile.get((ay_adi, SU_URUNLERI_GRUBU))
        if toplam is None:
            raise RuntimeError(f"EİB {yil} {ay_adi}: '{SU_URUNLERI_GRUBU}' satırı yok — ay okunamadı")
        yaz(SU_URUNLERI_GRUBU, ay_adi, toplam[0], toplam[1])

        hayvansal_fob = hayvansal_agr = 0.0
        for g in HAYVANSAL_GRUPLARI:
            fob, agr = aile[(ay_adi, g)]
            yaz(g, ay_adi, fob, agr)
            hayvansal_fob += fob
            hayvansal_agr += agr
        yaz(HAYVANSAL_TOPLAM, ay_adi, hayvansal_fob, hayvansal_agr)

        adlandirilan_fob = adlandirilan_agr = 0.0
        for ad in SU_URUNLERI_ADLARI:
            fob, agr = su_alt[(ay_adi, ad)]
            yaz(ad, ay_adi, fob, agr)
            adlandirilan_fob += fob
            adlandirilan_agr += agr
        yaz(DIGER_SU_URUNLERI, ay_adi, toplam[0] - adlandirilan_fob, toplam[1] - adlandirilan_agr)

    return noktalar


def _icerik_cek(session=None) -> str:
    http = session or requests
    yanit = http.get(ICERIK_URL, params={"SI_Id": ISTATISTIK_SI_ID}, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    veri = yanit.json()
    if "icerik" not in veri:
        raise RuntimeError("EİB istatistik sayfası: beklenmeyen JSON gövdesi")
    return veri["icerik"]


def _dosya_indir(url: str, session=None) -> bytes:
    http = session or requests
    yanit = http.get(url, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    return yanit.content


def _tum_noktalari_getir(onbellek: dict, session=None, bugun: date | None = None) -> dict[tuple[str, str], dict[str, float]]:
    if "noktalar" in onbellek:
        return onbellek["noktalar"]
    bugun = bugun or date.today()

    yillar_html = yillara_ayir(_icerik_cek(session))

    noktalar: dict[tuple[str, str], dict[str, float]] = {}
    en_az_bir_yil = False
    for yil in cekilecek_yillar(bugun):
        yil_html = yillar_html.get(str(yil))
        secim = hedef_ay_linki(yil, ay_baglantilarini_cikar(yil_html, yil), bugun) if yil_html else None
        if secim is None:
            if yil == bugun.year and bugun.month <= CARI_YIL_YAYIN_TOLERANSI_AY:
                continue  # henüz yayımlanmadı: cari yılın başlığı/ilk ayı yok
            raise RuntimeError(
                f"EİB: {yil} yılının başlığı ya da ay bağlantıları istatistik sayfasında yok — "
                f"o yılın tamamı eksik kalırdı"
            )
        son_ay, url = secim
        yillik = yil_verisini_cikar(_dosya_indir(url, session), yil, son_ay)
        for anahtar, seri_noktalari in yillik.items():
            noktalar.setdefault(anahtar, {}).update(seri_noktalari)
        en_az_bir_yil = True

    if not en_az_bir_yil:
        raise RuntimeError(f"EİB: {ILK_YIL} sonrası indirilecek yıllık bülten bulunamadı")

    onbellek["noktalar"] = noktalar
    return noktalar


def seri_cek(seri, onbellek: dict | None = None, session=None, bugun: date | None = None) -> pd.DataFrame:
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı).

    `onbellek` koşu boyunca paylaşılırsa 32 seri (14 su ürünleri + 18
    hayvansal) aynı 1-2 yıllık yıllık bülten indirmesini paylaşır.
    """
    onbellek = {} if onbellek is None else onbellek
    noktalar = _tum_noktalari_getir(onbellek, session, bugun)

    anahtar = (seri.eib_kalem, seri.eib_olcut)
    if anahtar not in noktalar or not noktalar[anahtar]:
        raise RuntimeError(f"EİB: kalem/ölçüt kombinasyonu bulunamadı: {anahtar!r} ({seri.id})")

    df = pd.DataFrame(sorted(noktalar[anahtar].items()), columns=["date", "value"])
    if seri.start_date:
        df = df[df["date"] >= seri.start_date]
    return df.reset_index(drop=True)
