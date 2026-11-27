"""ebebek Mağazacılık A.Ş. Yatırımcı İlişkileri aylık operasyonel veri istemcisi.

Kaynak: `kurumsal.ebebek.com/yatirimci-duyurulari` — "Özel Durum Açıklamaları"
grubu altında her ay üç ayrı KAP bildirimi (PDF) yayımlanır: "<Ay> <Yıl> Satış
Adedi", "<Ay> <Yıl> Ziyaretçi Sayısı", "<Ay> <Yıl> Mağaza Sayısı". Tek liste
sayfası TÜM tarihçeyi (Ekim 2023'ten bugüne) taşır — pgsus/thy gibi tek bir
indirilebilir tablo yerine burada 100+ küçük PDF'ye dağılmış aynı seri var;
`onbellek` üç kategoriyi ("satis"/"ziyaret"/"magaza") ayrı ayrı önbellekler ki
6 seri aynı ~35 PDF'yi paylaşsın (aksi halde her seri kendi 35 PDF'ini
indirirdi).

Ölçüldü (2026-09-18): Ağustos 2026 Satış Adedi/Mağaza Ziyaretçi/Web
Ziyaret/Toplam Mağaza/Mega Mağaza/Standart Mağaza sırasıyla 10.737.113 /
4.992.875 / 10.978.359 / 316 / 2 / 282 — kurumsal.ebebek.com'daki KAP
bildirimleriyle birebir eşleşiyor.

Mağaza Sayısı bildirimi iki şablon taşır: Ağustos 2026'dan ÖNCE "X tanesi
geleneksel/standart, Y tanesi mini olmak üzere Z'ye ulaşmıştır" (mega kırılımı
yok); Ağustos 2026'DAN İTİBAREN "Türkiye (Z Mağaza): G mega, X standart, Y
mini" (KAP'ın kendi sınıflandırma değişikliği — bkz. şirketin ebebek.html
sayfasındaki not: mega mağazalar öncesinde standart sayısının içindeydi,
gerçek bir mağaza değişikliği değil). `standart_magaza` iki şablonda da aynı
alanı okur (etiket adı değişse de kavram sürekli); `mega_magaza` yalnızca yeni
şablonda var olduğu için katalogda `start_date: "2026-08-01"` taşımalı, aksi
halde önceki aylarda RuntimeError alınır.

Bilinen kaynak hatası: "Nisan 2025 Ziyaretçi Sayıları" başlıklı duyurunun PDF
içeriği aslında "Nisan 2025 Mağaza Sayısı" metnidir (ebebek IR sitesindeki
yanlış dosya eşlemesi; 2026-09-18'de canlı doğrulandı). Bu TEK ay
`BOZUK_DUYURULAR`da açıkça listelenir ve atlanır — sessiz atlama DEĞİL:
beklenen rakamın bulunamadığı başka bir ay hâlâ RuntimeError verir. Aksi
halde kaynak tarafındaki tek dosya hatası 34 ayın tamamını kullanılamaz
kılıyordu. Kaynak düzeltilince liste boşaltılmalı.

Bazı aylar aynı (ay, yıl, kategori) için İKİ duyuru içerir (ör. Aralık 2024
Mağaza Sayısı, Eylül 2024 Ziyaretçi Sayıları) — ikisi de aynı değeri taşıyorsa
tekilleştirilir; değerler çelişirse RuntimeError.

Ekim 2026'dan itibaren üç ayrı bildirim yerine TEK bir "<Ay> <Yıl> Operasyonel
Veriler" bildirimi yayımlanıyor (ölçüldü 2026-11-27: KAP 06.11.2026, mağaza
322 / mağaza ziyaretçi 5.440.511 / web 11.136.416 / satış 11.620.026). Eski
başlık kalıpları bunu tanımadığı için Ekim 2026 ayı üç kategoride de SESSİZCE
düşüyordu; artık birleşik belge üç ayrıştırıcıya da beslenir.

Sessiz atlamaya karşı iki koruma (teslim notu bakım işi, 2026-11-27):
- Ay-yıl ile başlayıp operasyonel anahtar kelime (Satış/Ziyaret/Mağaza/
  Operasyonel) taşıyan ama hiçbir bilinen kalıba uymayan başlık hata verir —
  yeni bir başlık biçimi en yeni ayı sessizce yutamaz.
- Her kategoride ilk ve son ay arasındaki her ay bulunmalıdır; yalnızca
  `BILINEN_AYLIK_BOSLUKLAR`daki aylar eksik olabilir. En yeni ayın henüz
  yayımlanmamış olması doğal olarak hata DEĞİLDİR (son ay neyse aralık orada
  biter).
"""

from __future__ import annotations

import io
import re

import pandas as pd
import pdfplumber
import requests

from ingest.http import durum_kodu_yukselt

from core.catalog import GECERLI_EBEBEK_METRIKLERI

LISTE_SAYFASI = "https://kurumsal.ebebek.com/yatirimci-duyurulari"
ZAMAN_ASIMI = 30

AY_ADLARI = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
AY_INDEKS = {ad: i + 1 for i, ad in enumerate(AY_ADLARI)}

# Kaynakta içeriği başlığıyla uyuşmayan duyurular (duyuru başlığı, kategori).
# Liste AÇIK tutulur: buraya yazılmayan bir uyuşmazlık hâlâ hata verir.
# "Nisan 2025 Ziyaretçi Sayıları" PDF'i gerçekte mağaza sayısı metni taşıyor
# (2026-09-18'de canlı doğrulandı; referans platform da o ayı boş gösteriyor).
BOZUK_DUYURULAR = {("Nisan 2025 Ziyaretçi Sayıları", "ziyaret")}
# Ardışıklık denetiminde eksik olmasına izin verilen aylar (kategori -> {tarih}).
# Yalnızca `BOZUK_DUYURULAR`ın doğurduğu kalıcı boşluk: Nisan 2025 için
# kaynakta okunabilir bir ziyaretçi belgesi YOK (2026-11-27'de liste yeniden
# tarandı; tek "Nisan 2025 Ziyaretçi Sayıları" duyurusu hâlâ mağaza metni).
BILINEN_AYLIK_BOSLUKLAR = {"ziyaret": {"2025-04-01"}}
_AY_DESENI = "|".join(AY_ADLARI)

# Başlık kalıpları. "ebebek " öneki bazı eski duyurularda var (ör. "ebebek
# Ağustos 2024 Satış Adetleri"); "Adedi"/"Adetleri" ve "Sayısı"/"Sayıları"
# zaman içinde değişmiş, ikisi de kabul edilir.
_SATIS_BASLIK = re.compile(rf"^(?:ebebek )?({_AY_DESENI}) (\d{{4}}) Satış Ade(?:di|tleri)$")
_ZIYARET_BASLIK = re.compile(rf"^(?:ebebek )?({_AY_DESENI}) (\d{{4}}) Ziyaretçi Sayı(?:sı|ları)$")
_MAGAZA_BASLIK = re.compile(rf"^(?:ebebek )?({_AY_DESENI}) (\d{{4}}) Mağaza Sayısı$")
# Ekim 2026'dan itibaren üç kategori tek bildirimde (bkz. modül docstring'i).
_OPERASYONEL_BASLIK = re.compile(rf"^(?:ebebek )?({_AY_DESENI}) (\d{{4}}) Operasyonel Veriler?$")
# Ay-yıl ile başlayan ve operasyonel veri gibi görünen her başlık: yukarıdaki
# kalıplardan hiçbirine uymuyorsa biçim değişmiştir -> hata (sessiz atlama yok).
_DONEMSEL_BASLIK = re.compile(
    rf"^(?:ebebek )?(?:{_AY_DESENI}) \d{{4}} .*(?:Satış|Ziyaret|Mağaza|Operasyonel)"
)

# Değer kalıpları (PDF metni normalize edilip — tüm boşluk/satır sonu tek
# boşluğa indirgenip — aranır). Her belgede ay değeri her zaman kümülatif
# değerden ÖNCE geçtiği için `re.search` ilk (ay) eşleşmesini döner.
_SATIS_DEGER = re.compile(r"toplam ürün ade(?:di|ti) ([\d.]+) olarak")
_MAGAZA_ZIYARETCI_DEGER = re.compile(r"mağazalarını ziyaret eden ziyaretçi sayısı ([\d.]+) olarak")
_WEB_ZIYARET_DEGER = re.compile(r"ebebek\.com internet sitesi ziyaret(?:çi)? sayısı ([\d.]+) olarak")
# Ağustos 2026 öncesi şablon: "... tarihi itibarıyla N tanesi
# geleneksel/standart, M tanesi mini olmak üzere T'ye ulaşmıştır / olarak
# devam etmektedir." Mağaza sayısı DEĞİŞMEDİYSE "ulaşmıştır" yerine "olarak
# devam etmektedir" kullanılır.
_MAGAZA_ESKI = re.compile(
    r"mağaza sayısı.*?itibarıyla (\d+) tanesi (geleneksel|standart), "
    r"(\d+) tanesi mini olmak üzere (\d+)['’]?\w*\s*(?:ulaşmıştır|olarak devam etmektedir)"
)
# Ağustos 2026'dan itibaren şablon: "Türkiye (T Mağaza): G mega, N standart, M mini".
_MAGAZA_YENI = re.compile(r"Türkiye \((\d+) Mağaza\): (\d+) mega, (\d+) standart, (\d+) mini")


def _normalize(metin: str) -> str:
    return re.sub(r"\s+", " ", metin.replace("&#039;", "'").replace("&rsquo;", "'"))


def _sayi(metin: str) -> int:
    return int(metin.replace(".", ""))


def duyuru_listesi(session=None) -> list[tuple[str, str]]:
    """(başlık, pdf_url) çiftlerini döner — "Özel Durum Açıklamaları" grubu.

    Tek sayfa TÜM tarihçeyi taşır (sayfalama yok); bu yüzden tek istekte
    duyuru listesi + URL'leri çözülür.
    """
    http = session or requests
    yanit = http.get(LISTE_SAYFASI, headers={"User-Agent": "Mozilla/5.0"}, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    kayitlar = re.findall(
        r'data-gtm-doc="([^"]+)"[^>]*data-gtm-doc-group="Özel Durum Açıklamaları".*?'
        r'href="(https://kurumsal\.ebebek\.com/download\?path=[^"]+)"',
        yanit.text, re.S,
    )
    if not kayitlar:
        raise RuntimeError("ebebek yatirimci-duyurulari sayfasında 'Özel Durum Açıklamaları' bulunamadı")
    return [(_normalize(baslik), url) for baslik, url in kayitlar]


def _pdf_metni(url: str, session=None) -> str:
    http = session or requests
    yanit = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    with pdfplumber.open(io.BytesIO(yanit.content)) as pdf:
        metin = "\n".join((sayfa.extract_text() or "") for sayfa in pdf.pages)
    return _normalize(metin)


def _tarih(ay_adi: str, yil: str) -> str:
    return f"{yil}-{AY_INDEKS[ay_adi]:02d}-01"


def _baslik_kategorileri(baslik: str) -> tuple[set[str], re.Match | None]:
    """Başlığın taşıdığı kategoriler ({"satis","ziyaret","magaza"}) ve
    dönemi veren eşleşme. Operasyonel veri gibi görünüp hiçbir kalıba
    uymayan başlıkta RuntimeError — yeni bir başlık biçimi sessizce
    atlanmamalı (Ekim 2026 "Operasyonel Veriler" tam olarak böyle düştü)."""
    for desen, kategoriler in (
        (_SATIS_BASLIK, {"satis"}),
        (_ZIYARET_BASLIK, {"ziyaret"}),
        (_MAGAZA_BASLIK, {"magaza"}),
        (_OPERASYONEL_BASLIK, {"satis", "ziyaret", "magaza"}),
    ):
        eslesme = desen.match(baslik)
        if eslesme:
            return kategoriler, eslesme
    if _DONEMSEL_BASLIK.match(baslik):
        raise RuntimeError(
            f"ebebek: tanınmayan operasyonel veri duyurusu başlığı '{baslik}' — "
            "kaynak başlık biçimini değiştirmiş olabilir, o ay sessizce atlanmamalı"
        )
    return set(), None


def _ardisiklik_dogrula(sonuc: dict, kategori: str, aciklama: str) -> None:
    """İlk ve son ay arasındaki her ay `sonuc`ta olmalı; yalnızca
    `BILINEN_AYLIK_BOSLUKLAR` eksik olabilir. Son ayın ötesine bakılmaz:
    henüz yayımlanmamış ay hata değildir."""
    if not sonuc:
        return
    beklenen = pd.date_range(min(sonuc), max(sonuc), freq="MS").strftime("%Y-%m-%d")
    eksik = [t for t in beklenen if t not in sonuc and t not in BILINEN_AYLIK_BOSLUKLAR.get(kategori, set())]
    if eksik:
        raise RuntimeError(
            f"ebebek: '{aciklama}' serisinde okunamayan/eksik ay(lar): {', '.join(eksik)} "
            f"({LISTE_SAYFASI}) — duyuru listede yok ya da başlığı tanınmadı"
        )


def _tekillestir(sonuc: dict, tarih: str, deger, baslik: str, url: str, aciklama: str) -> None:
    if tarih in sonuc and sonuc[tarih] != deger:
        raise RuntimeError(
            f"ebebek: {tarih} için çelişen yinelenen '{aciklama}' duyurusu ({baslik}: {url})"
        )
    sonuc[tarih] = deger


def satis_noktalari(session=None) -> dict[str, int]:
    sonuc: dict[str, int] = {}
    for baslik, url in duyuru_listesi(session):
        kategoriler, eslesme = _baslik_kategorileri(baslik)
        if "satis" not in kategoriler:
            continue
        tarih = _tarih(*eslesme.groups())
        metin = _pdf_metni(url, session)
        deger_eslesme = _SATIS_DEGER.search(metin)
        if not deger_eslesme:
            raise RuntimeError(f"ebebek: 'Satış Adedi' rakamı ayıklanamadı ({baslik}: {url})")
        _tekillestir(sonuc, tarih, _sayi(deger_eslesme.group(1)), baslik, url, "Satış Adedi")
    if not sonuc:
        raise RuntimeError("ebebek: hiç 'Satış Adedi' duyurusu bulunamadı")
    _ardisiklik_dogrula(sonuc, "satis", "Satış Adedi")
    return sonuc


def _icerik_donemi(metin: str, baslik: str, url: str, kategori: str) -> str:
    """Dönemi PDF METNİNDEN okur; başlık güvenilmez.

    Ölçüm (2026-09-18): iki duyuru da "Eylül 2024 Ziyaretçi Sayıları"
    başlığını taşıyor ama birinin içeriği Eylül 2025'e ait (referans
    platform da Eylül 2024'ü boş, Eylül 2025'i 4.597.348 gösteriyor).
    Başlığa güvenmek iki farklı ayı aynı anahtara yazıp "çelişen yinelenen
    duyuru" hatası üretiyordu. İki kalıp ölçüldü: gövdede "<Ay> <Yıl>
    ayında/ayı" ve (yeni şablonda) başlık satırında "<Ay> <Yıl>
    <kategori>". Serbest ilk tarih eşleşmesi KULLANILMAZ: PDF'ler
    yayım tarihini ("01 Temmuz 2025") ve geçen yıl karşılaştırmasını da
    yazıyor, ilk eşleşme yanlış ayı verir.
    """
    for desen in (
        rf"({_AY_DESENI})\s+(\d{{4}})\s+ay[ıi]",
        rf"({_AY_DESENI})\s+(\d{{4}})\s+{kategori.split()[0]}",
    ):
        eslesme = re.search(desen, metin)
        if eslesme is not None:
            return _tarih(*eslesme.groups())
    raise RuntimeError(
        f"ebebek: '{kategori}' PDF içeriğinde dönem bulunamadı ({baslik}: {url})"
    )


def ziyaret_noktalari(session=None) -> dict[str, tuple[int, int]]:
    """(mağaza ziyaretçi, web ziyaret) çiftleri."""
    sonuc: dict[str, tuple[int, int]] = {}
    for baslik, url in duyuru_listesi(session):
        kategoriler, _eslesme = _baslik_kategorileri(baslik)
        if "ziyaret" not in kategoriler:
            continue
        metin = _pdf_metni(url, session)
        magaza_eslesme = _MAGAZA_ZIYARETCI_DEGER.search(metin)
        web_eslesme = _WEB_ZIYARET_DEGER.search(metin)
        if not magaza_eslesme or not web_eslesme:
            if (baslik, "ziyaret") in BOZUK_DUYURULAR:
                continue  # kaynak tarafı dosya eşleme hatası; docstring'de belgeli
            raise RuntimeError(
                f"ebebek: 'Ziyaretçi Sayısı' rakamları ayıklanamadı ({baslik}: {url}) "
                "— PDF içeriği başlıkla uyuşmuyor olabilir"
            )
        # Birleşik belgede dönem başlık satırında "<Ay> <Yıl> Operasyonel".
        kategori_adi = "Ziyaretçi Sayısı" if kategoriler == {"ziyaret"} else "Operasyonel Veriler"
        tarih = _icerik_donemi(metin, baslik, url, kategori_adi)
        deger = (_sayi(magaza_eslesme.group(1)), _sayi(web_eslesme.group(1)))
        _tekillestir(sonuc, tarih, deger, baslik, url, "Ziyaretçi Sayısı")
    if not sonuc:
        raise RuntimeError("ebebek: hiç 'Ziyaretçi Sayısı' duyurusu bulunamadı")
    _ardisiklik_dogrula(sonuc, "ziyaret", "Ziyaretçi Sayısı")
    return sonuc


def magaza_noktalari(session=None) -> dict[str, dict[str, int]]:
    """{"toplam", "standart", "mini", opsiyonel "mega"} alanları."""
    sonuc: dict[str, dict[str, int]] = {}
    for baslik, url in duyuru_listesi(session):
        kategoriler, eslesme = _baslik_kategorileri(baslik)
        if "magaza" not in kategoriler:
            continue
        tarih = _tarih(*eslesme.groups())
        metin = _pdf_metni(url, session)
        eski = _MAGAZA_ESKI.search(metin)
        yeni = _MAGAZA_YENI.search(metin)
        if yeni:
            toplam, mega, standart, mini = (int(x) for x in yeni.groups())
            deger = {"toplam": toplam, "standart": standart, "mini": mini, "mega": mega}
        elif eski:
            standart, _etiket, mini, toplam = eski.groups()
            deger = {"toplam": int(toplam), "standart": int(standart), "mini": int(mini)}
        else:
            raise RuntimeError(f"ebebek: 'Mağaza Sayısı' rakamları ayıklanamadı ({baslik}: {url})")
        _tekillestir(sonuc, tarih, deger, baslik, url, "Mağaza Sayısı")
    if not sonuc:
        raise RuntimeError("ebebek: hiç 'Mağaza Sayısı' duyurusu bulunamadı")
    _ardisiklik_dogrula(sonuc, "magaza", "Mağaza Sayısı")
    return sonuc


# --- Çeyreklik "Analist Toplantısı Sunumu" (Yatırımcı İlişkileri) ---
#
# `finansal-bilgiler` sayfasının "Finansal Sonuçlara İlişkin Sunumlar"
# bölümü 2023 3Ç'ten bugüne çeyreklik PDF listeler (aylık KAP
# duyurularından AYRI belge ailesi, aylık duyuru sayfasından da AYRI bir
# URL). "NÇ Türkiye Operasyonlarına Genel Bakış" sayfası kanal bazlı
# satış büyümesi/payı okur; bir sonraki sayfa fatura/sipariş ortalaması,
# PL payı ve LFL'yi; "Kategoriler arası..." sayfası kategori kırılımını
# okur. Üçü de yalnızca YAKIN GEÇMİŞTE ortaya çıktı (ölçüldü 2026-09-29:
# fatura/LFL/PL sayfası ilk kez 4Ç 2025'te, kanal ve kategori sayfaları ilk
# kez 4Ç 2024'te; 2024 1Ç–3Ç'de sayfa hiç yok) — daha eski sunumlarda
# `None`/atlama ile ele alınır (hata değil). Kanal sayfası 4Ç 2024'te
# yalnızca 12A kümülatif büyüme taşıdığı (çeyrek/YBİ çifti yok) için o
# sunum bilinçli atlanır: çeyrek serisine kümülatif değer yazılmaz.
FINANSAL_SAYFA = "https://kurumsal.ebebek.com/finansal-bilgiler"

_SUNUM_SATIRI = re.compile(
    r'data-gtm-doc="Analist Toplantısı Sunumu[^"]*"\s*'
    r'data-gtm-doc-group="Finansal Sonuçlara İlişkin Sunumlar">'
    r'.*?<strong>(\d{2})\.(\d{2})\.(\d{2})</strong>'
    r'.*?href="(https://kurumsal\.ebebek\.com/download\?path=[^"]+)"',
    re.S,
)
_AY_CEYREK = {"03": 1, "06": 2, "09": 3, "12": 4}

# Her sayfa türünün sunumlarda İLK göründüğü çeyrek (ölçüldü 2026-09-29,
# 2026-11-27'de 13 sunumun tamamı yeniden tarandı). Bu çeyrekten ÖNCE sayfanın
# olmaması doğaldır (None); bu çeyrekten itibaren sayfa bulunamazsa sayfa
# tanıma bozulmuştur -> hata. (2026-11-27: 1Ç 2025 kanal sayfası başlığı
# "Satış Kanalı Bazında Satış" büyük S ile yazıldığı için tanınmıyor ve o
# çeyrek altı kanal serisinden sessizce düşüyordu.)
SAYFA_ILK_CEYREK = {"kanal": (2024, 4), "fatura": (2025, 4), "kategori": (2024, 4)}

# Sayfası VAR ama çeyreğe özgü değer taşımadığı için bilerek atlanan
# (yıl, çeyrek, sayfa türü) üçlüleri. Liste AÇIK tutulur: burada olmayan her
# ayrıştırma hatası yükselir. 4Ç 2024 kanal sayfası altı büyüme etiketinin
# altısını da "2023/2024" (yalnızca 12A kümülatif) yazıyor (ölçüldü
# 2026-09-29, 2026-11-27'de yeniden doğrulandı) — çeyrek serisine kümülatif
# değer yazılmaz.
BILINEN_SUNUM_ATLAMALARI = {(2024, 4, "kanal")}

# Fatura sayfası VAR ama LFL panelleri yalnızca kümülatif ("<N>A'<yy>")
# etiket taşıdığı için çeyreklik LFL değeri YAYIMLANMAMIŞ (yıl, çeyrek)
# çiftleri. 3Ç 2026 sunumunun LFL Satış ve LFL Giriş panellerinde yalnızca
# "9A'25 9A'26" var, "3Ç'25/3Ç'26" yok (ölçüldü 2026-11-27). Liste AÇIK
# tutulur: burada olmayan bir çeyrekte LFL çeyrek etiketi bulunamazsa bu,
# etiket deseninin kaydığı (başka kesme işareti, "3Ç-26" vb.) bir şablon
# değişikliği sayılır ve yükselir — LFL serisinde sessiz delik açılmaz.
BILINEN_LFL_YALNIZ_KUMULATIF = {(2026, 3)}

# `fatura_siparis_pl_lfl_ayikla`nın "LFL panelleri yalnızca kümülatif"
# işareti; metrik değildir, `_sunum_metriklerini_getir` tüketip siler.
LFL_YALNIZ_KUMULATIF_ISARETI = "_lfl_yalniz_kumulatif"

GECERLI_SUNUM_METRIKLERI = {
    "kanal_buyume_magaza", "kanal_buyume_web", "kanal_buyume_pazaryeri",
    "kanal_payi_magaza", "kanal_payi_web", "kanal_payi_pazaryeri",
    "magaza_fatura_ortalama", "web_siparis_ortalama",
    "lfl_satis_adedi", "lfl_giris_sayisi",
    "pl_payi_toplam", "pl_payi_magaza", "pl_payi_web", "pl_payi_pazaryeri",
    "kategori_buyume_hizli_tuketim", "kategori_buyume_tamamlayici",
    "kategori_buyume_tekstil", "kategori_buyume_bebek_arac_gerec",
}


def _sunum_listesi(session=None) -> list[dict]:
    """finansal-bilgiler sayfasının "Finansal Sonuçlara İlişkin Sunumlar"
    bölümünden (yıl, çeyrek, url) satırlarını okur. Tarih başlığın kendi
    metninden ("2025 2. Çeyrek" vb. — yıllar arası ifade farklı) değil,
    belgeye eklenmiş sabit "GG.AA.YY" damgasından (her zaman dönem SONU)
    okunur — çok daha güvenilir."""
    http = session or requests
    yanit = http.get(FINANSAL_SAYFA, headers={"User-Agent": "Mozilla/5.0"}, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    sonuc = []
    for _gun, ay, yy, url in _SUNUM_SATIRI.findall(yanit.text):
        if ay not in _AY_CEYREK:
            raise RuntimeError(
                f"ebebek Analist Toplantısı Sunumu: çeyrek sonu olmayan tarih damgası (ay {ay}): {url}"
            )
        sonuc.append({"yil": 2000 + int(yy), "ceyrek": _AY_CEYREK[ay], "url": url})
    if not sonuc:
        raise RuntimeError(
            "ebebek finansal-bilgiler sayfasında hiç 'Analist Toplantısı Sunumu' bulunamadı"
        )
    # Satırı tanınmayan bir sunum çeyreği sessizce düşürmesin: ilk ve son
    # çeyrek arası kesintisiz olmalı (en yeni çeyreğin henüz yayımlanmamış
    # olması doğal olarak hata değil).
    ceyrekler = {(s["yil"], s["ceyrek"]) for s in sonuc}
    ilk, son = min(ceyrekler), max(ceyrekler)
    eksik = []
    yil, ceyrek = ilk
    while (yil, ceyrek) < son:
        if (yil, ceyrek) not in ceyrekler:
            eksik.append(f"{ceyrek}Ç {yil}")
        yil, ceyrek = (yil + 1, 1) if ceyrek == 4 else (yil, ceyrek + 1)
    if eksik:
        raise RuntimeError(
            f"ebebek finansal-bilgiler: şu çeyreklerin Analist Toplantısı Sunumu okunamadı: "
            f"{', '.join(eksik)} ({FINANSAL_SAYFA})"
        )
    return sonuc


def _sunum_pdfsini_getir(url: str, onbellek: dict, session=None) -> bytes:
    """Ham PDF baytlarını döner (metne değil — üç ayrıştırıcı da konum
    bilgisine ihtiyaç duyar). Sayfada LİSTELENEN bir sunumun 404 vermesi
    eskiden None döndürüp o çeyreği sessizce atlıyordu; artık aylık
    duyurulardaki `_pdf_metni` gibi HTTP hatası yükselir."""
    anahtar = ("sunum_bayt", url)
    if anahtar in onbellek:
        return onbellek[anahtar]
    http = session or requests
    yanit = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=ZAMAN_ASIMI)
    durum_kodu_yukselt(yanit)
    onbellek[anahtar] = yanit.content
    return yanit.content


def _sunum_sayisi(metin: str) -> float:
    """Sunum sayısı: Türkçe ("1.291", "53,2%") ya da İngilizce ("1,291",
    "53.6%") biçim — 3Ç 2026 sunumu İngilizce biçimde (ölçüldü 2026-11-27).
    Ayraçtan sonra tam 3 hane = binlik, 1–2 hane = ondalık; başka biçim hata."""
    govde = metin.rstrip("%")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", govde):
        return float(re.sub(r"[.,]", "", govde))
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", govde):
        return float(govde.replace(",", "."))
    raise RuntimeError(f"ebebek sunumu: sayı biçimi tanınmadı: {metin!r}")


_KANAL_BUYUME_DESENI = re.compile(r"(%-?\d+,\d+|-%\d+,\d+)")
# Başlık sunuma göre "Bazında satış" (2Ç 2025+) ya da "Bazında Satış" (1Ç 2025)
# yazılıyor — büyük/küçük harf duyarsız (ölçüldü 2026-11-27).
_KANAL_PANEL_DESENI = re.compile(r"Satış Kanalı Bazında [Ss]atış")


def kanal_buyume_ve_payini_ayikla(pdf_baytlari: bytes) -> dict[str, float] | None:
    """"NÇ Türkiye Operasyonlarına Genel Bakış" sunumunun "Satış Kanalı
    Bazında satış adedi kırılımı" bölümünü taşıyan sayfayı bulur. Sayfa
    yoksa (2024 4Ç'ten önce) None döner. 2024 4Ç sunumunda sayfa vardır
    ama altı büyüme değerinin altısı da "2023/2024" (yalnızca 12A kümülatif)
    etiketlidir — çeyreğe özgü değer olmadığı için RuntimeError verilir ve
    çağıran bu tek sunumu `BILINEN_SUNUM_ATLAMALARI` üzerinden açıkça atlar.

    Mağaza/ebebek.com/Pazaryeri satış adedi BÜYÜME YÜZDELERİ ve PASTA
    GRAFİĞİ PAYLARI gerçek metin katmanında var (regex/konumla okunabilir)
    ama üç panelin MUTLAK bin-adet çubuk değerleri PDF'te vektör/görsel
    olarak gömülü — metin katmanında HİÇ yok (ölçüldü: `extract_text()`
    çıktısında "23.288" gibi hiçbir çubuk etiketi geçmiyor, yalnızca
    başlıklar/yüzdeler geçiyor). Bu yüzden mutlak bileşen serisi yerine
    doğrudan yüzde serileri üretilir (büyüme + pay).

    Büyüme: metin sırası panel sırasıyla (Mağaza, ebebek.com, Pazaryeri)
    eşleşir — üç panelin başlığı da bu sırada, garipleşmiyor (yalnızca
    "Mağaza Fatura Başına..." sayfasındaki İKİ SATIRLI başlıklar
    garipleşiyor, bkz. `_fatura_siparis_pl_lfl_ayikla`). Tek çeyreklik
    sunumlarda (1Ç) panel başına TEK büyüme yüzdesi, çeyrek+YBİ
    kümülatif sunan sunumlarda (2Ç/3Ç/4Ç) panel başına İKİ (çeyrek, YBİ
    kümülatif) — yalnızca ÇEYREĞE özgü ilk değer kullanılır.

    Pay: pasta grafiğinin üç dilim yüzdesi konumdan okunur ama hangi
    sayının hangi kanala ait olduğu metin sırasından ÇIKARILAMAZ (üç
    sayı da pasta çevresinde serbestçe konumlanmış). Mağaza/ebebek.com/
    Pazaryeri payları HER ölçülen çeyrekte hep BÜYÜKTEN KÜÇÜĞE bu sırada
    olduğundan (Mağaza her zaman baskın, Pazaryeri her zaman en küçük —
    beş farklı çeyrekte doğrulandı) büyüklüğe göre eşlenir. Etiket yazımı
    sunuma göre değişir: 2026 1Ç'te üçü de çıplak sayı + ayrı "%", diğer
    sunumlarda en az biri tek parça ("%4", "%88") — ikisi de kabul edilir,
    aksi halde paylar 3 değil 2 bulunur ve sunum sessizce düşerdi (ölçüldü
    2026-09-29: 2Ç25/3Ç25/4Ç25/2Ç26 sunumlarının hepsi bu yüzden atlanıyordu,
    kalan tek veri 1Ç 2026'ydı)."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        sayfa = None
        for p in pdf.pages:
            t = p.extract_text() or ""
            if _KANAL_PANEL_DESENI.search(t) and "Mağaza Satış Adetleri" in t:
                sayfa = p
                break
        if sayfa is None:
            return None
        tam_metin = sayfa.extract_text() or ""
        kelimeler = sayfa.extract_words()

    idx_panel = _KANAL_PANEL_DESENI.search(tam_metin).start()
    legend_eslesme = re.search(r"Mağaza\s+ebebek\.com\s+Pazar\s*[Yy]eri", tam_metin)
    if legend_eslesme is None:
        raise RuntimeError("ebebek kanal sayfası: beklenen bölüm sınırları bulunamadı")
    idx_legend = legend_eslesme.start()
    buyume_ham = _KANAL_BUYUME_DESENI.findall(tam_metin[idx_panel:idx_legend])
    buyume = [float(g.replace("%", "").replace(",", ".")) for g in buyume_ham]
    if len(buyume) == 3:
        magaza_b, web_b, pazar_b = buyume
    elif len(buyume) == 6:
        magaza_b, web_b, pazar_b = buyume[0], buyume[2], buyume[4]
        # Altı değer = (çeyrek, YBİ kümülatif) İKİ çift. 4Ç 2024 sunumunda altı
        # etiketin de tamamı "2023/2024" (yalnızca 12A kümülatif) olduğundan
        # ÇEYREĞE ÖZGÜ değer yoktur — çeyrek serisine kümülatif değer yazmamak
        # için o sunum atlanır (ölçüldü 2026-09-29).
        etiketler = re.findall(
            r"\d[ÇA]['’]\d{2}/\d{2}|\d{4}/\d{4}", tam_metin[idx_panel:idx_legend]
        )
        if len(set(etiketler)) < 2:
            raise RuntimeError(
                "ebebek kanal büyümesi: sunum çeyrek/YBİ çifti taşımıyor, yalnızca kümülatif"
            )
    else:
        raise RuntimeError(f"ebebek kanal büyümesi: 3 ya da 6 değer bekleniyordu, {len(buyume)} bulundu")

    tek_ve_iki_hane = re.compile(r"^\d{1,2}$")
    # Pasta etiketleri % işaretiyle BİRLİKTE ("%4", "%88") ya da ayrı bir metin
    # parçası olarak ("9", "%") yazılır; ölçüldü (2026-09-29) — 2026 1Ç'te
    # üçü de çıplak sayı, diğer beş sunumda en az biri "%N" biçiminde. Önceki
    # kalıp yalnızca "N%" kabul ettiği için "%4"/"%88" etiketi düşüyor ve
    # paylar 3 yerine 2 değer bulunup SUNUM ATLANIYORDU (6 kanal serisi tek
    # satıra düşmüştü).
    yuzde_ekli = re.compile(r"^(?:%\d{1,2}%?|\d{1,2}%)$")
    yuzde_kelimesi = [w for w in kelimeler if w["text"] == "%"]
    pay_degerleri = []
    for w in kelimeler:
        if tek_ve_iki_hane.match(w["text"]) and any(
            abs(p["top"] - w["top"]) < 40 and abs(p["x0"] - w["x0"]) < 60 for p in yuzde_kelimesi
        ):
            pay_degerleri.append(float(w["text"]))
        elif yuzde_ekli.match(w["text"]):
            pay_degerleri.append(float(w["text"].strip("%")))
    if len(pay_degerleri) != 3:
        raise RuntimeError(f"ebebek kanal payı: 3 değer bekleniyordu, {len(pay_degerleri)} bulundu")
    magaza_p, web_p, pazar_p = sorted(pay_degerleri, reverse=True)

    return {
        "kanal_buyume_magaza": magaza_b, "kanal_buyume_web": web_b, "kanal_buyume_pazaryeri": pazar_b,
        "kanal_payi_magaza": magaza_p, "kanal_payi_web": web_p, "kanal_payi_pazaryeri": pazar_p,
    }


def fatura_siparis_pl_lfl_ayikla(pdf_baytlari: bytes) -> dict[str, float] | None:
    """"Mağaza Fatura Başına Nominal Tutar" + "ebebek.com Sipariş Başına
    Nominal Tutar" + "Satış Kanalı Bazında PL (Öz Marka) Adet Payı" +
    "Aynı Mağaza (LFL) Satış/Giriş" hepsini TEK sayfada taşıyan sayfayı
    bulur. Sayfa yoksa (2025 4Ç'ten önce) None döner.

    Bu sayfanın başlıkları (ör. "Mağaza Fatura Başına Nominal Tutar")
    pdfplumber'da SÜTUN BAZLI satır-satır çıkarıldığından komşu sütunların
    metniyle karakter düzeyinde iç içe geçiyor (ölçüldü: "Dönem sonu
    itibarıyla" ile karışıp "Dön M em a ğ so a nu z a iti b F..." gibi
    okunuyor) — bu yüzden hiçbir etiket metinden ARANMAZ, sayfa yalnızca
    LFL alt başlığından (garipleşmiyor) tanınır ve sayı DEĞERLERİ salt
    KONUMDAN (x0/top) okunur:
    - Her çubuk değeri, altındaki x ekseni etiketine ("2Ç'25", "6A'26",
      "12A'25") x0 yakınlığıyla eşlenir. Etiketler `top`a göre iki SATIRA
      kümelenir (üstte Fatura+Sipariş, altta LFL Satış+Giriş); her satır
      x0'a göre TAM ORTADAN ikiye bölünür (soldaki/sağdaki panel).
    - Panelde ÇEYREK etiketli ("<N>Ç'<yy>") en yeni yılın değeri kullanılır.
      Önceki sürüm değerleri salt sıra/aralıkla okuyordu; 3Ç 2026 sunumunda
      (ölçüldü 2026-11-27) sayılar İngilizce biçimde ("1,291", "53.6%") ve
      LFL paneli yalnızca "9A'25 9A'26" taşıdığı için PL payı 536, fatura
      1,291, LFL 30 gibi SAÇMA değerler yazılıyordu.
    - LFL panellerinde hiç çeyrek etiketi yoksa (yalnızca YBİ kümülatif; 3Ç
      2026) LFL anahtarları yazılmaz (kümülatif değer çeyrek serisine
      yazılmaz) ve sonuca `LFL_YALNIZ_KUMULATIF_ISARETI` konur. Ayıklayıcı
      çeyreği bilmediği için bunun belgeli bir durum mu (yalnızca
      `BILINEN_LFL_YALNIZ_KUMULATIF`) yoksa şablon kayması mı olduğuna
      `_sunum_metriklerini_getir` karar verir. Fatura/sipariş panelinde
      çeyrek etiketi yoksa doğrudan hata.
    PL payı dört değeri (Toplam/Mağaza/ebebek.com/Pazaryeri) "%" sonekiyle
    ayrı toplanır, soldan sağa sırayla."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        sayfa = None
        for p in pdf.pages:
            t = p.extract_text() or ""
            if "Aynı Mağaza (LFL)" in t and "Adet Payı" in t:
                sayfa = p
                break
        if sayfa is None:
            return None
        kelimeler = sayfa.extract_words()

    sayi_deseni = re.compile(r"^\d[\d.,]*%?$")
    yil_deseni = re.compile(r"^20\d{2}$")
    etiket_deseni = re.compile(r"^(\d{1,2})([ÇA])['’](\d{2})$")

    tum_sayilar = [w for w in kelimeler if sayi_deseni.match(w["text"]) and not yil_deseni.match(w["text"])]
    yuzdeli = sorted((w for w in tum_sayilar if w["text"].endswith("%")), key=lambda w: w["x0"])
    if len(yuzdeli) != 4:
        raise RuntimeError(f"ebebek PL adet payı: 4 değer bekleniyordu, {len(yuzdeli)} bulundu")
    pl_toplam, pl_magaza, pl_web, pl_pazar = (_sunum_sayisi(w["text"]) for w in yuzdeli)
    duz = [w for w in tum_sayilar if not w["text"].endswith("%")]

    # Etiket satırları: `top`u 15 pikselden yakın etiketler aynı satır. Tek
    # etiketli "satır" (PL panelinin "6A'26" başlığı) eksen değildir.
    etiketler = sorted((w for w in kelimeler if etiket_deseni.match(w["text"])), key=lambda w: w["top"])
    satirlar: list[list[dict]] = []
    for w in etiketler:
        if satirlar and w["top"] - satirlar[-1][-1]["top"] < 15:
            satirlar[-1].append(w)
        else:
            satirlar.append([w])
    satirlar = [satir for satir in satirlar if len(satir) >= 2]
    if len(satirlar) != 2:
        raise RuntimeError(
            f"ebebek fatura/sipariş/LFL: 2 x ekseni etiket satırı bekleniyordu, {len(satirlar)} bulundu"
        )

    def panel_ceyrek_degeri(panel: list[dict]) -> float | None:
        ceyrekler = []
        for etiket in panel:
            adaylar = [
                w for w in duz
                if 0 < etiket["top"] - w["top"] < 200 and abs(w["x0"] - etiket["x0"]) < 40
            ]
            if not adaylar:
                raise RuntimeError(f"ebebek fatura/sipariş/LFL: '{etiket['text']}' çubuğunun değeri bulunamadı")
            deger = min(adaylar, key=lambda w: abs(w["x0"] - etiket["x0"]))
            _no, tur, yy = etiket_deseni.match(etiket["text"]).groups()
            if tur == "Ç":
                ceyrekler.append((int(yy), _sunum_sayisi(deger["text"])))
        return max(ceyrekler)[1] if ceyrekler else None

    paneller = []
    for satir in satirlar:
        satir = sorted(satir, key=lambda w: w["x0"])
        if len(satir) % 2:
            raise RuntimeError(f"ebebek fatura/sipariş/LFL: tek sayıda eksen etiketi ({len(satir)})")
        orta = len(satir) // 2
        paneller += [panel_ceyrek_degeri(satir[:orta]), panel_ceyrek_degeri(satir[orta:])]
    fatura, siparis, lfl_satis, lfl_giris = paneller
    if fatura is None or siparis is None:
        raise RuntimeError("ebebek fatura/sipariş: panelde çeyrek etiketli çubuk yok")
    sonuc = {
        "magaza_fatura_ortalama": fatura, "web_siparis_ortalama": siparis,
        "pl_payi_toplam": pl_toplam, "pl_payi_magaza": pl_magaza,
        "pl_payi_web": pl_web, "pl_payi_pazaryeri": pl_pazar,
    }
    if (lfl_satis is None) != (lfl_giris is None):
        raise RuntimeError("ebebek LFL: iki panelden yalnızca biri çeyrek değeri taşıyor")
    if lfl_satis is not None:
        sonuc["lfl_satis_adedi"] = lfl_satis
        sonuc["lfl_giris_sayisi"] = lfl_giris
    else:
        sonuc[LFL_YALNIZ_KUMULATIF_ISARETI] = True
    return sonuc


_KATEGORI_SIRASI = (
    "kategori_buyume_hizli_tuketim", "kategori_buyume_tamamlayici",
    "kategori_buyume_tekstil", "kategori_buyume_bebek_arac_gerec",
)


def kategori_buyumesini_ayikla(pdf_baytlari: bytes) -> dict[str, float] | None:
    """"Kategoriler arası stratejik konumlandırma..." sayfasındaki dört
    kategorinin (Hızlı Tüketim/Tamamlayıcı/Tekstil/Bebek Araç-Gereç)
    adet büyüme yüzdesini okur. Sayfa yoksa (2024 4Ç'ten önce) None
    döner.

    Büyüme rozetleri ("+%NN adet büyümesi") metinde her zaman 2x2
    kutunun SATIR sırasıyla (Hızlı Tüketim, Tamamlayıcı, Tekstil, Bebek
    Araç-Gereç) geçiyor — dört rozet güvenle sıralı okunur. Kategori
    PAYLARI (pasta grafiği, bu fonksiyonda KULLANILMIYOR — yalnızca
    yüzde büyüme card'ı hedefleniyor) ise metin sırasında karışıyor
    (kutuların açıklama metinleriyle iç içe geçiyor, ölçüldü), konumdan
    (sayfa dörtte-bir çeyreği) okunması gerekir; büyüme rozetleri bu
    sorunu yaşamıyor çünkü rozet kutucuğu kendi başına bağımsız bir metin
    bloğu."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        tam_metin = None
        for p in pdf.pages:
            t = p.extract_text() or ""
            if "stratejik konumlandırmaya" in t and "Hızlı tüketim" in t:
                tam_metin = t
                break
        if tam_metin is None:
            return None
    # Rozet eksi de olabilir ("-%9", "-%3": 1Ç/2Ç 2025 Bebek Araç-Gereç,
    # ölçüldü 2026-11-27). Yalnızca "+" kabul eden eski kalıp 3 değer bulup
    # bu iki sunumu sessizce düşürüyordu.
    buyume = [
        float(m.group(2).replace(",", ".")) * (-1 if m.group(1) == "-" else 1)
        for m in re.finditer(r"([+-])\s*%\s*(\d+(?:,\d+)?)", tam_metin)
    ]
    if len(buyume) != 4:
        raise RuntimeError(f"ebebek kategori büyümesi: 4 değer bekleniyordu, {len(buyume)} bulundu")
    return dict(zip(_KATEGORI_SIRASI, buyume))


def _sunum_metriklerini_getir(onbellek: dict, session=None) -> dict[str, dict[str, float]]:
    """Tüm "Analist Toplantısı Sunumu" PDF'lerini TARA (üç ayrı sayfa
    türü, her biri kendi varlığını kontrol eder), on sekiz metriği
    birleştirip {metrik: {tarih: değer}} döner. Çakışan çeyreklerde
    SONRAKİ (daha yeni yayımlanan) sunum kazanır.

    Sessiz atlama YOK (2026-11-27): eskiden her `RuntimeError` yutulup o
    sunumun o sayfası atlanıyordu; canlı taramada bu, 1Ç/2Ç 2025 kategori
    büyümesini (eksi rozet okunamıyordu) gizliyordu. Artık:
    - sayfa yoksa (None) yalnızca `SAYFA_ILK_CEYREK`ten ÖNCEKİ sunumlarda
      kabul edilir, sonrasında hata;
    - ayrıştırma hatası yalnızca `BILINEN_SUNUM_ATLAMALARI`ndaki üçlüde
      atlanır, aksi halde dönem ve URL ile yükselir;
    - LFL'nin yalnızca kümülatif olması yalnızca
      `BILINEN_LFL_YALNIZ_KUMULATIF`teki çeyrekte kabul edilir."""
    if "sunum_metrikleri" in onbellek:
        return onbellek["sunum_metrikleri"]
    if "sunumlar" not in onbellek:
        onbellek["sunumlar"] = _sunum_listesi(session=session)
    birlesik: dict[str, dict[str, float]] = {m: {} for m in GECERLI_SUNUM_METRIKLERI}
    for s in sorted(onbellek["sunumlar"], key=lambda s: (s["yil"], s["ceyrek"])):
        baytlar = _sunum_pdfsini_getir(s["url"], onbellek, session=session)
        ay = {1: "01", 2: "04", 3: "07", 4: "10"}[s["ceyrek"]]
        tarih = f"{s['yil']}-{ay}-01"
        donem = (s["yil"], s["ceyrek"])
        for tur, ayiklayici in (
            ("kanal", kanal_buyume_ve_payini_ayikla),
            ("fatura", fatura_siparis_pl_lfl_ayikla),
            ("kategori", kategori_buyumesini_ayikla),
        ):
            try:
                sonuc = ayiklayici(baytlar)
            except RuntimeError as hata:
                if (*donem, tur) in BILINEN_SUNUM_ATLAMALARI:
                    continue  # belgeli: sayfa var ama çeyreğe özgü değer yok
                raise RuntimeError(
                    f"ebebek {s['ceyrek']}Ç {s['yil']} Analist Toplantısı Sunumu '{tur}' "
                    f"sayfası okunamadı ({s['url']}): {hata}"
                ) from hata
            if sonuc is None:
                if donem >= SAYFA_ILK_CEYREK[tur]:
                    raise RuntimeError(
                        f"ebebek {s['ceyrek']}Ç {s['yil']} Analist Toplantısı Sunumu'nda '{tur}' "
                        f"sayfası bulunamadı ({s['url']}) — {SAYFA_ILK_CEYREK[tur][1]}Ç "
                        f"{SAYFA_ILK_CEYREK[tur][0]}'ten beri her sunumda olmalı"
                    )
                continue  # sayfa bu sunumda henüz yoktu (belgeli)
            if sonuc.pop(LFL_YALNIZ_KUMULATIF_ISARETI, False) and donem not in BILINEN_LFL_YALNIZ_KUMULATIF:
                raise RuntimeError(
                    f"ebebek {s['ceyrek']}Ç {s['yil']} Analist Toplantısı Sunumu 'fatura' sayfasında "
                    f"LFL panelleri çeyrek etiketi taşımıyor ({s['url']}) — "
                    f"BILINEN_LFL_YALNIZ_KUMULATIF dışında; etiket deseni kaymış olabilir"
                )
            for metrik, deger in sonuc.items():
                birlesik[metrik][tarih] = deger
    onbellek["sunum_metrikleri"] = birlesik
    return birlesik


def seri_cek(seri, onbellek: dict | None = None, session=None):
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı).

    `onbellek` üç aylık kategoriyi ("satis"/"ziyaret"/"magaza") ayrı ayrı
    taşır: altı seri üç kategoriyi paylaşır, aksi halde her seri kendi
    ~35 PDF'ini indirirdi. Çeyreklik "Analist Toplantısı Sunumu" metrik
    ailesi (`GECERLI_SUNUM_METRIKLERI`) dördüncü, bağımsız bir önbellek
    anahtarı ("sunum_metrikleri") kullanır — on sekiz seri aynı ~12
    sunumu paylaşır.
    """
    onbellek = {} if onbellek is None else onbellek
    metrik = seri.ebebek_metrik

    if metrik == "satis_adedi":
        if "satis" not in onbellek:
            onbellek["satis"] = satis_noktalari(session)
        kendi = dict(onbellek["satis"])
    elif metrik in ("magaza_ziyaretci", "web_ziyaret"):
        if "ziyaret" not in onbellek:
            onbellek["ziyaret"] = ziyaret_noktalari(session)
        indeks = 0 if metrik == "magaza_ziyaretci" else 1
        kendi = {tarih: deger[indeks] for tarih, deger in onbellek["ziyaret"].items()}
    elif metrik in ("toplam_magaza", "standart_magaza", "mega_magaza"):
        if "magaza" not in onbellek:
            onbellek["magaza"] = magaza_noktalari(session)
        alan = {"toplam_magaza": "toplam", "standart_magaza": "standart", "mega_magaza": "mega"}[metrik]
        kendi = {}
        for tarih, deger in onbellek["magaza"].items():
            if alan in deger:
                kendi[tarih] = deger[alan]
            elif seri.start_date is None or tarih >= seri.start_date:
                # "mega" yalnızca Ağustos 2026 şablonunda var; start_date'ten
                # SONRA eski şablona dönülmüşse ay sessizce düşmemeli.
                raise RuntimeError(
                    f"ebebek: {tarih} Mağaza Sayısı bildiriminde '{alan}' kırılımı yok ({seri.id})"
                )
    elif metrik in GECERLI_SUNUM_METRIKLERI:
        harita = _sunum_metriklerini_getir(onbellek, session=session).get(metrik, {})
        if not harita:
            raise RuntimeError(f"ebebek {metrik!r} için hiçbir Analist Toplantısı Sunumu'nda değer bulunamadı")
        kendi = harita
    else:
        raise RuntimeError(f"bilinmeyen ebebek_metrik: {metrik!r} ({seri.id})")

    df = pd.DataFrame(sorted(kendi.items()), columns=["date", "value"])
    if seri.start_date:
        df = df[df["date"] >= seri.start_date]
    return df.reset_index(drop=True)
