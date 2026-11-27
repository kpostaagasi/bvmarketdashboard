"""OSD (Otomotiv Sanayii Derneği) aylık üretim bülteni istemcisi.

Bültenler yalnızca PDF olarak yayımlanıyor ve indirme URL'leri yükleme
tarihini gömdüğü için türetilemiyor — indeks sayfası kazınmak zorunda.

Firma aylık toplamı için 6–9. sayfalar okunur (firma × ay, araç tipi
bölümlerinde). Bir bülten o yılın tamamını taşıdığından tarihsel doldurma
yılda tek PDF ister; 2. sayfayı (tek ay) okumak aynı pencere için on kat
daha fazla indirme demek olurdu.

Öz-doğrulama: 6–9. sayfaların firma toplamı, 2. sayfanın TOPLAM sütunuyla
karşılaştırılır. Canlı bültende 13 firmanın 13'ünde de fark 0 ölçüldü.
Tutmazsa RuntimeError yükselir — OSD şablonu değiştiğinde sessizce eksik
veri üretmektense ingest'in kırılması istenir.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import date

import pandas as pd
import pdfplumber
import requests

from ingest.http import durum_kodu_yukselt

TABAN = "https://www.osd.org.tr"
INDEKS_URL = f"{TABAN}/osd-yayinlari/otomotiv-sanayii-uretim-bultenleri"
VARSAYILAN_GECMIS_YIL = 5

# 2022 alt çizgi, 2023+ tire kullanıyor; ikisi de kabul edilir.
# Yeniden yüklenen (düzeltilmiş) bülten `_1` gibi bir sonek alıyor
# (ölçüldü 2026-11-13: `…-2026.09_1.pdf`, 2026'nın indeksteki tek bülteni).
_BAGLANTI = re.compile(
    r'href="(/saved-files[^"]*?Otomotiv_Sanayii_Uretim_Bulteni[-_](\d{4}\.\d{2})(?:_\d+)?\.pdf)"'
)

_ATLANACAK_ONEKLER = ("Pay /", "Toplam Pay", "Tipler")

# İndeksteki HER PDF bağlantısı (yalnızca `_BAGLANTI`'ya uyanlar değil).
# Kısmi eşleşmenin sessiz kayıp açığını kapatmak için kullanılır: bir bülten
# yeni bir dosya adı şablonuyla yüklenirse (ör. `_1` soneki tanınmadan önce
# 2026'nın tek bülteni eşleşmemiş, 31 seri 317 gün geride kalmıştı) o ay
# sessizce dışarıda kalmak yerine ingest kırılır.
_HER_PDF = re.compile(r'href="(/saved-files[^"]*?\.pdf)"', re.IGNORECASE)

# Bilinen ve BİLEREK okunmayan eski ad şablonu: 2006–2021 yıllık bültenleri
# 2022-02-02'de toplu yüklenmiş (`/saved-files\PDF\2022\02\02\Üretim Bülteni
# _2021.pdf`, ölçüldü 2026-11-27). Eski şablonlu bu dosyalar hiç okunmadı;
# 13 firma serisi bu yüzden 2022-01'de başlar (delik değil, başlangıç).
# Muafiyet YALNIZCA `ESKI_AD_SON_YIL`'a kadarki yıllar için: canlı indekste bu
# şablonla 32 bağlantı var, hepsi 2006..2021 (ölçüldü 2026-11-27). Güncel bir
# yılın bülteni bu eski adla yüklenirse sessizce atlanmamalı — `cekilecek_
# bultenler`in boşluk denetimi en yeni yılı yakalayamaz.
_ESKI_ADLI_URETIM_BULTENI = re.compile(r"Üretim Bülteni _(\d{4})\.pdf$")
ESKI_AD_SON_YIL = 2021


def _eski_adli_bilinen_bulten_mi(yol: str) -> bool:
    eslesme = _ESKI_ADLI_URETIM_BULTENI.search(_dosya_adi(yol))
    return bool(eslesme) and int(eslesme.group(1)) <= ESKI_AD_SON_YIL


def _dosya_adi(yol: str) -> str:
    return yol.replace("\\", "/").rsplit("/", 1)[-1]


def bulten_baglantilari(html: str) -> dict[str, str]:
    """İndeks HTML'inden `"YYYY.MM" -> tam URL` eşlemesi çıkarır.

    HTML'deki yollar ters bölülü (`/saved-files\\PDF\\2026\\...`); düz bölüye
    çevrilir. Hiç bağlantı bulunamazsa RuntimeError: site yapısı değiştiyse
    boş liste döndürüp sessizce devam etmek, veriyi sessizce kaybetmektir.

    İndeksteki bir PDF ne `_BAGLANTI`'ya ne de bilinen eski ad şablonuna
    (`_ESKI_ADLI_URETIM_BULTENI`, yalnızca yıl <= `ESKI_AD_SON_YIL`) uyuyorsa
    da RuntimeError: o bülten
    okunamıyor demektir ve sessizce atlanırsa o yılın ayları eksik kalır.
    """
    baglantilar = {
        anahtar: TABAN + yol.replace("\\", "/")
        for yol, anahtar in _BAGLANTI.findall(html)
    }
    if not baglantilar:
        raise RuntimeError(
            f"OSD indeksinde bülten bağlantısı bulunamadı ({INDEKS_URL}) — "
            "sayfa yapısı değişmiş olabilir"
        )
    taninan = {yol for yol, _ in _BAGLANTI.findall(html)}
    taninmayan = sorted({
        yol for yol in _HER_PDF.findall(html)
        if yol not in taninan
        and not _eski_adli_bilinen_bulten_mi(yol)
    })
    if taninmayan:
        raise RuntimeError(
            f"OSD Üretim Bülteni indeksinde dosya adı tanınmayan bülten var "
            f"({INDEKS_URL}): {', '.join(_dosya_adi(y) for y in taninmayan)} — "
            "ad şablonu değişmiş olabilir; bu bülten sessizce atlanırsa o "
            "dönemin ayları eksik kalır"
        )
    return baglantilar


def cekilecek_bultenler(baglantilar: dict[str, str], bugun: date) -> list[str]:
    """Yıl başına en güncel bülteni seçer.

    Bir bülten o yılın tüm aylarını taşıdığı için yıl başına bir dosya
    yeter. Her yıl için indeksteki EN GÜNCEL bülten seçilir (ay ne olursa
    olsun); cari yılın en güncel bülteni zaten o yılın seçimi olur.

    Delik denetimi: seçilen yıllar arasında, SON yıl dışındaki her yılın
    seçimi Aralık (`.12`) olmalı ve yıllar kesintisiz ardışık olmalı. Aksi
    halde (ör. 2024'ün en güncel bülteni `.11` ama 2025 var) iki tarafında
    veri bulunan aylar sessizce eksik kalır — RuntimeError. Son yılın
    Aralık'tan önce bitmesi meşrudur: kalan aylar henüz yayımlanmadı
    (ör. Ocak'ta önceki yılın Aralık bülteni henüz yokken `.11`); bu bir
    delik değil, tazelikle ilgili bir durumdur (bayat seri raporu izler).
    Pencere başındaki eksik yıllar da delik değildir (seri daha geç başlar).
    """
    en_eski_yil = bugun.year - VARSAYILAN_GECMIS_YIL
    en_iyi: dict[int, str] = {}
    for a in baglantilar:
        y = int(a[:4])
        if y >= en_eski_yil:
            en_iyi[y] = max(en_iyi.get(y, ""), a)
    yillar = sorted(en_iyi)
    for onceki, sonraki in zip(yillar, yillar[1:]):
        if sonraki != onceki + 1:
            eksik = ", ".join(str(y) for y in range(onceki + 1, sonraki))
            raise RuntimeError(
                f"OSD indeksinde {eksik} yılı için belge yok ama {onceki} ve "
                f"{sonraki} var — aradaki aylar sessizce eksik kalırdı"
            )
        if not en_iyi[onceki].endswith(".12"):
            raise RuntimeError(
                f"OSD indeksinde {onceki} yılının Aralık belgesi yok (en "
                f"güncel: {en_iyi[onceki]}) ama {sonraki} var — {onceki} "
                "yılının kalan ayları sessizce eksik kalırdı"
            )
    return [en_iyi[y] for y in yillar]


def firma_adini_normalize(ham: str) -> str:
    """Null baytı, satır sonlarını ve fazla boşluğu temizler.

    Eski bültenlerde font kodlaması Türkçe karakterlerde `\\x00` sızdırıyor
    (`"T\\x00pler"`); normalizasyon olmazsa firma katalogla eşleşmez.
    """
    return " ".join(ham.replace("\x00", "").split())


def sayi_parse(ham: str | None) -> float | None:
    """Türkçe biçimli tam sayı: `36.548` → 36548.0. `-` ve boş → None.

    `-` kaynağın kendi "üretim/ihracat yok" işaretidir (meşru boşluk; birçok
    seri bu yüzden `yayin_notu` taşır). Dolu ama sayı olmayan bir hücre ise
    ValueError: önceki sürüm burada None dönüyordu ve okunamayan bir ay
    "-" gibi sessizce atlanıyordu.
    """
    metin = (ham or "").strip()
    if not metin or metin == "-":
        return None
    try:
        return float(metin.replace(".", "").replace(",", "."))
    except ValueError:
        raise ValueError(f"OSD hücresi sayı olarak okunamadı: {ham!r}") from None


_URETIM = "OSD Üretim Bülteni"
_DIS_SATIS = "OSD Dış Satışlar"


def _ay_hucresi(satir: list, ay: int, yil: int, belge: str) -> float | None:
    """`sayi_parse(satir[ay])`; okunamazsa hata mesajına belge, satır ve
    dönem eklenir (hangi ayın okunamadığı ingest çıktısında görünsün)."""
    try:
        return sayi_parse(satir[ay])
    except ValueError as hata:
        ad = firma_adini_normalize(satir[0] or "")
        raise ValueError(f"{belge} — {ad} {yil}-{ay:02d}: {hata}") from None


def _firma_satiri_mi(ad: str) -> bool:
    if not ad or ad.startswith(_ATLANACAK_ONEKLER):
        return False
    # "OTOMOBİL Toplam / Pass.Car Total", "TOPLAM / TOTAL" gibi toplam
    # satırları büyük/küçük harf farkı gözetmeksizin elenir.
    kucuk = ad.lower()
    return "toplam" not in kucuk and "total" not in kucuk


def firma_aylik_noktalari(
    tablolar: list, yil: int, gorulen: set[str] | None = None,
) -> list[tuple[str, str, float]]:
    """6–9. sayfa tablolarından `(firma, "YYYY-MM-01", adet)` üretir.

    Bir firma birden çok araç tipi bölümünde görünür (Ford Otosan hem
    kamyonette hem minibüste); bölümler boyunca TOPLANIR — firma toplam
    üretimi budur ve 2. sayfanın TOPLAM sütunuyla birebir tutar.

    `gorulen` verilirse tablodaki HER firma satırının adı ona eklenir — tüm
    hücreleri "-" olan satırlar dahil (bkz. `_bultende_firma_yok`).
    """
    toplam: dict[tuple[str, str], float] = defaultdict(float)
    for tablo in tablolar:
        for satir in tablo[1:]:
            ad = firma_adini_normalize(satir[0] or "")
            if not _firma_satiri_mi(ad):
                continue
            if gorulen is not None:
                gorulen.add(ad)
            for ay in range(1, 13):
                deger = _ay_hucresi(satir, ay, yil, _URETIM)
                if deger is not None:
                    toplam[(ad, f"{yil}-{ay:02d}-01")] += deger
    return [(ad, tarih, deger) for (ad, tarih), deger in toplam.items()]

def firma_aylik_noktalari_arac_tipli(
    tablolar: list, yil: int, gorulen: set[str] | None = None,
) -> list[tuple[str, str, str, float]]:
    """6–9. sayfa tablolarından `(firma, araç_tipi, "YYYY-MM-01", adet)` üretir.

    `firma_aylik_noktalari`nin aksine araç tipi bölümünü (OTOMOBİL, K.KAMYON,
    B.KAMYON, KAMYONET, OTOBÜS, MİNİBÜS, MİDİBÜS, TRAKTÖR) KORUR — marka
    sayfalarındaki (ör. ASUZU Hafif Kamyon Üretimi) tek-tip kartlar bunu
    ister. Tip adı, bölümü kapatan "<TİP> Toplam / ..." satırından çıkarılır;
    bir firma o bölümde hiç üretmediyse (satırı yoksa ya da tüm ayları "-")
    o (firma, tip) için hiç nokta üretilmez — bu sessiz veri kaybı değil,
    gerçek iş durumudur (osd_arac_tipi filtreli okuma bunu 0 değil "o
    dönemde üretim yok" olarak yorumlar, tıpkı kaynağın kendisi gibi).

    `gorulen` verilirse her firma satırının adı ona eklenir — tüm hücreleri
    "-" olan satırlar dahil (bkz. `_bultende_firma_yok`).
    """
    sonuc: list[tuple[str, str, str, float]] = []
    for tablo in tablolar:
        arabellek: list[tuple[str, str, float]] = []
        bolum_satirlari: list[list] = []
        for satir in tablo[1:]:
            ad = firma_adini_normalize(satir[0] or "")
            if not ad or ad.startswith(_ATLANACAK_ONEKLER):
                continue
            if "toplam" in ad.lower():
                tip = re.split(r"\s+Toplam\b", ad, maxsplit=1, flags=re.IGNORECASE)[0].strip()
                if bolum_satirlari:
                    _bolum_toplamini_dogrula(tip, bolum_satirlari, satir, yil)
                sonuc.extend((firma, tip, tarih, deger) for firma, tarih, deger in arabellek)
                arabellek = []
                bolum_satirlari = []
                continue
            bolum_satirlari.append(satir)
            if gorulen is not None:
                gorulen.add(ad)
            for ay in range(1, 13):
                deger = _ay_hucresi(satir, ay, yil, _URETIM)
                if deger is not None:
                    arabellek.append((ad, f"{yil}-{ay:02d}-01", deger))
        if bolum_satirlari:
            # Önceki sürüm bu satırları sessizce düşürüyordu (arabellek
            # yalnızca bir "Toplam" satırında boşaltılıyordu).
            adlar = ", ".join(firma_adini_normalize(s[0] or "") for s in bolum_satirlari)
            raise RuntimeError(
                f"OSD Üretim Bülteni {yil}: tablo, bölüm toplam satırı gelmeden "
                f"bitti ({adlar}) — araç tipi belirlenemedi, şablon değişmiş olabilir"
            )
    return sonuc


def _bolum_toplamini_dogrula(tip: str, firma_satirlari: list, toplam_satiri: list,
                             yil: int) -> None:
    """Bir araç tipi bölümünde her ay için firma satırlarının toplamını
    bölümün kendi "<TİP> Toplam" satırıyla karşılaştırır.

    2. sayfa doğrulaması (`dogrula`) yalnızca bültenin KENDİ ayını
    denetler; bu denetim yılın diğer aylarında okunamayan/kayan bir hücrenin
    (ör. boş okunan bir firma hücresi) sessizce düşmesini yakalar. `-` her
    iki tarafta da 0 sayılır (kaynağın "üretim yok" işareti).
    """
    for ay in range(1, 13):
        beklenen = _ay_hucresi(toplam_satiri, ay, yil, _URETIM) or 0.0
        bulunan = sum(_ay_hucresi(s, ay, yil, _URETIM) or 0.0 for s in firma_satirlari)
        if abs(bulunan - beklenen) > 0.5:
            raise RuntimeError(
                f"OSD Üretim Bülteni öz-doğrulama — {tip} {yil}-{ay:02d}: "
                f"firma toplamı {bulunan:,.0f}, bölüm toplamı {beklenen:,.0f}"
            )


def ay_toplamlari(s2_tablosu: list) -> dict[str, float]:
    """2. sayfanın `TOPLAM` sütunundan `firma -> adet` çıkarır (sütun 17)."""
    toplamlar = {}
    for satir in s2_tablosu[1:]:
        ad = firma_adini_normalize(satir[0] or "")
        if not _firma_satiri_mi(ad):
            continue
        deger = sayi_parse(satir[17])
        if deger is not None:
            toplamlar[ad] = deger
    return toplamlar


# Bülten 13 firma içerir. `toplamlar` bundan az firma taşıyorsa (ör. OSD
# 2. sayfaya bir sütun eklerse/araya sayfa sokarsa `sayi_parse` tüm satırlar
# için None döner ve `ay_toplamlari` neredeyse boş kalır) bu, döngünün hiç
# dönmediği (ya da az döndüğü) anlamına gelir — dilimin TEK güvenlik ağı
# sessizce no-op'a düşer. Bu yüzden döngüden önce sayı ayrıca kontrol edilir.
ASGARI_FIRMA_SAYISI = 13


def dogrula(
    noktalar: list[tuple[str, str, float]],
    toplamlar: dict[str, float],
    ay_tarihi: str,
) -> None:
    """6–9. sayfa toplamını 2. sayfanın TOPLAM sütunuyla karşılaştırır."""
    if len(toplamlar) < ASGARI_FIRMA_SAYISI:
        raise RuntimeError(
            f"OSD öz-doğrulama: 2. sayfada yalnızca {len(toplamlar)} firma "
            f"bulundu, beklenen en az {ASGARI_FIRMA_SAYISI} — sayfa yapısı "
            "değişmiş olabilir (sütun kayması, araya sayfa eklenmesi vb.)"
        )
    ay_noktalari = {ad: deger for ad, tarih, deger in noktalar if tarih == ay_tarihi}
    for ad, beklenen in toplamlar.items():
        bulunan = ay_noktalari.get(ad)
        if bulunan is None:
            raise RuntimeError(
                f"OSD öz-doğrulama: {ad} 2. sayfada var ({beklenen:,.0f}) ama "
                f"6–9. sayfalarda {ay_tarihi} için hiç noktası yok"
            )
        if abs(bulunan - beklenen) > 0.5:
            raise RuntimeError(
                f"OSD öz-doğrulama: {ad} {ay_tarihi} — 6–9. sayfa toplamı "
                f"{bulunan:,.0f}, 2. sayfa TOPLAM {beklenen:,.0f}"
            )


ZAMAN_ASIMI = 60
_SAYFA_FIRMA_AY = (5, 6, 7, 8)  # 6–9. sayfalar (0-tabanlı)
_SAYFA_AY_TOPLAM = 1            # 2. sayfa


def _indeks_cek(session=None) -> dict[str, str]:
    http = session or requests
    yanit = http.get(INDEKS_URL, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    return bulten_baglantilari(yanit.text)


def _pdf_indir(url: str, session=None) -> bytes:
    http = session or requests
    yanit = http.get(url, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    return yanit.content


def _bulteni_ayristir(
    baytlar: bytes, anahtar: str,
) -> tuple[list[tuple[str, str, float]], frozenset[str]]:
    """Bir bültenin firma×ay noktalarını ve bültende satırı bulunan firma
    adlarını (tümü "-" olanlar dahil) çıkarır; öz-doğrulamayı koşar."""
    yil, ay = int(anahtar[:4]), int(anahtar[5:7])
    gorulen: set[str] = set()
    with pdfplumber.open(io.BytesIO(baytlar)) as pdf:
        tablolar = [
            t for i in _SAYFA_FIRMA_AY for t in pdf.pages[i].extract_tables()
        ]
        noktalar = firma_aylik_noktalari(tablolar, yil, gorulen)
        # Yalnızca öz-doğrulama için: bölüm toplamlarını yılın TÜM aylarında
        # denetler (2. sayfa yalnızca bültenin kendi ayını doğrulayabilir).
        firma_aylik_noktalari_arac_tipli(tablolar, yil)
        toplamlar = ay_toplamlari(pdf.pages[_SAYFA_AY_TOPLAM].extract_tables()[0])
    dogrula(noktalar, toplamlar, f"{yil}-{ay:02d}-01")
    return noktalar, frozenset(gorulen)

def _bulten_baytlarini_getir(
    anahtar: str, baglantilar: dict[str, str], onbellek: dict, session=None,
) -> bytes:
    """PDF baytlarını önbellekler — toplam ve araç-tipli okuma aynı indirmeyi
    paylaşsın diye (`_bulteni_ayristir` yalnızca ayrıştırılmış SONUCU
    önbellekler, baytların kendisini değil)."""
    bayt_anahtari = f"{anahtar}:baytlar"
    if bayt_anahtari not in onbellek:
        onbellek[bayt_anahtari] = _pdf_indir(baglantilar[anahtar], session)
    return onbellek[bayt_anahtari]


def _bultendeki_tipli_okuma(
    baytlar: bytes, anahtar: str,
) -> tuple[list[tuple[str, str, str, float]], frozenset[str]]:
    """Bir bültenin (firma, araç_tipi, tarih, adet) noktalarını ve satırı
    bulunan firma adlarını (tümü "-" olanlar dahil) çıkarır.

    Ayrı öz-doğrulama YOK: aynı bülten baytları toplam yoluyla zaten
    `dogrula()`den geçmiş olur (ikisi aynı `onbellek` altında paylaşılır);
    tip kırılımı yalnızca doğrulanmış toplamın nasıl dağıldığını gösterir.
    """
    yil = int(anahtar[:4])
    with pdfplumber.open(io.BytesIO(baytlar)) as pdf:
        tablolar = [t for i in _SAYFA_FIRMA_AY for t in pdf.pages[i].extract_tables()]
    gorulen: set[str] = set()
    noktalar = firma_aylik_noktalari_arac_tipli(tablolar, yil, gorulen)
    return noktalar, frozenset(gorulen)


def _uretim_arac_tipi_cek(
    seri, onbellek: dict, session, bugun: date, arac_tipi: str,
) -> pd.DataFrame:
    """`osd_arac_tipi` verilen seriler: firma toplamı yerine tek araç tipi
    bölümünün adedini döner (bkz. `firma_aylik_noktalari_arac_tipli`).

    Firmanın SATIRI çekilen bültenlerden BİRİNDE bile (herhangi bir tipte)
    yoksa RuntimeError — ana yoldaki bülten-bazlı kısmi kayıp kontrolüyle aynı
    gerekçe ve aynı `start_date` muafiyeti (`_bultende_firma_yok`). Önceki
    sürüm yalnızca TÜM bültenlerde yoksa yükseliyordu; tek bir yılın
    bülteninde ad değişirse o yıl sessizce düşerdi. Firma bültende var ama
    o TİPTE hiç üretmediyse (ör. ASUZU'nun kamyonet üretmediği aylar) nokta
    üretilmez — bu gerçek iş durumudur ("-"), hata değil.
    """
    if "indeks" not in onbellek:
        onbellek["indeks"] = _indeks_cek(session)
    baglantilar = onbellek["indeks"]

    isimler = {seri.osd_firma, *(getattr(seri, "osd_eski_adlar", None) or ())}

    kendi: dict[str, float] = {}
    firma_bulundu = False
    for anahtar in cekilecek_bultenler(baglantilar, bugun):
        tipli_anahtar = f"{anahtar}:tipli"
        if tipli_anahtar not in onbellek:
            baytlar = _bulten_baytlarini_getir(anahtar, baglantilar, onbellek, session)
            onbellek[tipli_anahtar] = _bultendeki_tipli_okuma(baytlar, anahtar)

        noktalar, gorulen = onbellek[tipli_anahtar]
        if not isimler & gorulen:
            _bultende_firma_yok(seri, anahtar, "bülteninde")
            continue
        firma_bulundu = True
        for ad, tip, tarih, deger in noktalar:
            if ad in isimler and tip == arac_tipi:
                kendi[tarih] = kendi.get(tarih, 0.0) + deger

    if not firma_bulundu:
        raise RuntimeError(
            f"OSD bültenlerinde firma bulunamadı: {seri.osd_firma!r} "
            f"({seri.id}) — katalogdaki ad bültenle eşleşmiyor olabilir"
        )

    df = pd.DataFrame(sorted(kendi.items()), columns=["date", "value"])
    if seri.start_date:
        df = df[df["date"] >= seri.start_date]
    return df.reset_index(drop=True)


# --- OSD Aylık Değerlendirme Raporu: "Dış Satışlar" (ihracat) ---
#
# Üretim Bülteni'nde ihracat verisi YOK (yalnızca üretim). İhracat, OSD'nin
# AYRI bir aylık belgesinde ("Otomotiv Sektörü Aylık Değerlendirme Raporu")
# "Dış Satışlar" başlıklı 2 sayfalık bir bölümde yayımlanır: özet tablo
# (araç tipi × ay, tüm firmalar toplu) + yedi firma-bazlı tablo (araç tipi
# başına biri). Üretim tarafının B.KAMYON (Ağır Kamyon) / K.KAMYON (Hafif
# Kamyon) ayrımı burada firma bazında YOK — ikisi "KAMYON" adıyla tek
# tabloda birleşik gelir (özet tabloda hâlâ iki ayrı satırdır).
#
# Ölçüldü (2026-09-18, Ağustos 2026 raporu): A.I.O.S. Otobüs/Midibüs
# ihracatı 19/44, OTOKAR Kamyon/Otobüs/Midibüs 16/113/20, KARSAN
# Otobüs/Minibüs 5/2 — referans platformla birebir.

DEGERLENDIRME_INDEKS_URL = f"{TABAN}/osd-yayinlari/otomotiv-sektoru-aylik-degerlendirme-raporlari"

# Dosya adı (yolun son parçası) şablonları, ölçüldü 2026-11-27:
#   "08-2026-OSD_Aylik_Degerlendirme_Raporu.pdf" (2023+ tire),
#   "12-2022_OSD_Aylik_Degerlendirme_Raporu.pdf" (2021–2022 alt çizgi),
#   "01-2020 OSD Aylık Değerlendirme Raporu.pdf" (2020, boşluklu),
#   "02-2025-OSD_Aylik_Degerlendirme_Raporu__.pdf" (sonekli yeniden yükleme).
_DEGERLENDIRME_AY_YIL = re.compile(
    r"^(\d{2})[-_ ](\d{4})[-_ ]OSD[_ ]Ayl[iı]k[_ ]De[gğ]erlendirme[_ ]Raporu[^/]*\.pdf$"
)
#   "2019-07 OSD Aylık Değerlendirme Raporu.pdf",
#   "2018-10 OSD Aylık Değerlendirme Raporu_Final.pdf" (2018–2019).
_DEGERLENDIRME_YIL_AY = re.compile(
    r"^(\d{4})-(\d{2}) OSD Ayl[iı]k De[gğ]erlendirme Raporu[^/]*\.pdf$"
)
# Yıllık (aylık değil) raporlar, 2006–2017: "2017 OSD Değerlendirme
# Raporu.pdf". Ay tablosu taşımadıkları için BİLEREK okunmaz.
_DEGERLENDIRME_YILLIK = re.compile(r"^\d{4} OSD De[gğ]erlendirme Raporu\.pdf$")
# Adı ayı taşımayan iki aylık rapor; ay, PDF'in ilk sayfasından ve indeksteki
# bağlantı metninden doğrulandı (2026-11-27). Önceki sürüm bunları sessizce
# atlıyordu: 2021'in en güncel raporu 11-2021 seçildiği için 11 ihracat
# serisinde 2021-12 eksikti (CSV'ler 2021-01..2026-10, 70 yerine 69 satır).
BILINEN_DEGERLENDIRME_DOSYALARI = {
    # 1. sayfa "ARALIK 2021", bağlantı metni "2021 ARALIK"
    "d55b533b-d6c1-4fd7-857e-83bfbfcc7ab7.pdf": "2021.12",
    # 1. sayfa "TEMMUZ 2025", bağlantı metni "TEMMUZ 2025"
    "Aylık Rapor_07.pdf": "2025.07",
}


def _degerlendirme_anahtari(dosya: str) -> str | None:
    """Dosya adından `"YYYY.MM"`; yıllık rapor için None; tanınmazsa KeyError."""
    if dosya in BILINEN_DEGERLENDIRME_DOSYALARI:
        return BILINEN_DEGERLENDIRME_DOSYALARI[dosya]
    if m := _DEGERLENDIRME_AY_YIL.match(dosya):
        return f"{m.group(2)}.{m.group(1)}"
    if m := _DEGERLENDIRME_YIL_AY.match(dosya):
        return f"{m.group(1)}.{m.group(2)}"
    if _DEGERLENDIRME_YILLIK.match(dosya):
        return None
    raise KeyError(dosya)


def degerlendirme_baglantilari(html: str) -> dict[str, str]:
    """İndeks HTML'inden `"YYYY.MM" -> tam URL` eşlemesi çıkarır.

    İndeksteki HER PDF bağlantısı sınıflandırılır: aylık rapor şablonları,
    `BILINEN_DEGERLENDIRME_DOSYALARI` ve bilerek okunmayan yıllık raporlar.
    Hiçbirine uymayan bir dosya varsa RuntimeError — önceki sürüm onu
    sessizce dışarıda bırakıyordu; o ay yılın en güncel raporuysa o yılın
    kalan ayları (bkz. 2021-12) iz bırakmadan kayboluyordu.
    """
    baglantilar: dict[str, str] = {}
    taninmayan: list[str] = []
    for yol in dict.fromkeys(_HER_PDF.findall(html)):
        dosya = _dosya_adi(yol)
        try:
            anahtar = _degerlendirme_anahtari(dosya)
        except KeyError:
            taninmayan.append(dosya)
            continue
        if anahtar is not None:
            baglantilar[anahtar] = TABAN + yol.replace("\\", "/")
    if taninmayan:
        raise RuntimeError(
            "OSD Aylık Değerlendirme Raporu indeksinde dosya adı tanınmayan "
            f"rapor var ({DEGERLENDIRME_INDEKS_URL}): {', '.join(taninmayan)} — "
            "ad şablonu değişmiş olabilir; ayı doğrulayıp "
            "BILINEN_DEGERLENDIRME_DOSYALARI'na ya da şablona ekleyin"
        )
    if not baglantilar:
        raise RuntimeError(
            "OSD Aylık Değerlendirme Raporu indeksinde bağlantı bulunamadı "
            f"({DEGERLENDIRME_INDEKS_URL}) — sayfa yapısı değişmiş olabilir"
        )
    return baglantilar


def _dis_satis_indeks_cek(session=None) -> dict[str, str]:
    http = session or requests
    yanit = http.get(DEGERLENDIRME_INDEKS_URL, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    return degerlendirme_baglantilari(yanit.text)


# Bazı bülten yılları (ör. 2023/2024 Aralık) font kodlaması yüzünden "i"
# harflerini metinden düşürüyor ("Otomotiv Sanayii" -> "Otomotv Sanay",
# `firma_adini_normalize`'ın \x00 notuyla aynı köken); "Dış Satışlar" bu
# aylarda da BOZULMADAN geliyor, o yüzden yalnızca bu kısım aranır.
_DIS_SATIS_BASLIK = "Dış Satışlar"
# Firma bazlı tabloların (özet tablo hariç) rapordaki sabit sırası.
DIS_SATIS_TIP_SIRASI = (
    "OTOMOBİL", "KAMYONET", "MİNİBÜS", "KAMYON", "MİDİBÜS", "OTOBÜS", "TRAKTÖR",
)


def _dis_satis_sayfalarini_bul(pdf) -> list[int]:
    return [
        i for i, sayfa in enumerate(pdf.pages)
        if _DIS_SATIS_BASLIK in (sayfa.extract_text() or "")
    ]


def firma_bazli_dis_satis_tablolarindan(
    tablolar: list, yil: int, gorulen: set[str] | None = None,
) -> list[tuple[str, str, str, float]]:
    """Firma bazlı tablo listesinden (özet tablo HARİÇ, `DIS_SATIS_TIP_SIRASI`
    sırasında) `(firma, araç_tipi, "YYYY-MM-01", adet)` üretir.

    Öz-doğrulama: her tablonun kendi "TOPLAM - Total" satırı, o tablodaki
    firma satırlarının toplamıyla karşılaştırılır; tablo sayısı beklenenden
    (7) farklıysa da RuntimeError — sayfa şablonu değişmiş olabilir,
    sessizce eksik/yanlış veri üretmektense ingest kırılmalı. PDF/bayt
    bağımlılığı yok — `dis_satis_okumasi` bu fonksiyonu sarmalar.

    `gorulen` verilirse her firma satırının adı ona eklenir — tüm hücreleri
    "-" olan satırlar dahil (bkz. `_bultende_firma_yok`).
    """
    if len(tablolar) != len(DIS_SATIS_TIP_SIRASI):
        raise RuntimeError(
            f"OSD Dış Satışlar'da {len(tablolar)} firma tablosu bulundu, "
            f"beklenen {len(DIS_SATIS_TIP_SIRASI)} — şablon değişmiş olabilir"
        )

    sonuc: list[tuple[str, str, str, float]] = []
    for tip, tablo in zip(DIS_SATIS_TIP_SIRASI, tablolar):
        toplam_satiri = None
        firma_satirlari: list[tuple[str, list]] = []
        for satir in tablo[1:]:
            ad = firma_adini_normalize(satir[0] or "")
            if not ad:
                continue
            if ad.upper().startswith("TOPLAM"):
                toplam_satiri = satir
                continue
            firma_satirlari.append((ad, satir))
            if gorulen is not None:
                gorulen.add(ad)

        if toplam_satiri is None:
            raise RuntimeError(f"OSD Dış Satışlar — {tip} tablosunda TOPLAM satırı yok")

        for ay in range(1, 13):
            beklenen = _ay_hucresi(toplam_satiri, ay, yil, _DIS_SATIS) or 0.0
            bulunan = sum(_ay_hucresi(satir, ay, yil, _DIS_SATIS) or 0.0
                          for _, satir in firma_satirlari)
            if abs(bulunan - beklenen) > 0.5:
                raise RuntimeError(
                    f"OSD Dış Satışlar öz-doğrulama — {tip} {yil}-{ay:02d}: "
                    f"firma toplamı {bulunan:,.0f}, TOPLAM satırı {beklenen:,.0f}"
                )

        for ad, satir in firma_satirlari:
            for ay in range(1, 13):
                deger = _ay_hucresi(satir, ay, yil, _DIS_SATIS)
                if deger is not None:
                    sonuc.append((ad, tip, f"{yil}-{ay:02d}-01", deger))
    return sonuc


def dis_satis_okumasi(
    baytlar: bytes,
) -> tuple[list[tuple[str, str, str, float]], frozenset[str]]:
    """Değerlendirme Raporu'nun "Dış Satışlar" sayfalarından
    `(firma, araç_tipi, "YYYY-MM-01", adet)` noktalarını ve satırı bulunan
    firma adlarını (tümü "-" olanlar dahil) üretir (bkz.
    `firma_bazli_dis_satis_tablolarindan`)."""
    with pdfplumber.open(io.BytesIO(baytlar)) as pdf:
        sayfalar = _dis_satis_sayfalarini_bul(pdf)
        if len(sayfalar) < 2:
            raise RuntimeError(
                f"OSD Değerlendirme Raporu'nda '{_DIS_SATIS_BASLIK}' sayfaları "
                f"bulunamadı ({len(sayfalar)} sayfa) — şablon değişmiş olabilir"
            )
        yil_eslesme = re.search(r"\b(20\d{2})\b", pdf.pages[sayfalar[0]].extract_text() or "")
        if not yil_eslesme:
            raise RuntimeError("OSD Dış Satışlar sayfasında yıl bulunamadı")
        yil = int(yil_eslesme.group(1))

        # Özet tablo (araç tipi × ay, firma bazlı değil) HER ZAMAN ilk
        # bulunan sayfanın ilk tablosudur; başlık metniyle eşleştirmek
        # yerine konumsal atlama tercih edilir — bazı bülten yılları (2023/
        # 2024 Aralık) font kodlaması başlığı bozuyor ("Araç Tipleri" ->
        # "Araç Tipler\x00", \x00 temizlense bile sondaki "i" düşüyor) ve
        # metin eşleşmesi sessizce başarısız olup özet tabloyu firma
        # tablosu sanabilirdi.
        tablolar: list[list] = []
        for sayfa_sirasi, sayfa_no in enumerate(sayfalar):
            sayfa_tablolari = pdf.pages[sayfa_no].extract_tables()
            if sayfa_sirasi == 0 and sayfa_tablolari:
                sayfa_tablolari = sayfa_tablolari[1:]
            tablolar.extend(sayfa_tablolari)

    gorulen: set[str] = set()
    noktalar = firma_bazli_dis_satis_tablolarindan(tablolar, yil, gorulen)
    return noktalar, frozenset(gorulen)


def _bultende_firma_yok(seri, anahtar: str, belge: str) -> None:
    """Firmanın SATIRI tek bir belgede (bülten/rapor) yoksa RuntimeError; o
    yıl `start_date` yılından önceyse muaf (firma henüz yok).

    Ölçüt değer değil SATIR varlığıdır: satır var ama tüm hücreleri "-"
    ise (ör. KARSAN'ın 2023-01, 2025-01 ve 2025-02'de hiç ihracatı yok —
    karsan-toplam-ihracat.csv'de bu aylar yok) firma o belgede VARDIR ve
    meşru bir sıfır aydır. Değer bazlı bir ölçüt, böyle bir ay en güncel
    rapor olduğu sürece (haftalarca) ingest'i kırmızıya çevirirdi.
    """
    baslangic_yili = int(seri.start_date[:4]) if seri.start_date else None
    if baslangic_yili is not None and int(anahtar[:4]) < baslangic_yili:
        return
    raise RuntimeError(
        f"OSD {belge} firma bulunamadı: {seri.osd_firma!r} ({seri.id}) — "
        f"belge {anahtar} — o yılın ayları sessizce eksik kalırdı; ad "
        "değişmiş olabilir (osd_eski_adlar'a eklemeyi düşünün)"
    )


def _rapor_yilini_dogrula(noktalar: list, anahtar: str) -> None:
    """Dış Satışlar sayfasından okunan yıl indeks anahtarının yılıyla aynı
    olmalı; değilse o yılın ayları başka bir yılın üzerine yazılır ve
    kendi yılı sessizce boş kalır."""
    yil = anahtar[:4]
    yanlis = sorted({tarih[:4] for _, _, tarih, _ in noktalar if tarih[:4] != yil})
    if yanlis:
        raise RuntimeError(
            f"OSD Dış Satışlar raporu {anahtar}: sayfadan okunan yıl "
            f"{', '.join(yanlis)}, beklenen {yil}"
        )


def _ihracat_cek(
    seri, onbellek: dict, session, bugun: date, arac_tipi: str | None,
) -> pd.DataFrame:
    """`osd_veri_tipi="ihracat"` serileri: Değerlendirme Raporu'nun "Dış
    Satışlar" bölümünden firma×araç-tipi ihracat adedi.

    `arac_tipi` None ise firmanın TÜM tiplerdeki ihracatı toplanır (firma
    toplamı); verilmişse yalnızca o tip.
    """
    if "dis_satis_indeks" not in onbellek:
        onbellek["dis_satis_indeks"] = _dis_satis_indeks_cek(session)
    baglantilar = onbellek["dis_satis_indeks"]

    isimler = {seri.osd_firma, *(getattr(seri, "osd_eski_adlar", None) or ())}

    kendi: dict[str, float] = {}
    firma_bulundu = False
    for anahtar in cekilecek_bultenler(baglantilar, bugun):
        nokta_anahtari = f"dis_satis:{anahtar}"
        if nokta_anahtari not in onbellek:
            bayt_anahtari = f"dis_satis:{anahtar}:baytlar"
            if bayt_anahtari not in onbellek:
                onbellek[bayt_anahtari] = _pdf_indir(baglantilar[anahtar], session)
            okuma = dis_satis_okumasi(onbellek[bayt_anahtari])
            _rapor_yilini_dogrula(okuma[0], anahtar)
            onbellek[nokta_anahtari] = okuma

        noktalar, gorulen = onbellek[nokta_anahtari]
        if not isimler & gorulen:
            _bultende_firma_yok(seri, anahtar, "Dış Satışlar raporunda")
            continue
        firma_bulundu = True
        for ad, tip, tarih, deger in noktalar:
            if ad in isimler and (arac_tipi is None or tip == arac_tipi):
                kendi[tarih] = kendi.get(tarih, 0.0) + deger

    if not firma_bulundu:
        raise RuntimeError(
            f"OSD Dış Satışlar raporunda firma bulunamadı: {seri.osd_firma!r} "
            f"({seri.id}) — katalogdaki ad raporla eşleşmiyor olabilir"
        )

    df = pd.DataFrame(sorted(kendi.items()), columns=["date", "value"])
    if seri.start_date:
        df = df[df["date"] >= seri.start_date]
    return df.reset_index(drop=True)


def seri_cek(seri, onbellek: dict | None = None, session=None,
             bugun: date | None = None) -> pd.DataFrame:
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı).

    `osd_arac_tipi`/`osd_veri_tipi` verilmemişse (mevcut 13 firma serisi)
    davranış TAMAMEN değişmez: firma toplamı, Üretim Bülteni'nden. İkisinden
    biri verilirse `_uretim_arac_tipi_cek`/`_ihracat_cek`'e devredilir (bkz.
    o fonksiyonların docstring'i).

    `onbellek` verilirse indeks ve ayrıştırılmış bülten noktaları koşu
    boyunca paylaşılır: 13 seri aynı beş PDF'i okuduğu için yoksa 65
    indirme olurdu.

    Firma OSD bültenlerinde zaman içinde ad değiştirebilir (ör. HYUNDAI
    ASSAN -> HYUNDAI MOTOR TÜRKİYE); `seri.osd_eski_adlar` verilirse eski
    adlarla yazılmış noktalar da toplanır. Ayrıca her çekilen bülten AYRI
    AYRI kontrol edilir: firma (hangi adıyla olursa olsun) o bültende hiç
    yoksa RuntimeError yükselir — beş bültenden birinde kısmi kayıp olması
    "hiç eşleşme yok" durumuna göre çok daha sık ve sessizce geçebilir,
    bu yüzden toplam kontrolü yeterli değildir. Firmanın gerçekten henüz
    üretime başlamadığı dönemler için kaçış yolu `start_date`: o tarihin
    yılından ÖNCEKİ bültenler bu kontrolden muaftır.
    """
    bugun = bugun or date.today()
    onbellek = {} if onbellek is None else onbellek

    veri_tipi = getattr(seri, "osd_veri_tipi", None) or "uretim"
    arac_tipi = getattr(seri, "osd_arac_tipi", None)
    if veri_tipi == "ihracat":
        return _ihracat_cek(seri, onbellek, session, bugun, arac_tipi)
    if arac_tipi is not None:
        return _uretim_arac_tipi_cek(seri, onbellek, session, bugun, arac_tipi)

    if "indeks" not in onbellek:
        onbellek["indeks"] = _indeks_cek(session)
    baglantilar = onbellek["indeks"]

    isimler = {seri.osd_firma, *(getattr(seri, "osd_eski_adlar", None) or ())}
    baslangic_yili = int(seri.start_date[:4]) if seri.start_date else None

    kendi: dict[str, float] = {}
    for anahtar in cekilecek_bultenler(baglantilar, bugun):
        if anahtar not in onbellek:
            baytlar = _pdf_indir(baglantilar[anahtar], session)
            onbellek[anahtar] = _bulteni_ayristir(baytlar, anahtar)

        noktalar, gorulen = onbellek[anahtar]
        bu_bultendeki_noktalar = [
            (ad, tarih, deger) for ad, tarih, deger in noktalar
            if ad in isimler
        ]
        # Satır varlığı ölçütü (bkz. `_bultende_firma_yok`): satırı var ama
        # tüm ayları "-" olan firma o bültende VARDIR (meşru sıfır).
        if not isimler & gorulen:
            bulten_yili = int(anahtar[:4])
            if baslangic_yili is not None and bulten_yili < baslangic_yili:
                continue  # start_date'ten önceki yıl — firma henüz yok, muaf
            raise RuntimeError(
                f"OSD bülteninde firma bulunamadı: {seri.osd_firma!r} "
                f"({seri.id}) — bülten {anahtar} — katalogdaki ad(lar) "
                "bültenle eşleşmiyor olabilir (ad değişmiş olabilir, "
                "osd_eski_adlar'a eklemeyi düşünün)"
            )
        # Aynı bültende hem eski hem yeni ad AYNI ay için nokta üretebilir
        # (alias çakışması); üzerine yazmak yerine TOPLANIR, aksi halde
        # biri sessizce kaybolur. Farklı bültenler arasında ise en son
        # işlenen bültenin değeri geçerli olur (revizyonları yakalamak
        # için istenen davranış budur).
        bu_bulten: dict[str, float] = defaultdict(float)
        for _, tarih, deger in bu_bultendeki_noktalar:
            bu_bulten[tarih] += deger
        kendi.update(bu_bulten)

    if not kendi:
        raise RuntimeError(
            f"OSD bültenlerinde firma bulunamadı: {seri.osd_firma!r} "
            f"({seri.id}) — katalogdaki ad bültenle eşleşmiyor olabilir"
        )

    df = pd.DataFrame(sorted(kendi.items()), columns=["date", "value"])
    if seri.start_date:
        df = df[df["date"] >= seri.start_date]
    return df.reset_index(drop=True)
