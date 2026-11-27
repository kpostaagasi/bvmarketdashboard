"""TAB Gıda (Burger King/Popeyes/Arby's/Sbarro/Usta Dönerci/Usta Pideci/
Subway Türkiye ana bayii) çeyreklik "Finansal Bülten" PDF istemcisi.

TAB Gıda BIST'te işlem görmüyor (TABGD, marketvisuals.net'in dahili kısa
kodu) — tahvil yatırımcıları için gönüllü şeffaflık amacıyla
`tabgida.com.tr/tr/yatirimci-iliskileri/yatirimci-sunumlari` sayfasında yıl
başlıklı statik bir tabloda çeyreklik "Finansal Bülten" (temiz metin/tablo,
sunum destesi DEĞİL) yayımlıyor. Tablo satırı zaten "N. Çeyrek" etiketi
taşıdığından dönem, PDF içeriği ayrıştırılmadan doğrudan (yıl, çeyrek no)
ikilisinden biliniyor — 4. çeyrek satırı FY (tam yıl) bültenine işaret
ediyor.

**Sütun sırası BigChefs'in TERSİ**: "(milyon TL) | 2Ç 2025 | 2Ç 2026 | ... "
biçiminde ÖNCEKİ yıl önce, CARİ yıl sonra gelir.

Bu adaptör yalnızca iki seriyi karşılıyor:
- `restoran-sayisi` (çeyreklik): bültenin işletme özeti paragrafındaki
  toplam restoran/lokasyon cümlesinden. İFADE BİÇİMİ ÇEYREKTEN ÇEYREĞE
  DEĞİŞİR, ölçülen beş biçim (`_RESTORAN_DESENI`):
    * "restoran sayımızı 1.654'e çıkardık" / "toplam restoran sayımızı
      1.572'ye çıkardık" — iki ayrım var: `toplam` kelimesi BAZI
      çeyreklerde yok ve sonek `e` ya da `ye` (1Ç24, 3Ç23, 2Ç24, 3Ç25)
    * "toplam restoran sayımızı 2.100'e ulaştırdık" (2Ç26) — cümle metin
      satır ortasında bölündüğü için aradaki boşluk için `\\s` eşleşmesi şart
    * "restoran ağımızı 2.164'e ulaştırdık"           (3Ç26; 27 Kasım 2026
      canlı ölçüm — bu biçim eşleşmediği için çeyrek önceden SESSİZCE
      atlanıyordu)
    * "yılı 2.030 lokasyonla kapattık"                (4Ç25)
    * "toplamda 1.830 lokasyona ulaştık" / "portföyümüzü 1.906 lokasyona
      genişlettik" / "restoran portföyümüz 1.854 lokasyona ulaştı" /
      "1.615 restorana ulaştık"                       (4Ç23, 4Ç24, 1Ç25, 2Ç25)
  ELENEN (çeyreklik toplam bildirmeyen, yalnızca "N yeni restoran açtık"
  diyen): 3Ç24, 1Ç26 — bu çeyreklerde sayı yok, seri o dönem boş kalır.
  Bu iki çeyrek `TOPLAM_BILDIRMEYEN_CEYREKLER` sabitinde AÇIKÇA listelenir;
  listede olmayan bir bültende cümle bulunamazsa `seri_cek` hata verir
  (sessiz boşluk yok).
- `fis-sayisi` (yıllık): yalnızca 4. çeyrek (FY) bültenindeki "Önemli
  Operasyonel ve Finansal Göstergeler" tablosunun fiş sayısı satırından.
  4. çeyrek bültenlerinde tablo 4Ç ve FY olmak üzere İKİ çift gösterir:
  `Fiş sayısı ('000) 47.287 47.081 %0 183.140 203.718 %11` → FY 2023
  DEĞERİ beşinci alandır (203.718), ikincisi 4Ç 2023'tür (47.081).
  Sadece FY özeti olan tabloda (`Fiş sayısı ('000) 183.140 203.718 %11`)
  dört değer yoktur ve ikinci alan zaten FY'dir. 4Ç 2024 tek çeyrekte
  İngilizce yayımlandı: satır etiketi `Number of tickets ('000)` — iki
  etiket de kabul edilir. Elenen: 4Ç bültenindeki 4Ç değeri (kümülatif
  değil) ve metin içindeki "Fiş sayısı 51,3 milyona ulaşarak" anlatım
  cümlesi.

Ölçüldü (30 Eylül 2026, canlı): 12 bültenin 12'si de okundu. Seri
çıktıları: `restoran-sayisi` 10 çeyrek (3Ç23 1.572 → 2Ç26 2.100, artan),
`fis-sayisi` 3 yıl (FY2023 203.718 / FY2024 207.648 / FY2025 247.196 bin
adet — 2024 bülteni İngilizce olduğu için etiket eşleşmesi şarttı).

Yeniden ölçüldü (27 Kasım 2026, canlı): 13 bülten (3Ç26 eklendi). 3Ç26
"restoran ağımızı 2.164'e ulaştırdık" diyordu; desen bunu tanımadığı için
eski kod çeyreği SESSİZCE atlıyordu (CSV 2Ç26'da duruyordu). Desen
genişletildi; `restoran-sayisi` 11 çeyrek (→ 3Ç26 2.164), `fis-sayisi`
değişmedi.

**TLS/WAF (ölçüldü 30 Eylül 2026, sistemsik).** `tabgida.com.tr`
Python'ın varsayılan şifre listesini (`@SECLEVEL=2:...:!SHA1:!AESCCM`)
teklif eden ClientHello'yu `ConnectionResetError(54)` ile sıfırlıyor —
`curl`, `urllib` ve `requests` FARK YOK; hepsi aynı OpenSSL bağlamını
paylaşıyor. WAF'ın kabul ettiği tek ayrım `!SHA1` kaldırılmış listedir
(`:!AESCCM` yeterli değil, `AES256-SHA` eklemek de yetmez — OpenSSL'de
negasyonlar sonraki girdileri de siler). `_WafAdapter` bunu yapar. Bu
makinede `!SHA1`'sız liste 4/4, varsayılan liste 0/4 el bağlantı kuruyor.

**Göreli yol çözümü (ölçüldü 30 Eylül 2026).** Sayfa `/tr/yatirimci-
iliskileri/` altında ama CMS dosyaları site KÖKÜNDE: `href="../cmsfiles/..."`
satırından türetilen `urljoin` `/tr/cmsfiles/...` veriyor ve o yol 404 → ana
sayfaya YÖNLENDİRME döndürüyor (200 `text/html`, 36.378 bayt — PDF değil).
Bu yüzden göreli yol köke göre çözülür, baştaki `../` atılır.

**Bozuk `href` (ölçüldü 30 Eylül 2026, 2024/4.Çeyrek).** Ham HTML'de
`href="<../cmsfiles/..."` — baştaki `<` fazlalık. `.strip("<> ")` bunu
onar (27 Kasım 2026 canlı sayfada bu satır düzelmiş). Onarılamayan
(boş/hâlâ `<` içeren) bağlantı artık HATA verir: bülten yayımlanmış ama
okunamıyor demektir ve CSV her koşuda baştan yazıldığından atlamak o
çeyreği sessizce silerdi.

**Yayımlanmamış ↔ okunamayan ayrımı (27 Kasım 2026 bakım işi).** Meşru
"henüz yok" durumu tek biçimdedir: EN YENİ çeyreğin satırı yoktur (ya da
satır var ama bülten hücresinde bağlantı yoktur). Yayımlanmış bültenler
en eskiden en yeniye aralıksız olmalıdır (`_surekliligi_denetle`); ortada
eksik/bağlantısız bir çeyrek, ayrıştırılan yıl tablosu sayısının sayfadaki
`<tbody>` sayısından farklı olması da hatadır. Bunun dışındaki her şey —
şablona uymayan çeyrek satırı, onarılamayan `href`, 404, PDF yerine HTML
dönen yanıt, metinde aranan cümle/satırın bulunamaması (bilinen boşluklar
hariç) — dönemi ve URL'yi adıyla anan bir `RuntimeError` fırlatır.
Bağlantı hataları/zaman aşımları/5xx `__cause__` zinciriyle korunur;
`ingest.run.erisilemez_mi` onları kaynak sorunu sayar.

Kapsam dışı (ölçüldü): çalışan sayısı, ülke/marka bazında restoran dağılımı,
yatırım harcaması dağılımı — bültende ham alan olarak yok.
"""

from __future__ import annotations

import io
import re
import ssl
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from requests.adapters import HTTPAdapter

from ingest.ir_sunum import pdf_metnini_normallestir, tr_sayi

TABAN = "https://www.tabgida.com.tr/tr/yatirimci-iliskileri/"
SUNUM_URL = f"{TABAN}yatirimci-sunumlari"
_KOK = "https://www.tabgida.com.tr/"
ZAMAN_ASIMI = 60
_BASLIKLAR = {"User-Agent": "Mozilla/5.0"}

# WAF'ın kabul ettiği şifre listesi: Python varsayılanı (`ssl` modülünün
# `_DEFAULT_CIPHERS`) SONUNDA `!SHA1` ile SHA1 CBC paketlerini eliyor ve
# sunucu bu ClientHello'yu sıfırlıyor. `!AESCCM` kaldırılmış hâli yeterli.
_SIFRE_LISTESI = "@SECLEVEL=2:ECDH+AESGCM:ECDH+CHACHA20:ECDH+AES:DHE+AES:!aNULL:!eNULL:!aDSS:!AESCCM"


class _WafAdapter(HTTPAdapter):
    """`!SHA1` içermeyen şifre listesiyle bağlanır — aksi hâlde WAF el
    sıfırlıyor (docstring'deki ölçüm)."""

    def init_poolmanager(self, *args, **kwargs):
        baglam = ssl.create_default_context()
        baglam.set_ciphers(_SIFRE_LISTESI)
        kwargs["ssl_context"] = baglam
        return super().init_poolmanager(*args, **kwargs)


def _oturum(session=None) -> requests.Session:
    """Bu kaynak için WAF uyumlu TLS bağdaştırıcısını bağlar.

    `ingest.run` koşu boyunca paylaşılan TEK bir `requests.Session` verir ve
    o oturumun `https://` bağdaştırıcısı varsayılan şifre listesiyle
    çalışır — WAF onu sıfırlar. Bu yüzden sunucuya ÖZGÜ önek
    (`https://www.tabgida.com.tr`) bağdaştırıcısı değiştirilir; diğer
    kaynakların oturumu olduğu gibi kalır."""
    oturum = session if session is not None else requests.Session()
    if not isinstance(oturum.get_adapter(SUNUM_URL), _WafAdapter):
        oturum.mount("https://www.tabgida.com.tr", _WafAdapter(max_retries=2))
    return oturum


# Etiketler öznitelik kazanabilir (`<tr class=...>`, `<tbody id=...>`) —
# çıplak `<tr>` deseni öyle bir satırı/yılı SESSİZCE düşürürdü. Bu yüzden
# her etiket `\b[^>]*` ile gevşek; ayrıca `_bulten_listesi` sayfadaki
# `<tbody` sayısını ayrıştırılan yıl tablosu sayısıyla karşılaştırır.
_YIL_TABLO = re.compile(
    r"<thead\b[^>]*>\s*<tr\b[^>]*>\s*<th\b[^>]*>\s*(\d{4})\s*</th>.*?</thead>"
    r"\s*<tbody\b[^>]*>(.*?)</tbody>",
    re.S,
)
_TBODY = re.compile(r"<tbody\b", re.S)
# Satır düzeyinde ayrıştırma: önce her `<tr>`, sonra hücreleri. Tek parça
# bir satır deseni, şablona uymayan bir çeyrek satırını SESSİZCE atlardı.
_SATIR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
_HUCRE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_CEYREK_ETIKETI = re.compile(r"^\s*(\d)\.\s*Çeyrek\s*$")
_HREF = re.compile(r"<a\b[^>]*\bhref=\"([^\"]*)\"", re.S)

_RESTORAN_DESENI = re.compile(
    r"(?:toplam\s+)?restoran sayımızı\s+([\d.]+)'y?[ea]\s+(?:ulaştırdık|çıkardık)"
    r"|yılı\s+([\d.]+)\s+lokasyonla kapattık"
    r"|toplam(?:da)?\s+([\d.]+)\s+lokasyona ulaştık"
    r"|portföyümüzü\s+([\d.]+)\s+lokasyona genişlettik"
    r"|restoran portföyümüz\s+([\d.]+)\s+lokasyona ulaştı"
    r"|([\d.]+)\s+restorana ulaştık"
    r"|restoran ağımızı\s+([\d.]+)'y?[ea]\s+ulaştırdık"
)

# Çeyreklik TOPLAM restoran sayısı bildirmeyen bültenler (yıl, çeyrek) —
# kalıcı boşluk, hata değil. Kanıt (canlı ölçüm 30 Eylül ve 27 Kasım 2026,
# PDF metni tarandı): 3Ç 2024 bülteni yalnızca "3. çeyrekte 76 yeni restoran
# açtık" / "Eylül sonu itibarıyla toplam 182 yeni restoran" diyor; 1Ç 2026
# bülteni yalnızca "İlk çeyrekte 38 yeni restoran açarken". İkisinde de
# çeyrek sonu toplamı yok; açılış sayısından türetmek kapanışları bilmeden
# yanlış olur. Bu listede OLMAYAN bir bültende cümle bulunamazsa hata.
TOPLAM_BILDIRMEYEN_CEYREKLER = frozenset({(2024, 3), (2026, 1)})

GECERLI_METRIKLER = {"restoran-sayisi", "fis-sayisi"}
_CEYREK_ILK_AY = {1: "01", 2: "04", 3: "07", 4: "10"}


def _bulten_listesi(session=None) -> list[dict]:
    """(yil, ceyrek_no, url) listesi — yatirimci-sunumlari sayfasından."""
    http = _oturum(session)
    yanit = http.get(SUNUM_URL, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    yanit.raise_for_status()
    yanit.encoding = "utf-8"
    yil_tablolari = _YIL_TABLO.findall(yanit.text)
    tbody_sayisi = len(_TBODY.findall(yanit.text))
    if tbody_sayisi != len(yil_tablolari):
        # Ölçüldü (27 Kasım 2026): sayfada 4 `<tbody>`, 4 yıl tablosu
        # (2023–2026). Fark = bir yılın başlığı şablona uymuyor; o yılın
        # bütün çeyrekleri sessizce düşerdi.
        raise RuntimeError(
            f"TAB Gıda yatırımcı sunumları sayfasında {tbody_sayisi} tablo "
            f"gövdesi var ama {len(yil_tablolari)} yıl tablosu ayrıştırıldı — "
            "şablon değişmiş olabilir"
        )
    sonuc = []
    baglantisiz: list[tuple[int, int]] = []
    for yil, govde in yil_tablolari:
        for satir in _SATIR.findall(govde):
            hucreler = _HUCRE.findall(satir)
            etiket = _CEYREK_ETIKETI.match(hucreler[0]) if hucreler else None
            if etiket is None:
                raise RuntimeError(
                    f"TAB Gıda {yil} tablosunda çeyrek etiketi okunamayan satır "
                    f"var ({satir[:120]!r}) — şablon değişmiş olabilir"
                )
            ceyrek_no = etiket.group(1)
            donem = f"{yil} {ceyrek_no}Ç"
            if len(hucreler) != 3:
                raise RuntimeError(
                    f"TAB Gıda {donem} satırında 3 yerine {len(hucreler)} hücre "
                    "var — şablon değişmiş olabilir"
                )
            bulten_hucresi = hucreler[2]
            if "<a" not in bulten_hucresi:
                # "Henüz yayımlanmadı" adayı: satır (ör. sunumla birlikte)
                # açılmış ama bülten bağlantısı henüz konmamış. Yalnızca EN
                # YENİ dönem için meşru — aşağıda süreklilikle denetlenir.
                baglantisiz.append((int(yil), int(ceyrek_no)))
                continue
            href = _HREF.search(bulten_hucresi)
            # 2024/4.Çeyrek satırının href'i baştaki `<` ile bozuk geliyordu
            # ("<../cmsfiles/..."). Ayırıcı temizlenir; temizlenemeyen
            # bağlantı HATA verir — yayımlanmış bülteni atlamak o çeyreği
            # CSV'den sessizce silerdi.
            temiz = href.group(1).strip("<> ") if href else ""
            if not temiz or "<" in temiz:
                raise RuntimeError(
                    f"TAB Gıda {donem} Finansal Bülten bağlantısı okunamadı "
                    f"({bulten_hucresi[:120]!r}) — satır var, href bozuk"
                )
            # CMS dosyaları sayfadan değil site KÖKÜNDE (docstring ölçümü):
            # `../` atılıp köke göre çözülür.
            sonuc.append({
                "yil": int(yil),
                "ceyrek": int(ceyrek_no),
                "url": urljoin(_KOK, temiz.lstrip("./")),
            })
    if not sonuc:
        raise RuntimeError(
            "TAB Gıda yatırımcı sunumları sayfasında hiç 'Finansal Bülten' "
            "bağlantısı ayrıştırılamadı — şablon değişmiş olabilir"
        )
    _surekliligi_denetle(sonuc, baglantisiz)
    return sonuc


def _surekliligi_denetle(sonuc: list[dict], baglantisiz: list[tuple[int, int]]) -> None:
    """Yayımlanmış bültenler en eskiden en yeniye ARALIKSIZ olmalı.

    Meşru "henüz yok" yalnızca en yeni dönemdir. Ortadaki bir çeyreğin
    satırı kaybolursa ya da bülten hücresindeki bağlantı kalkarsa (CMS
    düzenlemesi) o çeyrek CSV'den sessizce silinirdi — hata verilir.
    Ölçüldü (27 Kasım 2026): 3Ç 2023 → 3Ç 2026, 13 bülten, aralıksız."""
    donemler = sorted((b["yil"], b["ceyrek"]) for b in sonuc)
    if len(set(donemler)) != len(donemler):
        tekrar = sorted({d for d in donemler if donemler.count(d) > 1})
        raise RuntimeError(
            "TAB Gıda sayfasında aynı dönem için birden çok Finansal Bülten "
            f"satırı var: {', '.join(f'{y} {c}Ç' for y, c in tekrar)}"
        )
    en_yeni = donemler[-1]
    eski_baglantisiz = sorted(d for d in baglantisiz if d < en_yeni)
    if eski_baglantisiz:
        raise RuntimeError(
            "TAB Gıda Finansal Bülten bağlantısı daha yeni bülten yayımlanmışken "
            "eksik: " + ", ".join(f"{y} {c}Ç" for y, c in eski_baglantisiz)
            + " — satır var, bülten hücresi boş (yalnızca en yeni dönem "
            "'henüz yayımlanmadı' sayılabilir)"
        )
    eksik = []
    for (y1, c1), (y2, c2) in zip(donemler, donemler[1:]):
        y, c = y1, c1
        while True:
            y, c = (y + 1, 1) if c == 4 else (y, c + 1)
            if (y, c) == (y2, c2):
                break
            eksik.append(f"{y} {c}Ç")
    if eksik:
        raise RuntimeError(
            "TAB Gıda yatırımcı sunumları sayfasında Finansal Bülten dizisi "
            f"aralıklı — eksik dönem: {', '.join(eksik)} (satır kaybolmuş ya da "
            "şablon değişmiş olabilir)"
        )


def _belge_metnini_getir(url: str, onbellek: dict, session=None, donem: str = "") -> str:
    """Bülten PDF'inin metnini döndürür; okunamayan bülten HATA verir.

    Eskiden 404/HTML/bağlantı hatasında `None` dönüp çeyrek atlanıyordu —
    CSV her koşuda baştan yazıldığından bu, o çeyreği sessizce silmek
    demekti. Artık: bağlantı hatası/zaman aşımı/5xx `from` ile zincirlenir
    (`erisilemez_mi` kaynak sorunu sayar, koşu yeşil kalır, CSV korunur);
    404 ve PDF yerine HTML dönen yanıt (ana sayfaya yönlenme = yanlış yol)
    bizim düzeltmemiz gereken şeydir ve kırmızıdır."""
    if url in onbellek:
        return onbellek[url]
    http = _oturum(session)
    try:
        yanit = http.get(url, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    except requests.RequestException as hata:
        raise RuntimeError(
            f"TAB Gıda {donem} Finansal Bülten indirilemedi: {url}"
        ) from hata
    try:
        yanit.raise_for_status()
    except requests.HTTPError as hata:
        raise RuntimeError(
            f"TAB Gıda {donem} Finansal Bülten indirilemedi "
            f"(HTTP {yanit.status_code}): {url}"
        ) from hata
    if not yanit.content.startswith(b"%PDF"):
        # CMS yolu tutmazsa sunucu 200 döndürüp ana sayfaya YÖNLENDİRİR
        # (ölçüldü: 36.378 bayt `text/html`); PDF imzası yoksa PDF değildir.
        raise RuntimeError(
            f"TAB Gıda {donem} Finansal Bülten PDF değil (200 ama PDF imzası "
            f"yok — ana sayfaya yönlenmiş olabilir): {url}"
        )
    with pdfplumber.open(io.BytesIO(yanit.content)) as pdf:
        metin = pdf_metnini_normallestir("\n".join(sayfa.extract_text() or "" for sayfa in pdf.pages))
    if not metin.strip():
        raise RuntimeError(
            f"TAB Gıda {donem} Finansal Bülten PDF'inde metin katmanı yok: {url}"
        )
    onbellek[url] = metin
    return metin


def restoran_sayisini_ayikla(metin: str) -> float | None:
    """Toplam restoran/lokasyon cümlesinden değeri alır (biçimler ve elenen
    alternatifler modül docstring'inde — canlı 13 bültenin 11'i eşleşiyor;
    kalan ikisi `TOPLAM_BILDIRMEYEN_CEYREKLER`)."""
    m = _RESTORAN_DESENI.search(metin)
    if not m:
        return None
    ham = next(g for g in m.groups() if g)
    return float(ham.replace(".", ""))


def fis_sayisini_ayikla(metin: str) -> float | None:
    """"Fiş sayısı ('000) ..." satırından FY değerini alır.

    Değer zaten BİN adet cinsindendir (satır başlığı "('000)") — ayrıca
    ölçeklenmez. 4.Ç bültenlerinde satır 4Ç ve FY olmak üzere iki çift
    gösterir (`... %0 183.140 203.718 %11`); FY **beşinci** alandadır, ikinci
    alan 4Ç'dir. Yalnızca FY özeti olan tabloda üçüncü alan yoktur ve
    ikinci alan zaten FY'dir. 2024 tek çeyrekte satır İngilizce
    ("Number of tickets") — iki etiket de kabul edilir.
    """
    desen = re.compile(
        r"^(?:Fiş sayısı|Number of tickets) \('000\)\s+(.+)$", re.M,
    )
    m = desen.search(metin)
    if not m:
        return None
    # Değer alanlarını topla; YÜZDE değişim alanları elenir.
    sayilar = [a for a in m.group(1).split() if not a.startswith("%")]
    if len(sayilar) < 2:
        return None
    # 4Ç+FY tablosunda 4 değer var (4Ç öncü, 4Ç cari, FY öncü, FY cari) →
 # FY cari dördüncüsü; sadece FY tablosunda 2 değer var → ikincisi.
    ham = sayilar[3] if len(sayilar) >= 4 else sayilar[1]
    try:
        return tr_sayi(ham)
    except ValueError:
        return None


def seri_cek(seri, onbellek: dict | None = None, session=None) -> pd.DataFrame:
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı)."""
    onbellek = onbellek if onbellek is not None else {}
    metrik = seri.tabgida_metrik
    if metrik not in GECERLI_METRIKLER:
        raise RuntimeError(f"Bilinmeyen tabgida_metrik: {metrik!r}")

    if "bultenler" not in onbellek:
        onbellek["bultenler"] = _bulten_listesi(session=session)
    bultenler = onbellek["bultenler"]

    noktalar: list[tuple[str, float]] = []
    for b in bultenler:
        if metrik == "fis-sayisi" and b["ceyrek"] != 4:
            continue  # fis-sayisi: yalnızca 4. çeyrek (FY) bültenleri
        donem = f"{b['yil']} {b['ceyrek']}Ç"
        metin = _belge_metnini_getir(b["url"], onbellek, session=session, donem=donem)
        if metrik == "restoran-sayisi":
            deger = restoran_sayisini_ayikla(metin)
            if deger is None:
                if (b["yil"], b["ceyrek"]) in TOPLAM_BILDIRMEYEN_CEYREKLER:
                    continue  # kalıcı boşluk — sabitin yorumundaki kanıt
                raise RuntimeError(
                    f"TAB Gıda {donem} Finansal Bülten'inde toplam restoran "
                    f"sayısı cümlesi bulunamadı ({b['url']}) — yeni ifade "
                    "biçimi `_RESTORAN_DESENI`'ne eklenmeli ya da bülten gerçekten "
                    "toplam bildirmiyorsa `TOPLAM_BILDIRMEYEN_CEYREKLER`'e kanıtla yazılmalı"
                )
            tarih = f"{b['yil']}-{_CEYREK_ILK_AY[b['ceyrek']]}-01"
        else:
            deger = fis_sayisini_ayikla(metin)
            if deger is None:
                raise RuntimeError(
                    f"TAB Gıda {donem} (FY {b['yil']}) Finansal Bülten'inde "
                    f"fiş sayısı satırı okunamadı ({b['url']}) — şablon değişmiş olabilir"
                )
            tarih = f"{b['yil']}-10-01"
        noktalar.append((tarih, deger))

    if not noktalar:
        raise RuntimeError(
            f"TAB Gıda {metrik!r} için taranan {len(bultenler)} bültenin "
            "hiçbirinde değer bulunamadı — şablon değişmiş olabilir"
        )
    df = (
        pd.DataFrame(noktalar, columns=["date", "value"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return df
