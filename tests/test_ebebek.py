"""ebebek Mağazacılık aylık operasyonel veri istemcisi testleri.

`duyuru_listesi` HTML ayrıştırması gerçek `yatirimci-duyurulari` sayfa
parçacığıyla test edilir. PDF indirme + metin çıkarma adımı (`_pdf_metni`)
monkeypatch'lenip ayrıştırıcılara (satış/ziyaret/mağaza) 2026-09-18'de CANLI
ölçülmüş gerçek KAP bildirim metinleri (kısaltılmış) beslenir — ağa ya da
pdfplumber'a girmeden regex davranışını, önbellek paylaşımını ve bilinen
kaynak anomalisini (Nisan 2025 Ziyaretçi Sayısı — başlıkla uyuşmayan içerik)
pinler.
"""

from types import SimpleNamespace

import pytest

import requests

import ingest.ebebek as ebebek
from ingest.ebebek import magaza_noktalari, satis_noktalari, seri_cek, ziyaret_noktalari

# --- Gerçek belgelerden alınmış (2026-09-18 ölçümü), kısaltılmış metinler ---

_SATIS_AGUSTOS_2026 = (
    "KAP'ta yayınlanma tarihi ve saati: 07.09.2026 21:06:23 "
    "EBEBEK MAĞAZACILIK A.Ş. Özel Durum Açıklaması (Genel) Özet Bilgi "
    "Ağustos 2026 Satış Adetleri Bildirim İçeriği Açıklamalar "
    "Ağustos 2026'da Türkiye'de ebebek mağazaları ve e-ticaret kanalından "
    "satılan toplam ürün adedi 10.737.113 olarak gerçekleşmişken, bu sayı "
    "Ağustos 2025'te 8.676.273'tür. Ağustos 2026'da sona eren 8 aylık "
    "dönemde Türkiye'de ebebek mağazaları ve e-ticaret kanalından satılan "
    "toplam ürün adedi 82.546.307 olarak gerçekleşmişken, bu sayı 2025'in "
    "aynı döneminde 67.876.582'dir."
)

_SATIS_EBEBEK_ONEKLI_AGUSTOS_2024 = (
    "Özel Durum Açıklaması 6 Eylül 2024 Ağustos 2024 Satış Adetleri "
    "Ağustos 2024’te Türkiye’de ebebek mağazaları ve e-ticaret kanalından "
    "satılan toplam ürün adedi 7.445.297 olarak gerçekleşmişken, bu sayı "
    "Ağustos 2023’te 6.642.939’dur."
)

_ZIYARET_AGUSTOS_2026 = (
    "KAP'ta yayınlanma tarihi ve saati: 03.09.2026 18:34:41 "
    "EBEBEK MAĞAZACILIK A.Ş. Özel Durum Açıklaması (Genel) Özet Bilgi "
    "Ağustos 2026 Ziyaretçi Sayısı Bildirim İçeriği Açıklamalar "
    "Ağustos 2026'da Türkiye'deki ebebek mağazalarını ziyaret eden "
    "ziyaretçi sayısı 4.992.875 olarak gerçekleşmiş olup bu sayı Ağustos "
    "2025'te 4.586.675'tir. Ağustos 2026'da sona eren 8 aylık dönemde "
    "Türkiye'deki ebebek mağazalarını ziyaret eden ziyaretçi sayısı "
    "39.132.243, 2025 yılının aynı döneminde ise 35.111.762 olarak "
    "gerçekleşmiştir. Ağustos 2026'da ebebek.com internet sitesi ziyaret "
    "sayısı 10.978.359 olarak gerçekleşmiş olup bu sayı Ağustos 2025'te "
    "10.451.442'dir. Ağustos 2026'da sona eren 8 aylık dönemde ebebek.com "
    "internet sitesini ziyaret eden ziyaretçi sayısı 96.122.744, 2025 "
    "yılının aynı döneminde ise 91.724.081 olarak gerçekleşmiştir."
)

# Bilinen kaynak anomalisi: bu belge "Nisan 2025 Ziyaretçi Sayıları" başlığı
# altında listelenir ama içeriği aslında Mağaza Sayısı metnidir (ebebek IR
# sitesinin kendi dosya eşleme hatası) — ziyaretçi kalıpları hiç geçmez.
_NISAN_2025_YANLIS_ESLESEN_ICERIK = (
    "Özel Durum Açıklaması 2 Mayıs 2025 Nisan 2025 Mağaza Sayısı "
    "31 Mart 2025 tarihi itibarıyla 260 tanesi geleneksel, 13 tanesi ise "
    "mini mağaza konseptinde olmak üzere Türkiye’de toplam 273 mağazaya "
    "sahip olan şirketimizin mağaza sayısı 30 Nisan 2025 tarihi itibarıyla "
    "261 tanesi geleneksel, 15 tanesi mini olmak üzere 276’a ulaşmıştır."
)

_MAGAZA_EKIM_2023_ESKI_SABLON = (
    "Özel Durum Açıklaması 1 Kasım 2023 Ekim 2023 Mağaza Sayısı "
    "30 Eylül 2023 tarihi itibarıyla 220 tanesi geleneksel, 4 tanesi ise "
    "mini mağaza konseptinde olmak üzere Türkiye’de toplam 224 mağazaya "
    "sahip olan şirketimizin mağaza sayısı 31 Ekim 2023 tarihi itibarıyla "
    "221 tanesi geleneksel, 4 tanesi mini olmak üzere 225’e ulaşmıştır. "
    "30 Eylül - 31 Ekim 2023 tarihleri arasında; 1 Iğdır’da, 1 Manisa’da "
    "olmak üzere toplam 2 mağaza açılmıştır ve 1 mağaza Ayvalık’ta "
    "kapanmıştır."
)

# Değişmeyen ay: "X'e ulaşmıştır" yerine "olarak devam etmektedir" kalıbı.
_MAGAZA_DEGISMEYEN_ESKI_SABLON = (
    "Özel Durum Açıklaması 1 Haziran 2024 Mayıs 2024 Mağaza Sayısı "
    "30 Nisan 2024 tarihi itibarıyla 240 tanesi geleneksel, 7 tanesi ise "
    "mini mağaza konseptinde olmak üzere Türkiye’de toplam 247 mağazaya "
    "sahip olan şirketimizin mağaza sayısı 31 Mayıs 2024 tarihi itibarıyla "
    "240 tanesi geleneksel, 7 tanesi mini olmak üzere 247 olarak devam "
    "etmektedir."
)

_MAGAZA_AGUSTOS_2026_YENI_SABLON = (
    "KAP'ta yayınlanma tarihi ve saati: 01.09.2026 21:37:09 "
    "EBEBEK MAĞAZACILIK A.Ş. Özel Durum Açıklaması (Genel) Özet Bilgi "
    "Ağustos 2026 Mağaza Sayısı Bildirim İçeriği Açıklamalar "
    "Şirketimiz, Ağustos 2026 döneminde Zonguldak'ta açtığı 1 yeni mağaza "
    "ve Mersin'de kapattığı 1 mağazayla birlikte Türkiye'deki mağaza "
    "sayısını 316'da sabit tutmuştur. 31 Ağustos 2026 itibarıyla toplam "
    "mağaza durumumuz aşağıdaki gibidir: - Türkiye (316 Mağaza): 2 mega, "
    "282 standart, 32 mini - Yurt Dışı (4 Mağaza): 3 Birleşik Krallık, "
    "1 Kuzey Irak"
)


def ebebek_seri(**kwargs):
    varsayilan = dict(
        id="perakende/ebebek-satis-adedi",
        kaynak_tipi="ebebek",
        ebebek_metrik="satis_adedi",
        start_date=None,
    )
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


class SahteYanit:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class SahteOturum:
    def __init__(self, yanit):
        self.yanit = yanit
        self.cagrilar = 0

    def get(self, url, **kwargs):
        self.cagrilar += 1
        return self.yanit


def _duyuru_sayfasi(kayitlar, yabanci_grup_da_ekle=True):
    """`kayitlar`: [(başlık, url)] -> yatirimci-duyurulari sayfa parçacığı."""
    bloklar = [
        f'<div data-gtm-doc="{baslik}" data-gtm-doc-group="Özel Durum '
        f'Açıklamaları"><a href="{url}" target="_blank">indir</a></div>'
        for baslik, url in kayitlar
    ]
    if yabanci_grup_da_ekle:
        # Başka bir grup (Finansal Tablolar) — filtre bunu ASLA almamalı.
        bloklar.append(
            '<div data-gtm-doc="Esas Sözleşme" data-gtm-doc-group='
            '"Finansal Tablolar"><a href="https://kurumsal.ebebek.com/'
            'download?path=sozlesme.pdf">indir</a></div>'
        )
    return "<html><body>" + "".join(bloklar) + "</body></html>"


# --- duyuru_listesi: HTML ayrıştırma ---


def test_duyuru_listesi_yalniz_ozel_durum_grubunu_alir():
    kayitlar = [
        ("Ağustos 2026 Satış Adetleri", "https://kurumsal.ebebek.com/download?path=a.pdf"),
        ("Ağustos 2026 Mağaza Sayısı", "https://kurumsal.ebebek.com/download?path=b.pdf"),
    ]
    oturum = SahteOturum(SahteYanit(text=_duyuru_sayfasi(kayitlar)))
    sonuc = ebebek.duyuru_listesi(session=oturum)
    assert sonuc == kayitlar
    assert oturum.cagrilar == 1


def test_duyuru_listesi_http_hatasi_yukselir():
    oturum = SahteOturum(SahteYanit(status_code=500, text=""))
    with pytest.raises(requests.HTTPError, match="HTTP 500"):
        ebebek.duyuru_listesi(session=oturum)


def test_duyuru_listesi_hic_kayit_yoksa_hata():
    oturum = SahteOturum(SahteYanit(text=_duyuru_sayfasi([], yabanci_grup_da_ekle=False)))
    with pytest.raises(RuntimeError, match="Özel Durum Açıklamaları"):
        ebebek.duyuru_listesi(session=oturum)


# --- satis_noktalari ---


def test_satis_noktalari_gercek_deger_dondurur(monkeypatch):
    """Ağustos 2026 Satış Adedi — CANLI ölçülen referans kart değeriyle birebir."""
    kayitlar = [("Ağustos 2026 Satış Adetleri", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _SATIS_AGUSTOS_2026)

    noktalar = satis_noktalari()
    assert noktalar == {"2026-08-01": 10_737_113}


def test_satis_noktalari_ebebek_onekli_baslik_taninir(monkeypatch):
    kayitlar = [("ebebek Ağustos 2024 Satış Adetleri", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _SATIS_EBEBEK_ONEKLI_AGUSTOS_2024
    )

    noktalar = satis_noktalari()
    assert noktalar == {"2024-08-01": 7_445_297}


def test_satis_noktalari_deger_ayiklanamazsa_hata(monkeypatch):
    kayitlar = [("Ocak 2024 Satış Adetleri", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: "alakasız içerik")

    with pytest.raises(RuntimeError, match="ayıklanamadı"):
        satis_noktalari()


def test_satis_noktalari_celisen_yinelenen_anahtarda_hata(monkeypatch):
    kayitlar = [
        ("Ağustos 2026 Satış Adetleri", "https://x/a.pdf"),
        ("Ağustos 2026 Satış Adedi", "https://x/b.pdf"),
    ]
    metinler = {
        "https://x/a.pdf": _SATIS_AGUSTOS_2026,
        "https://x/b.pdf": _SATIS_AGUSTOS_2026.replace("10.737.113", "1.234.567"),
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    with pytest.raises(RuntimeError, match="çelişen"):
        satis_noktalari()


def test_satis_noktalari_ayni_degerli_yinelenen_sessizce_tekillesir(monkeypatch):
    """ebebek IR sitesinde bazı aylar aynı kategoriyi iki kez listeler
    (ör. gerçek 'Aralık 2024 Mağaza Sayısı' — bkz. modül docstring'i);
    değerler eşitse hata değil, tekil kayıt üretilmeli."""
    kayitlar = [
        ("Ağustos 2026 Satış Adetleri", "https://x/a.pdf"),
        ("Ağustos 2026 Satış Adedi", "https://x/b.pdf"),
    ]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _SATIS_AGUSTOS_2026)

    noktalar = satis_noktalari()
    assert noktalar == {"2026-08-01": 10_737_113}


# --- ziyaret_noktalari ---


def test_ziyaret_noktalari_iki_degeri_ayirir(monkeypatch):
    """Mağaza ziyaretçi ve web ziyaret — CANLI ölçülen referans değerlerle birebir."""
    kayitlar = [("Ağustos 2026 Ziyaretçi Sayısı", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _ZIYARET_AGUSTOS_2026)

    noktalar = ziyaret_noktalari()
    assert noktalar == {"2026-08-01": (4_992_875, 10_978_359)}


def test_ziyaret_noktalari_bilinen_bozuk_duyuruyu_atlar(monkeypatch):
    """Gerçek ebebek IR sitesinde "Nisan 2025 Ziyaretçi Sayıları" başlıklı
    duyurunun PDF'i Mağaza Sayısı içeriği taşıyor. Bu TEK duyuru
    `BOZUK_DUYURULAR`da açıkça listeli olduğu için atlanır — kaynak
    tarafındaki bir dosya hatası 34 ayın tamamını düşürmemeli."""
    kayitlar = [
        ("Nisan 2025 Ziyaretçi Sayıları", "https://x/nisan.pdf"),
        ("Ağustos 2026 Ziyaretçi Sayısı", "https://x/agustos.pdf"),
    ]
    metinler = {
        "https://x/nisan.pdf": _NISAN_2025_YANLIS_ESLESEN_ICERIK,
        "https://x/agustos.pdf": _ZIYARET_AGUSTOS_2026,
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    assert ziyaret_noktalari() == {"2026-08-01": (4_992_875, 10_978_359)}


def test_ziyaret_noktalari_listede_olmayan_uyusmazlikta_hata(monkeypatch):
    """Listeye yazılmamış bir başlık/içerik uyuşmazlığı hâlâ hata verir:
    istisna listesi açık tutulur, genel sessiz atlama yoktur."""
    kayitlar = [("Mart 2025 Ziyaretçi Sayıları", "https://x/mart.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _NISAN_2025_YANLIS_ESLESEN_ICERIK
    )

    with pytest.raises(RuntimeError, match="ayıklanamadı"):
        ziyaret_noktalari()


# --- magaza_noktalari ---


def test_magaza_noktalari_eski_sablon_geleneksel_mini(monkeypatch):
    kayitlar = [("Ekim 2023 Mağaza Sayısı", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _MAGAZA_EKIM_2023_ESKI_SABLON
    )

    noktalar = magaza_noktalari()
    assert noktalar == {"2023-10-01": {"toplam": 225, "standart": 221, "mini": 4}}
    assert "mega" not in noktalar["2023-10-01"]


def test_magaza_noktalari_eski_sablon_degismeyen_ay(monkeypatch):
    """'...ulaşmıştır' yerine '...olarak devam etmektedir' kalıbı (sayı
    değişmediğinde) da tanınmalı."""
    kayitlar = [("Mayıs 2024 Mağaza Sayısı", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _MAGAZA_DEGISMEYEN_ESKI_SABLON
    )

    noktalar = magaza_noktalari()
    assert noktalar == {"2024-05-01": {"toplam": 247, "standart": 240, "mini": 7}}


def test_magaza_noktalari_yeni_sablon_mega_kirilimi(monkeypatch):
    """Ağustos 2026'dan itibaren KAP bildirimi mega/standart/mini
    kırılımını farklı bir cümle kalıbıyla verir — CANLI ölçülen referans
    kart değerleriyle birebir."""
    kayitlar = [("Ağustos 2026 Mağaza Sayısı", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _MAGAZA_AGUSTOS_2026_YENI_SABLON
    )

    noktalar = magaza_noktalari()
    assert noktalar == {"2026-08-01": {"toplam": 316, "standart": 282, "mini": 32, "mega": 2}}


def test_magaza_noktalari_sablonsuz_metinde_hata(monkeypatch):
    kayitlar = [("Ocak 2024 Mağaza Sayısı", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: "alakasız içerik")

    with pytest.raises(RuntimeError, match="ayıklanamadı"):
        magaza_noktalari()


# --- seri_cek: ağ kabuğu, önbellek, start_date ---


def test_seri_cek_satis_adedi_dogru_deger_dondurur(monkeypatch):
    kayitlar = [("Ağustos 2026 Satış Adetleri", "https://x/a.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _SATIS_AGUSTOS_2026)

    df = seri_cek(ebebek_seri(), onbellek={})
    assert list(df["date"]) == ["2026-08-01"]
    assert df["value"].iloc[0] == 10_737_113


def test_seri_cek_ziyaret_onbellegi_iki_seri_arasinda_paylasilir(monkeypatch):
    """`magaza_ziyaretci` ve `web_ziyaret` aynı PDF kategorisini okur;
    önbellek paylaşılmazsa aynı ~35 belge iki kez indirilirdi."""
    cagri_sayaci = {"n": 0}

    def sahte_duyuru_listesi(session=None):
        cagri_sayaci["n"] += 1
        return [("Ağustos 2026 Ziyaretçi Sayısı", "https://x/a.pdf")]

    monkeypatch.setattr(ebebek, "duyuru_listesi", sahte_duyuru_listesi)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _ZIYARET_AGUSTOS_2026)

    onbellek: dict = {}
    df1 = seri_cek(ebebek_seri(ebebek_metrik="magaza_ziyaretci"), onbellek=onbellek)
    df2 = seri_cek(ebebek_seri(ebebek_metrik="web_ziyaret"), onbellek=onbellek)

    assert cagri_sayaci["n"] == 1
    assert df1["value"].iloc[0] == 4_992_875
    assert df2["value"].iloc[0] == 10_978_359


def test_seri_cek_mega_magaza_sadece_yeni_sablon_aylarini_icerir(monkeypatch):
    """Eski şablon aylarında 'mega' kavramı yok; `mega_magaza` serisi
    start_date'ten ÖNCEKİ bu ayları atlar (uydurma 0 değeri YASAK), yalnızca
    yeni şablonun kapsadığı ayları döner. (Mağaza dönemi başlıktan okunur;
    eski şablon metni Temmuz 2026 başlığıyla beslenir ki aylar ardışık olsun.)"""
    kayitlar = [
        ("Temmuz 2026 Mağaza Sayısı", "https://x/eski.pdf"),
        ("Ağustos 2026 Mağaza Sayısı", "https://x/yeni.pdf"),
    ]
    metinler = {
        "https://x/eski.pdf": _MAGAZA_EKIM_2023_ESKI_SABLON,
        "https://x/yeni.pdf": _MAGAZA_AGUSTOS_2026_YENI_SABLON,
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    df = seri_cek(ebebek_seri(ebebek_metrik="mega_magaza", start_date="2026-08-01"), onbellek={})
    assert list(df["date"]) == ["2026-08-01"]
    assert df["value"].iloc[0] == 2

    df_toplam = seri_cek(ebebek_seri(ebebek_metrik="toplam_magaza"), onbellek={})
    assert list(df_toplam["date"]) == ["2026-07-01", "2026-08-01"]


def test_seri_cek_start_date_oncesini_kirpar(monkeypatch):
    kayitlar = [
        ("Temmuz 2026 Mağaza Sayısı", "https://x/eski.pdf"),
        ("Ağustos 2026 Mağaza Sayısı", "https://x/yeni.pdf"),
    ]
    metinler = {
        "https://x/eski.pdf": _MAGAZA_EKIM_2023_ESKI_SABLON,
        "https://x/yeni.pdf": _MAGAZA_AGUSTOS_2026_YENI_SABLON,
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    df = seri_cek(
        ebebek_seri(ebebek_metrik="toplam_magaza", start_date="2026-08-01"), onbellek={}
    )
    assert list(df["date"]) == ["2026-08-01"]


def test_seri_cek_bilinmeyen_metrikte_hata():
    with pytest.raises(RuntimeError, match="bilinmeyen ebebek_metrik"):
        seri_cek(ebebek_seri(ebebek_metrik="uydurma"), onbellek={})


# --- Sessiz atlama korumaları (teslim notu bakım işi, 2026-11-27) ---

# Gerçek "Ekim 2026 Operasyonel Veriler" bildirimi (KAP 06.11.2026), kısaltılmış.
# Ekim 2026'dan itibaren üç kategori TEK belgede; eski başlık kalıpları bunu
# tanımadığı için Ekim 2026 üç kategoride de sessizce düşüyordu.
_OPERASYONEL_EKIM_2026 = (
    "KAP'ta yayınlanma tarihi ve saati: 06.11.2026 18:48:48 EBEBEK MAĞAZACILIK "
    "A.Ş. Özel Durum Açıklaması (Genel) Özet Bilgi Ekim 2026 Operasyonel "
    "Veriler Bildirim İçeriği Açıklamalar Mağaza Sayısı: Şirketimiz, Ekim 2026 "
    "döneminde açtığı Konya'da 1 yeni mağazayla birlikte Türkiye'deki mağaza "
    "sayısını 322'ye yükseltmiştir. 31 Ekim 2026 itibarıyla toplam mağaza "
    "durumumuz aşağıdaki gibidir: - Türkiye (322 Mağaza): 2 mega, 283 "
    "standart, 37 mini - Yurt Dışı (5 Mağaza): 4 Birleşik Krallık, 1 Kuzey "
    "Irak Ziyaretçi Sayısı: Ekim 2026'da Türkiye'deki ebebek mağazalarını "
    "ziyaret eden ziyaretçi sayısı 5.440.511 olarak gerçekleşmiş olup bu sayı "
    "Ekim 2025'te 4.854.935'tir. Ekim 2026'da ebebek.com internet sitesi "
    "ziyaret sayısı 11.136.416 olarak gerçekleşmiş olup bu sayı Ekim 2025'te "
    "11.456.239'dur. Satış Adetleri: Ekim 2026'da Türkiye'de ebebek "
    "mağazaları ve e-ticaret kanalından satılan toplam ürün adedi 11.620.026 "
    "olarak gerçekleşmişken, bu sayı Ekim 2025'te 9.681.629'dur."
)


def test_operasyonel_veriler_birlesik_belgesi_uc_kategoriye_okunur(monkeypatch):
    kayitlar = [("Ekim 2026 Operasyonel Veriler", "https://x/ekim.pdf")]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _OPERASYONEL_EKIM_2026)

    assert satis_noktalari() == {"2026-10-01": 11_620_026}
    assert ziyaret_noktalari() == {"2026-10-01": (5_440_511, 11_136_416)}
    assert magaza_noktalari() == {"2026-10-01": {"toplam": 322, "standart": 283, "mini": 37, "mega": 2}}


def test_tanınmayan_donemsel_baslik_hata_verir(monkeypatch):
    """Ay-yıl ile başlayan operasyonel görünümlü yeni bir başlık biçimi en
    yeni ayı sessizce yutamaz."""
    kayitlar = [
        ("Ağustos 2026 Satış Adetleri", "https://x/a.pdf"),
        ("Kasım 2026 Satış ve Ziyaretçi Verileri", "https://x/b.pdf"),
    ]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _SATIS_AGUSTOS_2026)

    with pytest.raises(RuntimeError, match="tanınmayan operasyonel veri duyurusu başlığı 'Kasım 2026"):
        satis_noktalari()


def test_ilgisiz_duyuru_basliklari_hata_vermez(monkeypatch):
    kayitlar = [
        ("Kuzey Irak'ta İlk Fiziksel Mağazanın Açılması", "https://x/k.pdf"),
        ("3Ç 2026 Finansal Rapor Açıklama Tarihi", "https://x/f.pdf"),
        ("Ağustos 2026 Satış Adetleri", "https://x/a.pdf"),
    ]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: _SATIS_AGUSTOS_2026)

    assert satis_noktalari() == {"2026-08-01": 10_737_113}


def test_aradaki_ay_eksikse_hata_verir(monkeypatch):
    """Temmuz ve Eylül var, Ağustos yok -> delikli çerçeve yazılmaz."""
    kayitlar = [
        ("Temmuz 2026 Mağaza Sayısı", "https://x/temmuz.pdf"),
        ("Eylül 2026 Mağaza Sayısı", "https://x/eylul.pdf"),
    ]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _MAGAZA_AGUSTOS_2026_YENI_SABLON
    )

    with pytest.raises(RuntimeError, match="'Mağaza Sayısı' serisinde okunamayan/eksik ay\\(lar\\): 2026-08-01"):
        magaza_noktalari()


def test_en_yeni_ay_henuz_yayimlanmamissa_hata_yok(monkeypatch):
    """Bugün Kasım sonu olsa da kaynak son olarak Ağustos'u yayımladıysa
    seri Ağustos'ta biter; yayımlanmamış ay hata DEĞİLDİR."""
    kayitlar = [
        ("Temmuz 2026 Mağaza Sayısı", "https://x/temmuz.pdf"),
        ("Ağustos 2026 Mağaza Sayısı", "https://x/agustos.pdf"),
    ]
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(
        ebebek, "_pdf_metni", lambda url, session=None: _MAGAZA_AGUSTOS_2026_YENI_SABLON
    )

    assert sorted(magaza_noktalari()) == ["2026-07-01", "2026-08-01"]


def test_bilinen_nisan_2025_ziyaret_boslugu_ardisiklik_denetimini_gecer(monkeypatch):
    mart = _ZIYARET_AGUSTOS_2026.replace("Ağustos 2026", "Mart 2025")
    mayis = _ZIYARET_AGUSTOS_2026.replace("Ağustos 2026", "Mayıs 2025")
    # Dönem içerikten okunur ("<Ay> <Yıl> Ziyaretçi"); metinler ona göre.
    kayitlar = [
        ("Mart 2025 Ziyaretçi Sayıları", "https://x/mart.pdf"),
        ("Nisan 2025 Ziyaretçi Sayıları", "https://x/nisan.pdf"),
        ("Mayıs 2025 Ziyaretçi Sayıları", "https://x/mayis.pdf"),
    ]
    metinler = {
        "https://x/mart.pdf": mart,
        "https://x/nisan.pdf": _NISAN_2025_YANLIS_ESLESEN_ICERIK,
        "https://x/mayis.pdf": mayis,
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    assert sorted(ziyaret_noktalari()) == ["2025-03-01", "2025-05-01"]


def test_bilinmeyen_ziyaret_boslugu_hata_verir(monkeypatch):
    mart = _ZIYARET_AGUSTOS_2026.replace("Ağustos 2026", "Mart 2025")
    mayis = _ZIYARET_AGUSTOS_2026.replace("Ağustos 2026", "Mayıs 2026")
    kayitlar = [
        ("Mart 2025 Ziyaretçi Sayıları", "https://x/mart.pdf"),
        ("Mayıs 2026 Ziyaretçi Sayısı", "https://x/mayis.pdf"),
    ]
    metinler = {"https://x/mart.pdf": mart, "https://x/mayis.pdf": mayis}
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    with pytest.raises(RuntimeError, match="eksik ay\\(lar\\): 2025-05-01"):
        ziyaret_noktalari()


def test_seri_cek_start_date_sonrasi_mega_kirilimi_yoksa_hata(monkeypatch):
    kayitlar = [
        ("Temmuz 2026 Mağaza Sayısı", "https://x/yeni.pdf"),
        ("Ağustos 2026 Mağaza Sayısı", "https://x/eski.pdf"),
    ]
    metinler = {
        "https://x/yeni.pdf": _MAGAZA_AGUSTOS_2026_YENI_SABLON,
        "https://x/eski.pdf": _MAGAZA_EKIM_2023_ESKI_SABLON,
    }
    monkeypatch.setattr(ebebek, "duyuru_listesi", lambda session=None: kayitlar)
    monkeypatch.setattr(ebebek, "_pdf_metni", lambda url, session=None: metinler[url])

    with pytest.raises(RuntimeError, match="2026-08-01 Mağaza Sayısı bildiriminde 'mega' kırılımı yok"):
        seri_cek(ebebek_seri(ebebek_metrik="mega_magaza", start_date="2026-07-01"), onbellek={})


# --- Çeyreklik sunumlar: liste, PDF, sayfa varlığı, bilinen atlama ---


def _sunum_sayfasi(damgalar):
    """`damgalar`: ["31.03.25", ...] -> finansal-bilgiler sayfa parçacığı."""
    return "".join(
        f'<div data-gtm-doc="Analist Toplantısı Sunumu" data-gtm-doc-group="Finansal '
        f'Sonuçlara İlişkin Sunumlar"><strong>{d}</strong><a href="https://kurumsal.'
        f'ebebek.com/download?path={i}.pdf">indir</a></div>'
        for i, d in enumerate(damgalar)
    )


def test_sunum_listesi_kesintisizse_doner():
    oturum = SahteOturum(SahteYanit(text=_sunum_sayfasi(["31.12.24", "31.03.25", "30.06.25"])))
    sonuc = ebebek._sunum_listesi(session=oturum)
    assert [(s["yil"], s["ceyrek"]) for s in sonuc] == [(2024, 4), (2025, 1), (2025, 2)]


def test_sunum_listesinde_aradaki_ceyrek_eksikse_hata():
    oturum = SahteOturum(SahteYanit(text=_sunum_sayfasi(["31.12.24", "30.09.25"])))
    with pytest.raises(RuntimeError, match="okunamadı: 1Ç 2025, 2Ç 2025"):
        ebebek._sunum_listesi(session=oturum)


def test_listelenen_sunum_pdfi_404_verirse_hata():
    """Eskiden 404 None döndürüp o çeyreği sessizce atlıyordu."""
    oturum = SahteOturum(SahteYanit(status_code=404))
    with pytest.raises(requests.HTTPError, match="HTTP 404"):
        ebebek._sunum_pdfsini_getir("https://x/s.pdf", {}, session=oturum)


def _sunum_onbellegi(donemler):
    onbellek = {"sunumlar": []}
    for yil, ceyrek in donemler:
        url = f"https://x/{yil}-{ceyrek}.pdf"
        onbellek["sunumlar"].append({"yil": yil, "ceyrek": ceyrek, "url": url})
        onbellek[("sunum_bayt", url)] = url.encode()
    return onbellek


def _ayiklayicilari_sahtele(monkeypatch, kanal, fatura, kategori):
    """Her biri `bayt -> sonuç` (ya da hata yükselten) sahte ayıklayıcı."""
    monkeypatch.setattr(ebebek, "kanal_buyume_ve_payini_ayikla", kanal)
    monkeypatch.setattr(ebebek, "fatura_siparis_pl_lfl_ayikla", fatura)
    monkeypatch.setattr(ebebek, "kategori_buyumesini_ayikla", kategori)


def _kategori_sonucu(deger):
    return {m: deger for m in ebebek._KATEGORI_SIRASI}


def test_sunum_ayristirma_hatasi_artik_yutulmaz(monkeypatch):
    def kategori(bayt):
        if bayt == b"https://x/2025-1.pdf":
            raise RuntimeError("ebebek kategori büyümesi: 4 değer bekleniyordu, 3 bulundu")
        return _kategori_sonucu(5.0)

    # Kanal sayfası 4Ç 2024'ten beri zorunlu: sahte boş sonuç ("sayfa var").
    _ayiklayicilari_sahtele(monkeypatch, lambda b: {}, lambda b: None, kategori)
    onbellek = _sunum_onbellegi([(2024, 3), (2025, 1)])
    with pytest.raises(RuntimeError, match="1Ç 2025 Analist Toplantısı Sunumu 'kategori' sayfası okunamadı"):
        ebebek._sunum_metriklerini_getir(onbellek)


def test_bilinen_4c_2024_kanal_atlamasi_hata_vermez(monkeypatch):
    def kanal(bayt):
        if bayt == b"https://x/2024-4.pdf":
            raise RuntimeError("ebebek kanal büyümesi: sunum çeyrek/YBİ çifti taşımıyor, yalnızca kümülatif")
        return {"kanal_payi_magaza": 87.0}

    _ayiklayicilari_sahtele(monkeypatch, kanal, lambda b: None, lambda b: _kategori_sonucu(5.0))
    onbellek = _sunum_onbellegi([(2024, 4), (2025, 1)])
    sonuc = ebebek._sunum_metriklerini_getir(onbellek)
    assert sonuc["kanal_payi_magaza"] == {"2025-01-01": 87.0}
    assert sorted(sonuc["kategori_buyume_tekstil"]) == ["2024-10-01", "2025-01-01"]


def test_sayfa_ilk_ceyrekten_once_yoksa_hata_yok_sonra_yoksa_hata(monkeypatch):
    """Kategori sayfası 4Ç 2024'ten önce yok (doğal); 1Ç 2025'te yoksa sayfa
    tanıma bozulmuştur (1Ç 2025 kanal sayfası tam olarak böyle düşüyordu)."""
    def kategori(bayt):
        return _kategori_sonucu(5.0) if bayt == b"https://x/2024-4.pdf" else None

    _ayiklayicilari_sahtele(monkeypatch, lambda b: {}, lambda b: None, kategori)
    with pytest.raises(RuntimeError, match="1Ç 2025 Analist Toplantısı Sunumu'nda 'kategori' sayfası bulunamadı"):
        ebebek._sunum_metriklerini_getir(_sunum_onbellegi([(2024, 3), (2024, 4), (2025, 1)]))

    _ayiklayicilari_sahtele(monkeypatch, lambda b: {}, lambda b: None, kategori)
    sonuc = ebebek._sunum_metriklerini_getir(_sunum_onbellegi([(2024, 3), (2024, 4)]))
    assert sonuc["kategori_buyume_tekstil"] == {"2024-10-01": 5.0}


# --- Sunum sayfası ayrıştırıcıları (pdfplumber sahte nesneyle) ---


class SahteSayfa:
    def __init__(self, metin, kelimeler=()):
        self.metin = metin
        self.kelimeler = list(kelimeler)

    def extract_text(self):
        return self.metin

    def extract_words(self):
        return self.kelimeler


class SahtePdf:
    def __init__(self, sayfalar):
        self.pages = sayfalar

    def __enter__(self):
        return self

    def __exit__(self, *hata):
        return False


def _pdfplumber_sahtele(monkeypatch, sayfalar):
    monkeypatch.setattr(ebebek, "pdfplumber", SimpleNamespace(open=lambda dosya: SahtePdf(sayfalar)))


def _k(metin, x0, top):
    return {"text": metin, "x0": x0, "top": top}


def test_kategori_buyumesi_eksi_rozeti_okur(monkeypatch):
    """1Ç 2025 sunumu (ölçüldü 2026-11-27): Bebek Araç-Gereç rozeti "-%9";
    eski kalıp yalnızca "+" kabul edip 3 değer buluyor, sunum düşüyordu."""
    metin = (
        "Kategoriler arası stratejik konumlandırmaya olanak tanıyan\n"
        "Hızlı tüketim ürünleri Tamamlayıcı ürünler\n+%6 +%12\n"
        "Tekstil ürünleri Bebek araç & gereçleri\n+%11 -%9\n"
    )
    _pdfplumber_sahtele(monkeypatch, [SahteSayfa(metin)])
    assert ebebek.kategori_buyumesini_ayikla(b"") == {
        "kategori_buyume_hizli_tuketim": 6.0, "kategori_buyume_tamamlayici": 12.0,
        "kategori_buyume_tekstil": 11.0, "kategori_buyume_bebek_arac_gerec": -9.0,
    }


def test_kanal_sayfasi_buyuk_harfli_basligi_tanir(monkeypatch):
    """1Ç 2025 sunumu başlığı "Satış Kanalı Bazında Satış" (büyük S) yazıyor;
    eski arama küçük harf beklediği için sayfa None dönüp çeyrek düşüyordu."""
    metin = (
        "Mağaza Satış Adetleri ebebek.com Satış Adetleri Pazaryeri Satış Adetleri "
        "Satış Kanalı Bazında Satış\n(Bin) Adedi Kırılımı\n1Ç’25\n%4\n%10\n% 86\n"
        "%14,3 %0,5 %32,9\n1Ç’24/25 1Ç’24/25 1Ç’24/25\nMağaza ebebek.com Pazar Yeri\n"
    )
    kelimeler = [_k("%4", 1700, 300), _k("%10", 1650, 330), _k("%", 1600, 400), _k("86", 1610, 405)]
    _pdfplumber_sahtele(monkeypatch, [SahteSayfa(metin, kelimeler)])
    assert ebebek.kanal_buyume_ve_payini_ayikla(b"") == {
        "kanal_buyume_magaza": 14.3, "kanal_buyume_web": 0.5, "kanal_buyume_pazaryeri": 32.9,
        "kanal_payi_magaza": 86.0, "kanal_payi_web": 10.0, "kanal_payi_pazaryeri": 4.0,
    }


_FATURA_SAYFA_METNI = "Satış Kanalı Bazında PL (Öz Marka) Adet Payı Aynı Mağaza (LFL)* Satış Adetleri"


def test_fatura_sayfasi_2c_2026_turkce_bicim(monkeypatch):
    """2Ç 2026 sunumunun gerçek kelime konumları (ölçüldü 2026-11-27)."""
    kelimeler = [
        _k("1.988", 933, 347), _k("1.903", 1315, 351), _k("57,1%", 1791, 355),
        _k("1.198", 220, 363), _k("1.147", 617, 366), _k("1.337", 806, 377),
        _k("53,2%", 1498, 374), _k("53,4%", 1595, 373), _k("874", 91, 382),
        _k("827", 487, 384), _k("1.219", 1189, 382), _k("50,3%", 1692, 389),
        _k("6A’26", 1797, 221),
        _k("2Ç'25", 83, 451), _k("2Ç'26", 216, 451), _k("6A'25", 480, 451), _k("6A'26", 613, 451),
        _k("2Ç'25", 804, 456), _k("2Ç'26", 931, 456), _k("6A'25", 1186, 456), _k("6A'26", 1313, 456),
        _k("44.283", 799, 771), _k("39.006", 671, 782), _k("23.834", 1533, 806),
        _k("23.337", 418, 813), _k("21.534", 1408, 811), _k("20.614", 291, 818),
        _k("13.878", 1154, 827), _k("11.823", 1028, 832),
        _k("2Ç'25", 295, 878), _k("2Ç'26", 423, 878), _k("6A'25", 677, 878), _k("6A'26", 805, 878),
        _k("2Ç'25", 1030, 876), _k("2Ç'26", 1157, 876), _k("6A'25", 1411, 876), _k("6A'26", 1539, 876),
        _k("30", 474, 979), _k("19", 1753, 1034),
    ]
    _pdfplumber_sahtele(monkeypatch, [SahteSayfa(_FATURA_SAYFA_METNI, kelimeler)])
    assert ebebek.fatura_siparis_pl_lfl_ayikla(b"") == {
        "magaza_fatura_ortalama": 1198.0, "web_siparis_ortalama": 1988.0,
        "lfl_satis_adedi": 23337.0, "lfl_giris_sayisi": 13878.0,
        "pl_payi_toplam": 53.2, "pl_payi_magaza": 53.4, "pl_payi_web": 50.3, "pl_payi_pazaryeri": 57.1,
    }


def test_fatura_sayfasi_3c_2026_ingilizce_bicim_ve_yalniz_kumulatif_lfl(monkeypatch):
    """3Ç 2026 sunumu (ölçüldü 2026-11-27): İngilizce sayı biçimi ve LFL
    paneli yalnızca 9A. Eski kod PL payını 536, LFL'yi 30 yazıyordu; artık
    PL 53,6 ve LFL hiç yazılmıyor (kaynak çeyrek LFL'yi yayımlamamış)."""
    kelimeler = [
        _k("2,177", 981, 339), _k("1,989", 1299, 347), _k("1,291", 220, 358),
        _k("61.1%", 1793, 356), _k("1,197", 617, 363), _k("1,562", 821, 367),
        _k("967", 91, 376), _k("1,326", 1140, 377), _k("876", 488, 382),
        _k("53.6%", 1498, 386), _k("53.5%", 1595, 386), _k("51.3%", 1694, 395),
        _k("9A’26", 1797, 221),
        _k("3Ç'25", 83, 451), _k("3Ç'26", 216, 451), _k("9A'25", 480, 451), _k("9A'26", 613, 451),
        _k("3Ç'25", 820, 456), _k("3Ç'26", 979, 456), _k("9A'25", 1138, 456), _k("9A'26", 1297, 456),
        _k("66,295", 703, 765), _k("58,050", 384, 777), _k("34,777", 1120, 801), _k("36,383", 1438, 798),
        _k("9A'25", 391, 878), _k("9A'26", 709, 878), _k("9A'25", 1125, 876), _k("9A'26", 1443, 876),
        _k("30", 593, 979), _k("17", 1753, 1034),
    ]
    _pdfplumber_sahtele(monkeypatch, [SahteSayfa(_FATURA_SAYFA_METNI, kelimeler)])
    assert ebebek.fatura_siparis_pl_lfl_ayikla(b"") == {
        "magaza_fatura_ortalama": 1291.0, "web_siparis_ortalama": 2177.0,
        "pl_payi_toplam": 53.6, "pl_payi_magaza": 53.5, "pl_payi_web": 51.3, "pl_payi_pazaryeri": 61.1,
        ebebek.LFL_YALNIZ_KUMULATIF_ISARETI: True,
    }


def test_fatura_sayfasi_cubuk_degeri_yoksa_hata(monkeypatch):
    kelimeler = [
        _k("1,0%", 1500, 380), _k("2,0%", 1600, 380), _k("3,0%", 1700, 380), _k("4,0%", 1800, 380),
        _k("874", 91, 382), _k("1.198", 220, 363), _k("1.337", 806, 377),  # 4. çubuk değeri yok
        _k("1Ç'25", 83, 451), _k("1Ç'26", 216, 451), _k("1Ç'25", 804, 456), _k("1Ç'26", 931, 456),
        _k("10", 291, 818), _k("11", 418, 813), _k("12", 1028, 832), _k("13", 1154, 827),
        _k("1Ç'25", 295, 878), _k("1Ç'26", 423, 878), _k("1Ç'25", 1030, 876), _k("1Ç'26", 1157, 876),
    ]
    _pdfplumber_sahtele(monkeypatch, [SahteSayfa(_FATURA_SAYFA_METNI, kelimeler)])
    with pytest.raises(RuntimeError, match="'1Ç'26' çubuğunun değeri bulunamadı"):
        ebebek.fatura_siparis_pl_lfl_ayikla(b"")


def test_sunum_sayisi_iki_bicimi_ayirir():
    assert ebebek._sunum_sayisi("1.291") == 1291.0
    assert ebebek._sunum_sayisi("1,291") == 1291.0
    assert ebebek._sunum_sayisi("53,2%") == 53.2
    assert ebebek._sunum_sayisi("53.6%") == 53.6
    assert ebebek._sunum_sayisi("874") == 874.0
    with pytest.raises(RuntimeError, match="sayı biçimi tanınmadı"):
        ebebek._sunum_sayisi("1.2.3,4")


def _yalniz_kumulatif_fatura(bayt):
    return {"magaza_fatura_ortalama": 1291.0, ebebek.LFL_YALNIZ_KUMULATIF_ISARETI: True}


def test_lfl_yalniz_kumulatif_listede_olmayan_ceyrekte_hata(monkeypatch):
    """LFL çeyrek etiketi yalnızca belgeli çeyrekte eksik olabilir; başka
    bir çeyrekte eksikse etiket deseni kaymıştır, LFL serisinde delik açılmaz."""
    _ayiklayicilari_sahtele(monkeypatch, lambda b: {}, _yalniz_kumulatif_fatura, lambda b: _kategori_sonucu(5.0))
    with pytest.raises(RuntimeError, match="2Ç 2026 Analist Toplantısı Sunumu 'fatura' sayfasında LFL panelleri çeyrek etiketi taşımıyor"):
        ebebek._sunum_metriklerini_getir(_sunum_onbellegi([(2026, 2)]))


def test_lfl_yalniz_kumulatif_bilinen_3c_2026_hata_vermez(monkeypatch):
    _ayiklayicilari_sahtele(monkeypatch, lambda b: {}, _yalniz_kumulatif_fatura, lambda b: _kategori_sonucu(5.0))
    sonuc = ebebek._sunum_metriklerini_getir(_sunum_onbellegi([(2026, 3)]))
    assert sonuc["magaza_fatura_ortalama"] == {"2026-07-01": 1291.0}
    assert sonuc["lfl_satis_adedi"] == {}
    assert ebebek.LFL_YALNIZ_KUMULATIF_ISARETI not in sonuc
