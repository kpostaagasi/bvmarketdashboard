"""TAB Gıda çeyreklik "Finansal Bülten" PDF ayrıştırma testleri.

Şebeke bağımlılığı yok. Canlı ölçüm 30 Eylül 2026: WAF sorunu
`_WafAdapter` ile çözüldü (docstring), 12 bültenin 12'si de okundu — bu
testler ayrıştırma mantığını ve "yayımlanmamış ↔ okunamayan" ayrımını
(27 Kasım 2026) kanıtlar, HTML örnekleri canlı
sayfadan birebir alınmış satırlardır."""

from types import SimpleNamespace

import pytest
import requests

from ingest.tabgida import (
    GECERLI_METRIKLER,
    _bulten_listesi,
    fis_sayisini_ayikla,
    restoran_sayisini_ayikla,
    seri_cek,
)


def tabgd_seri(**kwargs):
    varsayilan = dict(id="restoran/tabgd-restoran-sayisi", tabgida_metrik="restoran-sayisi")
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


class _Yanit:
    """`_bulten_listesi` yalnızca `.text` ve `.raise_for_status()` kullanıyor."""

    def __init__(self, metin, kod=200):
        self.text = metin
        self.status_code = kod

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


class _SahteOturum(requests.Session):
    """Gerçek `requests.Session` — `_oturum` bu sınıfa `mount` uyguluyor."""

    def __init__(self, sayfa):
        super().__init__()
        self._sayfa = sayfa
        self.istenen: list[str] = []

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.istenen.append(url)
        return _Yanit(self._sayfa)


def test_restoran_sayisini_ayikla_toplam_ulastirdik_kalibi():
    metin = "30 Haziran 2026 itibarıyla toplam restoran sayımızı 2.100'e ulaştırdık."
    assert restoran_sayisini_ayikla(metin) == 2100.0


def test_restoran_sayisini_ayikla_yili_kapatti_kalibi():
    """FY bültenlerinde farklı ifade biçimi: 'yılı N lokasyonla kapattık'."""
    metin = "restoran sayımızda 2.000'i aştık ve yılı 2.030 lokasyonla kapattık."
    assert restoran_sayisini_ayikla(metin) == 2030.0


def test_restoran_sayisini_ayikla_satir_ortasinda_bolunen_cumle():
    """2Ç 2026 PDF'inde cümle satır ortasında bölünüyor (canlı ölçüm)."""
    metin = (
        "30 Haziran 2026 itibarıyla toplam restoran sayımızı 2.100'e\n"
        "ulaştırdık. Bu çeyrekte açılan restoranların yarısı franchise.\n"
    )
    assert restoran_sayisini_ayikla(metin) == 2100.0


def test_restoran_sayisini_ayikla_lokasyona_ulaştik_kalibi():
    """4Ç 2024 canlı metni: 'Açtığımız 246 yeni restoranla toplamda 1.830\nlokasyona ulaştık.'"""
    metin = "Açtığımız 246 yeni restoranla toplamda 1.830\nlokasyona ulaştık.\n"
    assert restoran_sayisini_ayikla(metin) == 1830.0


def test_restoran_sayisini_ayikla_portfoy_kalibi():
    """1Ç 2025 canlı metni: 'restoran portföyümüz 1.854 lokasyona ulaştı'."""
    metin = "Çeyrek sonu itibariyle restoran portföyümüz 1.854 lokasyona ulaştı ve franchise.\n"
    assert restoran_sayisini_ayikla(metin) == 1854.0


def test_restoran_sayisini_ayikla_ye_soneki_ve_toplamsiz_kalip():
    """3Ç 2023 canlı metni: "toplam restoran sayımızı 1.572'ye çıkardık" —
    ek `y` içeren sonek. 1Ç 2024'te "toplam" kelimesi YOK:
    "restoran sayımızı 1.654'e çıkardık"."""
    assert restoran_sayisini_ayikla(
        "3Ç 2023'te net 38 restoran açarak toplam restoran sayımızı 1.572'ye çıkardık.\n"
    ) == 1572.0
    assert restoran_sayisini_ayikla(
        "3Ç 2024'te 61 yeni restoran açarak restoran sayımızı 1.654'e çıkardık.\n"
    ) == 1654.0


def test_restoran_sayisini_ayikla_yalnizca_yeni_acilan_sayi_eslesmez():
    """3Ç 2024/1Ç 2026 yalnızca 'N yeni restoran açtık' diyor; çeyreklik
    toplam bildirmediği için seri o dönem boş kalmalı (sessiz 0 üretmemek)."""
    metin = "3. çeyrekte 76 yeni restoran açtık.\n"
    assert restoran_sayisini_ayikla(metin) is None


def test_restoran_sayisini_ayikla_eslesme_yoksa_none():
    assert restoran_sayisini_ayikla("ilgisiz içerik") is None


def test_fis_sayisini_ayikla_ikinci_sayiyi_alir_cari_donem():
    """TAB Gıda tablo sırası BigChefs'in TERSİ: önceki yıl önce, cari sonra."""
    metin = "Fiş sayısı ('000) 207.648 247.196 %19,0 207.648 247.196 %19,0\n"
    assert fis_sayisini_ayikla(metin) == 247196.0


def test_fis_sayisini_ayikla_4c_fy_tablosunda_fy_degerini_alir():
    """4Ç 2023 canlı satırı: ikinci alan 4Ç 2023 (47.081), FY 2023 BEŞİNCİ
    alanda (203.718). İkinciyi almak yıl değil çeyrek fiş sayısı üretirdi."""
    metin = "Fiş sayısı ('000) 47.287 47.081 %0 183.140 203.718 %11\n"
    assert fis_sayisini_ayikla(metin) == 203718.0


def test_fis_sayisini_ayikla_ingilizce_satir_etiketini_kabul_eder():
    """4Ç 2024 tek çeyrekte İngilizce yayımlandı: 'Number of tickets'."""
    metin = "Number of tickets ('000) 47.081 51.309 %9 203.718 207.648 %2\n"
    assert fis_sayisini_ayikla(metin) == 207648.0


def test_fis_sayisini_ayikla_etiketsiz_satiri_atlar_etiketliyi_kullanir():
    """4Ç 2023 bülteninde (canlı metin, 27 Kasım 2026) önce birim etiketsiz
    FY özeti satırı ('Fiş sayısı 183.140 203.718 %11'), sonra `('000)`
    etiketli 4Ç+FY satırı gelir. Desen yalnızca etiketliyi kabul eder (birim
    bilinmeden ölçek varsayılmaz); etiketli satırın FY alanı alınır.
    Bu test eskiden aynı adlı ikinci testle gölgelenip hiç koşmuyordu."""
    metin = (
        "(Milyon TL) FY 2022 FY 2023 Yıllık değişim\n"
        "Fiş sayısı 183.140 203.718 %11\n"
        "Fiş sayısı ('000) 47.287 47.081 %0 183.140 203.718 %11\n"
    )
    assert fis_sayisini_ayikla(metin) == 203718.0


def test_fis_sayisini_ayikla_yalniz_etiketsiz_satir_eslesmez():
    """Yalnız birim etiketsiz satır varsa `None` — `seri_cek` bunu sessiz
    boşluk değil 'fiş sayısı satırı okunamadı' hatasına çevirir."""
    metin = "(Milyon TL) FY 2022 FY 2023 Yıllık değişim\nFiş sayısı 183.140 203.718 %11\n"
    assert fis_sayisini_ayikla(metin) is None


def test_fis_sayisini_ayikla_bin_adet_olceginde_kalir():
    """Değer zaten bin adet cinsinden — ayrıca 1000 ile çarpılmamalı."""
    metin = "Fiş sayısı ('000) 100.000 150.000 %50,0 100.000 150.000 %50,0\n"
    assert fis_sayisini_ayikla(metin) == 150000.0  # 150 milyon fiş değil


def test_fis_sayisini_ayikla_anlatim_cumlesi_eslesmez():
    """4Ç 2024'te anlatım cümlesi var ('Fiş sayısı 51,3 milyona ulaşarak') —
    tablo satırı olmadığı için eşleşmemeli."""
    metin = "Fiş sayısı 4Ç 2024'te yıllık bazda %9 artışla 51,3 milyona ulaşarak.\n"
    assert fis_sayisini_ayikla(metin) is None


def _sayfa(*satirlar: str) -> str:
    govde = "".join(
        f'<tr><td>{c}. Çeyrek</td><td><a href="sunum-{c}.pdf">İncele</a></td>'
        f'<td><a href="{h}">İncele</a></td></tr>'
        for c, h in satirlar
    )
    return f"<thead><tr><th>2026</th></tr></thead><tbody>{govde}</tbody>"


def test_bulten_listesi_bozuk_href_i_temizler():
    """2024/4.Çeyrek canlı HTML'de `href="<../cmsfiles/..."` — baştaki `<`
    fazlalık. Ayırıcı temizlenmeli, bağlantı atlanmamalı."""
    oturum = _SahteOturum(_sayfa(("4", "<../cmsfiles/yatirimci-iliskileri/fy.pdf")))
    liste = _bulten_listesi(session=oturum)
    assert [b["url"] for b in liste] == [
        "https://www.tabgida.com.tr/cmsfiles/yatirimci-iliskileri/fy.pdf"
    ]


def test_fis_sayisini_ayikla_yalniz_fy_ozeti_tablosu_etiketli_satir():
    """4Ç 2023'ün ikinci tablosunda satır etiketi 'Fiş sayısı ('000)' ve
    yalnızca iki değer var (FY 2022 / FY 2023) → ikincisi zaten FY."""
    metin = "(Milyon TL) FY 2022 FY 2023 Yıllık değişim\nFiş sayısı ('000) 183.140 203.718 %11\n"
    assert fis_sayisini_ayikla(metin) == 203718.0



def test_bulten_listesi_onarilamayan_href_hata_verir():
    """Satır var, bülten bağlantısı var ama href onarılamıyor → bülten
    yayımlanmış ama okunamıyor. Atlamak o çeyreği CSV'den sessizce silerdi."""
    oturum = _SahteOturum(
        _sayfa(
            ("1", "cmsfiles/<bozuk.pdf"),
            ("2", "../cmsfiles/saglam.pdf"),
        )
    )
    with pytest.raises(RuntimeError, match="2026 1Ç Finansal Bülten bağlantısı okunamadı"):
        _bulten_listesi(session=oturum)


def test_bulten_listesi_bos_href_hata_verir():
    oturum = _SahteOturum(_sayfa(("3", " ")))
    with pytest.raises(RuntimeError, match="2026 3Ç Finansal Bülten bağlantısı okunamadı"):
        _bulten_listesi(session=oturum)


def test_bulten_listesi_baglantisiz_bulten_hucresi_yayimlanmamis_sayilir():
    """Meşru 'henüz yayımlanmadı': satır sunumla açılmış, bülten hücresi boş.
    Hata vermez; o çeyrek listede yer almaz, sağlam olanlar okunur."""
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td><a href="s1.pdf">İncele</a></td>'
        '<td><a href="../cmsfiles/b1.pdf">İncele</a></td></tr>'
        '<tr><td>2. Çeyrek</td><td><a href="s2.pdf">İncele</a></td><td></td></tr>'
        "</tbody>"
    )
    liste = _bulten_listesi(session=_SahteOturum(sayfa))
    assert [b["ceyrek"] for b in liste] == [1]
    assert liste[0]["url"] == "https://www.tabgida.com.tr/cmsfiles/b1.pdf"


def test_bulten_listesi_eksik_hucreli_satir_hata_verir():
    """Eski tek parça satır deseni şablona uymayan satırı sessizce atlıyordu."""
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>3. Çeyrek</td><td><a href="../cmsfiles/b3.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="2026 3Ç satırında 3 yerine 2 hücre"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_etiketsiz_satir_hata_verir():
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>Q3</td><td>x</td><td><a href="../cmsfiles/b3.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="2026 tablosunda çeyrek etiketi okunamayan satır"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_ortadaki_baglantisiz_ceyrek_hata_verir():
    """Bağlantısız bülten hücresi yalnızca EN YENİ dönem için 'henüz
    yayımlanmadı' sayılır. Ortadaki çeyreğin bağlantısı kalkarsa (CMS
    düzenlemesi) o çeyrek sessizce silinirdi."""
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b1.pdf">İncele</a></td></tr>'
        "<tr><td>2. Çeyrek</td><td>s</td><td></td></tr>"
        '<tr><td>3. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b3.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="bağlantısı daha yeni bülten yayımlanmışken eksik: 2026 2Ç"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_ortadaki_satir_kaybolursa_hata_verir():
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b1.pdf">İncele</a></td></tr>'
        '<tr><td>3. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b3.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="aralıklı — eksik dönem: 2026 2Ç"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_yil_sinirinda_eksik_ceyregi_bulur():
    """2025 4Ç satırı kaybolmuş: 2025 3Ç → 2026 1Ç arası aralık."""
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b261.pdf">İncele</a></td></tr>'
        "</tbody>"
        "<thead><tr><th>2025</th></tr></thead><tbody>"
        '<tr><td>3. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b253.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="eksik dönem: 2025 4Ç"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_yil_sinirinda_aralıksiz_dizi_gecer():
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b261.pdf">İncele</a></td></tr>'
        "</tbody>"
        "<thead><tr><th>2025</th></tr></thead><tbody>"
        '<tr><td>4. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b254.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    liste = _bulten_listesi(session=_SahteOturum(sayfa))
    assert [(b["yil"], b["ceyrek"]) for b in liste] == [(2026, 1), (2025, 4)]


def test_bulten_listesi_oznitelikli_etiketleri_okur():
    """CMS `<tr class=...>`, `<tbody id=...>`, `<th scope=...>` üretirse
    satır/yıl sessizce düşmemeli."""
    sayfa = (
        '<thead class="h"><tr class="r"><th scope="col">2026</th><th>X</th></tr></thead>'
        '<tbody id="g">'
        '<tr class="a"><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b1.pdf">İncele</a></td></tr>'
        '<tr data-x="1"><td>2. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b2.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    liste = _bulten_listesi(session=_SahteOturum(sayfa))
    assert [b["ceyrek"] for b in liste] == [1, 2]


def test_bulten_listesi_ayristirilamayan_yil_tablosu_hata_verir():
    """Bir yılın başlığı şablona uymazsa o yılın bütün çeyrekleri düşerdi;
    `<tbody>` sayısı ile yıl tablosu sayısı karşılaştırılır."""
    sayfa = (
        "<thead><tr><th>2026</th></tr></thead><tbody>"
        '<tr><td>1. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b1.pdf">İncele</a></td></tr>'
        "</tbody>"
        "<thead><tr><td>Yıl 2025</td></tr></thead><tbody>"
        '<tr><td>4. Çeyrek</td><td>s</td><td><a href="../cmsfiles/b4.pdf">İncele</a></td></tr>'
        "</tbody>"
    )
    with pytest.raises(RuntimeError, match="2 tablo gövdesi var ama 1 yıl tablosu"):
        _bulten_listesi(session=_SahteOturum(sayfa))


def test_bulten_listesi_ayni_donem_iki_kez_hata_verir():
    oturum = _SahteOturum(_sayfa(("1", "../cmsfiles/a.pdf"), ("1", "../cmsfiles/b.pdf")))
    with pytest.raises(RuntimeError, match="aynı dönem için birden çok.*2026 1Ç"):
        _bulten_listesi(session=oturum)


def test_bulten_listesi_bos_sayfada_hata_verir():
    oturum = _SahteOturum("<html>şablon değişti</html>")
    with pytest.raises(RuntimeError, match="hiç 'Finansal Bülten' bağlantısı"):
        _bulten_listesi(session=oturum)


def test_seri_cek_bilinmeyen_metrik_hata_verir():
    with pytest.raises(RuntimeError, match="Bilinmeyen tabgida_metrik"):
        seri_cek(tabgd_seri(tabgida_metrik="olmayan"))


def test_seri_cek_fis_sayisi_yalniz_4_ceyrek_bultenlerini_kullanir(monkeypatch):
    import ingest.tabgida as tabgida_modul

    monkeypatch.setattr(
        tabgida_modul, "_bulten_listesi",
        lambda session=None: [
            {"yil": 2025, "ceyrek": 4, "url": "http://x/fy.pdf"},
            {"yil": 2025, "ceyrek": 2, "url": "http://x/2c.pdf"},
        ],
    )
    icerikler = {"http://x/fy.pdf": "Fiş sayısı ('000) 207.648 247.196 %19,0 207.648 247.196 %19,0\n"}
    monkeypatch.setattr(
        tabgida_modul, "_belge_metnini_getir",
        lambda url, onbellek, session=None, donem="": icerikler[url],
    )
    df = seri_cek(tabgd_seri(tabgida_metrik="fis-sayisi"))
    assert list(df["date"]) == ["2025-10-01"]
    assert list(df["value"]) == [247196.0]


def _sahte_bultenler(monkeypatch, bultenler, icerikler):
    import ingest.tabgida as tabgida_modul

    monkeypatch.setattr(tabgida_modul, "_bulten_listesi", lambda session=None: bultenler)
    monkeypatch.setattr(
        tabgida_modul, "_belge_metnini_getir",
        lambda url, onbellek, session=None, donem="": icerikler[url],
    )


def test_seri_cek_restoran_cumlesi_bulunamayan_bultende_hata_verir(monkeypatch):
    """Bilinen boşluk listesinde OLMAYAN bir bültende cümle eşleşmezse çeyrek
    sessizce atlanmamalı (27 Kasım 2026: 3Ç26 tam böyle kayboluyordu)."""
    _sahte_bultenler(
        monkeypatch,
        [
            {"yil": 2025, "ceyrek": 1, "url": "http://x/1c25.pdf"},
            {"yil": 2025, "ceyrek": 2, "url": "http://x/2c25.pdf"},
        ],
        {
            "http://x/1c25.pdf": "restoran portföyümüz 1.854 lokasyona ulaştı.\n",
            "http://x/2c25.pdf": "Bu çeyrekte 40 yeni restoran açtık.\n",
        },
    )
    with pytest.raises(RuntimeError, match="2025 2Ç Finansal Bülten'inde toplam restoran"):
        seri_cek(tabgd_seri())


def test_seri_cek_toplam_bildirmeyen_bilinen_ceyrekleri_atlar(monkeypatch):
    """3Ç24 ve 1Ç26 bültenleri canlı ölçümde toplam bildirmiyor
    (`TOPLAM_BILDIRMEYEN_CEYREKLER`) — kalıcı boşluk, hata değil."""
    from ingest.tabgida import TOPLAM_BILDIRMEYEN_CEYREKLER

    assert TOPLAM_BILDIRMEYEN_CEYREKLER == {(2024, 3), (2026, 1)}
    _sahte_bultenler(
        monkeypatch,
        [
            {"yil": 2024, "ceyrek": 3, "url": "http://x/3c24.pdf"},
            {"yil": 2026, "ceyrek": 1, "url": "http://x/1c26.pdf"},
            {"yil": 2026, "ceyrek": 2, "url": "http://x/2c26.pdf"},
        ],
        {
            "http://x/3c24.pdf": "3. çeyrekte 76 yeni restoran açtık\n",
            "http://x/1c26.pdf": "İlk çeyrekte 38 yeni restoran açarken\n",
            "http://x/2c26.pdf": "toplam restoran sayımızı 2.100'e ulaştırdık.\n",
        },
    )
    df = seri_cek(tabgd_seri())
    assert list(df["date"]) == ["2026-04-01"]
    assert list(df["value"]) == [2100.0]


def test_seri_cek_fis_satiri_okunamayan_fy_bulteninde_hata_verir(monkeypatch):
    _sahte_bultenler(
        monkeypatch,
        [{"yil": 2025, "ceyrek": 4, "url": "http://x/fy25.pdf"}],
        {"http://x/fy25.pdf": "Fiş sayısı 4Ç'te 51,3 milyona ulaştı.\n"},
    )
    with pytest.raises(RuntimeError, match=r"2025 4Ç \(FY 2025\) Finansal Bülten'inde fiş sayısı"):
        seri_cek(tabgd_seri(tabgida_metrik="fis-sayisi"))


def test_seri_cek_okunamayan_bulten_hatasi_seriyi_durdurur(monkeypatch):
    """Bozuk bülten artık atlanmaz: hata yukarı çıkar, `seriyi_yaz`
    çağrılmaz, mevcut CSV korunur."""
    import ingest.tabgida as tabgida_modul

    monkeypatch.setattr(
        tabgida_modul, "_bulten_listesi",
        lambda session=None: [{"yil": 2024, "ceyrek": 1, "url": "http://x/bozuk.pdf"}],
    )

    def _bozuk(url, onbellek, session=None, donem=""):
        raise RuntimeError(f"TAB Gıda {donem} Finansal Bülten PDF değil: {url}")

    monkeypatch.setattr(tabgida_modul, "_belge_metnini_getir", _bozuk)
    with pytest.raises(RuntimeError, match="2024 1Ç Finansal Bülten PDF değil"):
        seri_cek(tabgd_seri())


def test_restoran_sayisini_ayikla_restoran_agimizi_kalibi():
    """3Ç 2026 canlı metni (27 Kasım 2026): "restoran ağımızı 2.164'e
    ulaştırdık" — eski desen bunu tanımıyor, çeyrek sessizce atlanıyordu."""
    metin = (
        "toplam 151 yeni restoran\naçılışı gerçekleştirerek restoran ağımızı "
        "2.164'e ulaştırdık. Piyasa\n"
    )
    assert restoran_sayisini_ayikla(metin) == 2164.0


class _BelgeYaniti:
    def __init__(self, icerik, kod=200):
        self.content = icerik
        self.status_code = kod

    def raise_for_status(self):
        if self.status_code >= 400:
            hata = requests.HTTPError(f"HTTP {self.status_code}")
            hata.response = self
            raise hata


def _belge_oturumu(yanit):
    oturum = _SahteOturum("")
    oturum.get = lambda url, headers=None, timeout=None: yanit
    return oturum


def test_belge_metnini_getir_pdf_imzasi_olmayan_yaniti_reddeder():
    """CMS yolu tutmazsa sunucu 200 döndürüp ana sayfaya YÖNLENDİRİR
    (canlı ölçüm: 36.378 bayt `text/html`); bu PDF değildir → hata."""
    import ingest.tabgida as tabgida_modul

    oturum = _belge_oturumu(_BelgeYaniti(b"<!doctype html><html><title>TAB Gida</title>"))
    with pytest.raises(RuntimeError, match="2025 3Ç Finansal Bülten PDF değil"):
        tabgida_modul._belge_metnini_getir("http://x/a.pdf", {}, session=oturum, donem="2025 3Ç")


def test_belge_metnini_getir_404_hata_verir():
    """404 = bizim kurduğumuz yanlış yol; kırmızıyı hak eder (atlanmaz)."""
    import ingest.tabgida as tabgida_modul
    from ingest.run import erisilemez_mi

    oturum = _belge_oturumu(_BelgeYaniti(b"yok", kod=404))
    with pytest.raises(RuntimeError, match=r"2025 3Ç Finansal Bülten indirilemedi \(HTTP 404\)") as bilgi:
        tabgida_modul._belge_metnini_getir("http://x/a.pdf", {}, session=oturum, donem="2025 3Ç")
    assert erisilemez_mi(bilgi.value) is False


def test_belge_metnini_getir_503_kaynak_sorunu_sayilir():
    import ingest.tabgida as tabgida_modul
    from ingest.run import erisilemez_mi

    oturum = _belge_oturumu(_BelgeYaniti(b"", kod=503))
    with pytest.raises(RuntimeError, match="HTTP 503") as bilgi:
        tabgida_modul._belge_metnini_getir("http://x/a.pdf", {}, session=oturum, donem="2025 3Ç")
    assert erisilemez_mi(bilgi.value) is True


def test_oturum_paylasilan_oturuma_waf_adaptorunu_takar():
    """`ingest.run` paylaşılan `requests.Session` verir; onun `https://`
    bağdaştırıcısı varsayılan şifre listesiyle WAF'a takılır. Bu kaynak
    için sunucu önekli bağdaştırıcı değiştirilir, diğer kaynaklar etkilenmez."""
    from ingest.tabgida import _WafAdapter, _oturum

    oturum = requests.Session()
    diger = oturum.get_adapter("https://ornek.gov.tr")
    assert _oturum(oturum) is oturum
    assert isinstance(oturum.get_adapter("https://www.tabgida.com.tr/x"), _WafAdapter)
    assert oturum.get_adapter("https://ornek.gov.tr") is diger


def test_belge_metnini_getir_baglanti_hatasi_zincirlenir_ve_erisilemez_sayilir():
    """Bağlantı hatası artık `None` ile yutulmaz (çeyrek sessizce düşerdi):
    `from` ile zincirlenir, `erisilemez_mi` kaynak sorunu sayar → koşu
    yeşil, CSV korunur."""
    import ingest.tabgida as tabgida_modul
    from ingest.run import erisilemez_mi

    class _Hata(_SahteOturum):
        def get(self, url, headers=None, timeout=None, **kwargs):
            raise requests.ConnectionError("WAF el sıfırladı")

    with pytest.raises(RuntimeError, match="2024 4Ç Finansal Bülten indirilemedi") as bilgi:
        tabgida_modul._belge_metnini_getir("http://x/a.pdf", {}, session=_Hata(""), donem="2024 4Ç")
    assert erisilemez_mi(bilgi.value) is True


def test_gecerli_metrikler_iki_seriyi_kapsar():
    assert GECERLI_METRIKLER == {"restoran-sayisi", "fis-sayisi"}


def test_belge_metnini_getir_metin_katmani_olmayan_pdf_hata_verir(monkeypatch):
    """PDF var ama metin vermiyor (görsel/taranmış) → okunamayan bülten."""
    import ingest.tabgida as tabgida_modul

    class _SahtePdf:
        pages = [SimpleNamespace(extract_text=lambda: None)]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tabgida_modul.pdfplumber, "open", lambda akis: _SahtePdf())
    oturum = _belge_oturumu(_BelgeYaniti(b"%PDF-1.7 ..."))
    with pytest.raises(RuntimeError, match="2026 3Ç Finansal Bülten PDF'inde metin katmanı yok"):
        tabgida_modul._belge_metnini_getir("http://x/a.pdf", {}, session=oturum, donem="2026 3Ç")
