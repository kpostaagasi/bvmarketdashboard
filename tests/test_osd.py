from datetime import date

import pytest

from ingest.osd import (
    ASGARI_FIRMA_SAYISI,
    ay_toplamlari,
    bulten_baglantilari,
    cekilecek_bultenler,
    dogrula,
    firma_adini_normalize,
    firma_aylik_noktalari,
    sayi_parse,
)

# --- İndeks kazıma ---

INDEKS_HTML = """
<a href="/saved-files\\PDF\\2023\\01\\16\\Otomotiv_Sanayii_Uretim_Bulteni_2022.12.pdf">2022</a>
<a href="/saved-files\\PDF\\2024\\01\\14\\Otomotiv_Sanayii_Uretim_Bulteni-2023.12.pdf">2023</a>
<a href="/saved-files\\PDF\\2026\\08\\17\\Otomotiv_Sanayii_Uretim_Bulteni-2026.07.pdf">2026</a>
<a href="/saved-files\\PDF\\2010\\01\\01\\Üretim Bülteni _2009.pdf">2009</a>
"""


def test_bulten_baglantilari_tire_ve_alt_cizgiyi_kabul_eder():
    """2022 alt çizgi, 2023+ tire kullanıyor — ikisi de bulunmalı."""
    b = bulten_baglantilari(INDEKS_HTML)
    assert set(b) == {"2022.12", "2023.12", "2026.07"}


def test_bulten_baglantilari_ters_boluyu_duzeltir():
    b = bulten_baglantilari(INDEKS_HTML)
    assert b["2026.07"] == (
        "https://www.osd.org.tr/saved-files/PDF/2026/08/17/"
        "Otomotiv_Sanayii_Uretim_Bulteni-2026.07.pdf"
    )


def test_bulten_baglantilari_eski_bicimi_yok_sayar():
    """`Üretim Bülteni _2009.pdf` farklı format; kapsam dışı."""
    assert "2009" not in bulten_baglantilari(INDEKS_HTML)


def test_bulten_baglantilari_eski_adla_guncel_yil_yuklenirse_yukselir():
    """Eski ad şablonu yalnızca 2006–2021 için bilinen muafiyet; güncel bir
    yılın bülteni o adla yüklenirse sessizce atlanmamalı."""
    html = INDEKS_HTML + (
        '<a href="/saved-files\\PDF\\2026\\11\\16\\'
        'Üretim Bülteni _2026.pdf">2026</a>'
    )
    with pytest.raises(RuntimeError, match="tanınmayan bülten.*Üretim Bülteni _2026.pdf"):
        bulten_baglantilari(html)


def test_bulten_baglantilari_eski_adla_son_muaf_yili_kabul_eder():
    """`Üretim Bülteni _2021.pdf` canlı indekste var; muaf kalmalı."""
    html = INDEKS_HTML + (
        '<a href="/saved-files\\PDF\\2022\\02\\02\\'
        'Üretim Bülteni _2021.pdf">2021</a>'
    )
    assert set(bulten_baglantilari(html)) == {"2022.12", "2023.12", "2026.07"}


def test_bulten_baglantilari_hicbiri_yoksa_yukselir():
    """Site yapısı değişirse sessizce boş dönmemeli."""
    with pytest.raises(RuntimeError, match="bülten bağlantısı"):
        bulten_baglantilari("<html><body>hiçbir şey</body></html>")


def test_bulten_baglantilari_taninmayan_bulten_adinda_yukselir():
    """Kısmi bağlantı eşleşmesi: yeni bir ad şablonuyla yüklenen bülten
    sessizce atlanmamalı — o dönemin ayları eksik kalırdı."""
    html = INDEKS_HTML + (
        '<a href="/saved-files\\PDF\\2026\\11\\16\\'
        'Otomotiv_Sanayii_Uretim_Bulteni-2026.10-v2.pdf">Ekim</a>'
    )
    with pytest.raises(RuntimeError, match="tanınmayan bülten.*2026.10-v2"):
        bulten_baglantilari(html)


def test_bulten_baglantilari_saved_files_disindaki_pdfi_yok_sayar():
    """Sayfa altbilgisindeki tüzük PDF'i (`/pdf/OSD_TUZUK…`) bülten değil."""
    html = INDEKS_HTML + '<a href="/pdf/OSD_TUZUK310826.pdf">Tüzük</a>'
    assert set(bulten_baglantilari(html)) == {"2022.12", "2023.12", "2026.07"}


def test_bulten_baglantilari_yeniden_yukleme_sonekini_kabul_eder():
    """OSD düzeltilmiş bülteni `…-2026.09_1.pdf` adıyla yeniden yüklüyor.
    Sonek tanınmadığı için 2026'nın tek bülteni eşleşmedi ve 31 seri
    2025-12'de kaldı (ölçüldü 2026-11-13: 317 gün gecikme)."""
    html = (
        '<a href="/saved-files\\PDF\\2026\\10\\15\\'
        'Otomotiv_Sanayii_Uretim_Bulteni-2026.09_1.pdf">Eylül</a>'
    )
    assert bulten_baglantilari(html) == {
        "2026.09": "https://www.osd.org.tr/saved-files/PDF/2026/10/15/"
                   "Otomotiv_Sanayii_Uretim_Bulteni-2026.09_1.pdf"
    }


# --- Bülten seçimi ---

BAGLANTILAR = {
    "2022.12": "u1", "2023.12": "u2", "2024.12": "u3",
    "2025.12": "u4", "2026.07": "u5",
}


def test_cekilecek_bultenler_aralik_ve_guncel_secer():
    secilen = cekilecek_bultenler(BAGLANTILAR, date(2026, 9, 4))
    assert secilen == ["2022.12", "2023.12", "2024.12", "2025.12", "2026.07"]


def test_cekilecek_bultenler_gecmis_yil_siniri_uygular():
    """VARSAYILAN_GECMIS_YIL=5 ise 2021 ve öncesi alınmaz."""
    genis = dict(BAGLANTILAR, **{"2019.12": "u0", "2020.12": "u0b"})
    secilen = cekilecek_bultenler(genis, date(2026, 9, 4))
    assert "2019.12" not in secilen and "2020.12" not in secilen


def test_cekilecek_bultenler_ocakta_tekrar_secmez():
    """Ocak'ta en güncel bülten önceki yılın Aralık'ıdır (2025.12); bu, yıl
    başına bir kez seçilir ve Aralık listesiyle çakışıp tekrar üretmez."""
    ocak = {"2024.12": "u3", "2025.12": "u4"}
    secilen = cekilecek_bultenler(ocak, date(2026, 1, 10))
    assert secilen == ["2024.12", "2025.12"]


def test_cekilecek_bultenler_gecmis_yilda_aralik_yoksa_yukselir():
    """Geçmiş bir yılın en güncel bülteni `.11` ise ve sonraki yıl varsa
    2024-12 iki tarafında veri olan bir deliktir. Önceki sürüm `.11`'i
    sessizce seçip Aralık'ı düşürüyordu."""
    baglantilar = {
        "2022.12": "u1", "2023.12": "u2", "2024.11": "u3",
        "2025.12": "u4", "2026.07": "u5",
    }
    with pytest.raises(RuntimeError, match="2024 yılının Aralık belgesi yok"):
        cekilecek_bultenler(baglantilar, date(2026, 9, 4))


def test_cekilecek_bultenler_aradaki_yil_yoksa_yukselir():
    baglantilar = {"2022.12": "u1", "2023.12": "u2", "2025.12": "u4", "2026.07": "u5"}
    with pytest.raises(RuntimeError, match="2024 yılı için belge yok"):
        cekilecek_bultenler(baglantilar, date(2026, 9, 4))


def test_cekilecek_bultenler_son_yilin_araligi_henuz_yayimlanmamissa_gecer():
    """Ocak başında önceki yılın Aralık bülteni henüz yok: en güncel `.11`
    meşrudur (henüz yayımlanmadı), delik değil."""
    secilen = cekilecek_bultenler({"2024.12": "u3", "2025.11": "u4"}, date(2026, 1, 10))
    assert secilen == ["2024.12", "2025.11"]


def test_cekilecek_bultenler_pencere_basindaki_eksik_yil_delik_sayilmaz():
    """2021 bülteni eski ad şablonunda olduğu için okunmuyor; seri 2022'de
    başlar — iki tarafında veri olmayan bu boşluk delik değildir."""
    baglantilar = {"2022.12": "u1", "2023.12": "u2", "2024.12": "u3",
                   "2025.12": "u4", "2026.10": "u5"}
    secilen = cekilecek_bultenler(baglantilar, date(2026, 11, 27))
    assert secilen == ["2022.12", "2023.12", "2024.12", "2025.12", "2026.10"]


# --- Ad ve sayı ayrıştırma ---

def test_firma_adini_normalize_null_bayti_temizler():
    """Eski PDF'lerde font kodlaması Türkçe karakterlerde \\x00 sızdırıyor."""
    assert firma_adini_normalize("T\x00pler") == "Tpler"


def test_firma_adini_normalize_satir_sonu_ve_bosluk_temizler():
    assert firma_adini_normalize("  FORD\nOTOSAN  ") == "FORD OTOSAN"


def test_sayi_parse_turkce_binlik_ayraci():
    assert sayi_parse("36.548") == 36548.0


def test_sayi_parse_bos_ve_tire_none_doner():
    assert sayi_parse("-") is None
    assert sayi_parse("") is None
    assert sayi_parse(None) is None


def test_sayi_parse_okunamayan_hucrede_yukselir():
    """Dolu ama sayı olmayan hücre "-" gibi sessizce atlanmamalı."""
    with pytest.raises(ValueError, match="okunamadı: '12.3a4'"):
        sayi_parse("12.3a4")


# --- Nokta çıkarma ---

def _tablo(*satirlar):
    """s6 biçimi: 14 sütun (tip/firma + 12 ay + toplam)."""
    basliklar = ["Tipler\nTypes"] + [f"AY{i}" for i in range(1, 13)] + ["TOPLAM"]
    return [basliklar, *satirlar]


def _firma_satiri(ad, *aylar):
    hucreler = list(aylar) + ["-"] * (12 - len(aylar))
    return [ad, *hucreler, "-"]


def test_firma_aylik_noktalari_firma_satirlarini_okur():
    tablo = _tablo(
        _firma_satiri("FORD OTOSAN", "100", "200"),
        ["Pay / Share %", *["1"] * 13],
        _firma_satiri("TOFAŞ", "10", "20"),
        ["Pay / Share %", *["1"] * 13],
        ["OTOMOBİL Toplam / Pass.Car Total", *["110"] * 13],
        ["Toplam Pay / Total Share", *["100"] * 13],
    )
    noktalar = firma_aylik_noktalari([tablo], 2026)
    assert ("FORD OTOSAN", "2026-01-01", 100.0) in noktalar
    assert ("FORD OTOSAN", "2026-02-01", 200.0) in noktalar
    assert ("TOFAŞ", "2026-02-01", 20.0) in noktalar


def test_firma_aylik_noktalari_alt_toplam_satirlarini_atlar():
    tablo = _tablo(
        _firma_satiri("FORD OTOSAN", "100"),
        ["Pay / Share %", *["1"] * 13],
        ["OTOMOBİL Toplam / Pass.Car Total", *["100"] * 13],
        ["Toplam Pay / Total Share", *["100"] * 13],
        ["", *[""] * 13],
    )
    adlar = {n[0] for n in firma_aylik_noktalari([tablo], 2026)}
    assert adlar == {"FORD OTOSAN"}


def test_firma_aylik_noktalari_ayni_firmayi_bolumler_arasi_toplar():
    """Bir firma birden çok araç tipi bölümünde görünür; toplanmalı."""
    t1 = _tablo(_firma_satiri("FORD OTOSAN", "100"))
    t2 = _tablo(_firma_satiri("FORD OTOSAN", "50"))
    noktalar = firma_aylik_noktalari([t1, t2], 2026)
    assert noktalar == [("FORD OTOSAN", "2026-01-01", 150.0)]


def test_firma_aylik_noktalari_okunamayan_ay_hucresinde_yukselir():
    tablo = _tablo(_firma_satiri("KARSAN", "5", "#", "7"))
    with pytest.raises(ValueError, match="Üretim Bülteni — KARSAN 2026-02: .*okunamadı: '#'"):
        firma_aylik_noktalari([tablo], 2026)


def test_firma_aylik_noktalari_bos_ayi_atlar():
    tablo = _tablo(_firma_satiri("KARSAN", "-", "5"))
    noktalar = firma_aylik_noktalari([tablo], 2026)
    assert noktalar == [("KARSAN", "2026-02-01", 5.0)]


# --- Öz-doğrulama ---

def _s2_tablosu(*satirlar):
    basliklar = ["FİRMALAR"] + [f"S{i}" for i in range(1, 17)] + ["TOPLAM Total", "%"]
    return [basliklar, *satirlar]


def _s2_satiri(ad, toplam):
    return [ad, *["-"] * 16, toplam, "-"]


def test_ay_toplamlari_toplam_sutununu_okur():
    tablo = _s2_tablosu(
        _s2_satiri("FORD OTOSAN", "36.548"),
        _s2_satiri("TOPLAM / TOTAL", "105.725"),
    )
    assert ay_toplamlari(tablo) == {"FORD OTOSAN": 36548.0}


# dogrula testleri ASGARI_FIRMA_SAYISI (13) eşiğini geçmek için 13 firmalık
# tam bir TOPLAM sözlüğü/nokta listesi kullanır — aksi halde yeni sayı
# kontrolü, testin asıl kontrol ettiği duruma ulaşılmadan devreye girer.
_13_FIRMA = [f"FIRMA{i:02d}" for i in range(1, 12)] + ["FORD OTOSAN", "TOFAŞ"]


def _tam_toplamlar(**gecersiz):
    d = {ad: 1000.0 for ad in _13_FIRMA}
    d.update(gecersiz)
    return d


def _tam_noktalar(ay_tarihi, haric=(), **gecersiz):
    degerler = {ad: 1000.0 for ad in _13_FIRMA}
    degerler.update(gecersiz)
    return [
        (ad, ay_tarihi, deger) for ad, deger in degerler.items()
        if ad not in haric
    ]


def test_dogrula_tutan_toplamda_sessiz():
    ay = "2026-07-01"
    dogrula(_tam_noktalar(ay), _tam_toplamlar(), ay)


def test_dogrula_tutmayan_toplamda_yukselir():
    """Şablon değişirse sessizce eksik veri üretmek yerine kırılmalı."""
    ay = "2026-07-01"
    noktalar = _tam_noktalar(ay, **{"FORD OTOSAN": 30000.0})
    with pytest.raises(RuntimeError, match="FORD OTOSAN"):
        dogrula(noktalar, _tam_toplamlar(), ay)


def test_dogrula_eksik_firmada_yukselir():
    ay = "2026-07-01"
    noktalar = _tam_noktalar(ay, haric=("TOFAŞ",))
    with pytest.raises(RuntimeError, match="TOFAŞ"):
        dogrula(noktalar, _tam_toplamlar(), ay)


def test_dogrula_bos_toplamlarda_yukselir():
    """OSD 2. sayfa yapısı değişip `toplamlar` boş dönerse (ör. sütun
    kayması sonucu `sayi_parse` hepsi için None dönerse), dilimin tek
    güvenlik ağı sessizce no-op'a düşmemeli."""
    with pytest.raises(RuntimeError, match=str(ASGARI_FIRMA_SAYISI)):
        dogrula([("FORD OTOSAN", "2026-07-01", 100.0)], {}, "2026-07-01")


def test_dogrula_eksik_firma_sayisinda_yukselir():
    """Beklenenden az firma (ör. 5) bulunması da şablon değişikliği
    sinyalidir — yalnızca tamamen boş sözlük değil."""
    ay = "2026-07-01"
    az_toplamlar = {ad: 1000.0 for ad in _13_FIRMA[:5]}
    with pytest.raises(RuntimeError, match=str(ASGARI_FIRMA_SAYISI)):
        dogrula(_tam_noktalar(ay), az_toplamlar, ay)


# --- Ağ kabuğu: seri_cek ---


def _okumaya_cevir(sahte):
    """Noktalar döndüren sahte ayrıştırıcıyı `(noktalar, görülen adlar)`
    sözleşmesine sarar; görülen adlar noktalardaki firmalardır."""
    def sarili(*args):
        noktalar = sahte(*args)
        return noktalar, frozenset(n[0] for n in noktalar)
    return sarili

def test_seri_cek_onbellegi_paylasir(monkeypatch):
    """13 seri aynı beş PDF'i paylaşır; ikinci seri hiç indirmemeli."""
    from types import SimpleNamespace

    from ingest import osd

    indirilenler = []

    def sahte_indir(url, session=None):
        indirilenler.append(url)
        return b"sahte-pdf"

    def sahte_ayristir(baytlar, anahtar):
        return [("FORD OTOSAN", "2026-01-01", 100.0),
                ("TOFAŞ", "2026-01-01", 50.0)]

    monkeypatch.setattr(osd, "_indeks_cek", lambda session=None: {"2026.07": "u"})
    monkeypatch.setattr(osd, "_pdf_indir", sahte_indir)
    monkeypatch.setattr(osd, "_bulteni_ayristir", _okumaya_cevir(sahte_ayristir))

    onbellek: dict = {}
    ford = SimpleNamespace(id="otomotiv/ford-otosan", osd_firma="FORD OTOSAN",
                           start_date=None)
    tofas = SimpleNamespace(id="otomotiv/tofas", osd_firma="TOFAŞ",
                            start_date=None)

    df1 = osd.seri_cek(ford, onbellek=onbellek, bugun=date(2026, 9, 4))
    df2 = osd.seri_cek(tofas, onbellek=onbellek, bugun=date(2026, 9, 4))

    assert len(indirilenler) == 1  # ikinci seri önbellekten
    assert list(df1.columns) == ["date", "value"]
    assert df1["value"].iloc[0] == 100.0
    assert df2["value"].iloc[0] == 50.0


def test_seri_cek_bilinmeyen_firmada_yukselir(monkeypatch):
    """Katalogdaki ad bültende yoksa sessizce boş seri yazılmamalı."""
    from types import SimpleNamespace

    from ingest import osd

    monkeypatch.setattr(osd, "_indeks_cek", lambda session=None: {"2026.07": "u"})
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(
        osd, "_bulteni_ayristir",
        _okumaya_cevir(lambda baytlar, anahtar: [("FORD OTOSAN", "2026-01-01", 100.0)]),
    )

    seri = SimpleNamespace(id="otomotiv/yok", osd_firma="YOK BÖYLE FİRMA",
                           start_date=None)
    with pytest.raises(RuntimeError, match="YOK BÖYLE FİRMA"):
        osd.seri_cek(seri, onbellek={}, bugun=date(2026, 9, 4))


def test_seri_cek_eski_adla_eslesen_noktalari_da_toplar(monkeypatch):
    """Firma OSD'de ad değiştirmiş olabilir (ör. HYUNDAI ASSAN -> HYUNDAI MOTOR
    TÜRKİYE); osd_eski_adlar verilirse eski adla yazılmış noktalar da
    toplanmalı, yoksa o dönem sessizce kaybolur."""
    from types import SimpleNamespace

    from ingest import osd

    def sahte_ayristir(baytlar, anahtar):
        if anahtar == "2025.12":
            return [("HYUNDAI ASSAN", "2025-01-01", 100.0)]
        return [("HYUNDAI MOTOR TÜRKİYE", "2026-01-01", 200.0)]

    monkeypatch.setattr(
        osd, "_indeks_cek",
        lambda session=None: {"2025.12": "u1", "2026.07": "u2"},
    )
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(osd, "_bulteni_ayristir", _okumaya_cevir(sahte_ayristir))

    seri = SimpleNamespace(
        id="otomotiv/hyundai", osd_firma="HYUNDAI MOTOR TÜRKİYE",
        osd_eski_adlar=("HYUNDAI ASSAN",), start_date=None,
    )
    df = osd.seri_cek(seri, onbellek={}, bugun=date(2026, 9, 4))
    assert set(df["date"]) == {"2025-01-01", "2026-01-01"}


def test_seri_cek_bir_bultende_firma_yoksa_o_bulteni_belirterek_yukselir(monkeypatch):
    """Kısmi kayıp — bazı bültenlerde firma var, birinde yoksa — artık sessiz
    geçmemeli; hata mesajı hangi bültende bulunamadığını söylemeli."""
    from types import SimpleNamespace

    from ingest import osd

    def sahte_ayristir(baytlar, anahtar):
        if anahtar == "2025.12":
            return [("BASKA FIRMA", "2025-01-01", 1.0)]  # KARSAN burada yok
        return [("KARSAN", "2026-01-01", 200.0)]

    monkeypatch.setattr(
        osd, "_indeks_cek",
        lambda session=None: {"2025.12": "u1", "2026.07": "u2"},
    )
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(osd, "_bulteni_ayristir", _okumaya_cevir(sahte_ayristir))

    seri = SimpleNamespace(
        id="otomotiv/karsan", osd_firma="KARSAN",
        osd_eski_adlar=None, start_date=None,
    )
    with pytest.raises(RuntimeError, match="2025.12"):
        osd.seri_cek(seri, onbellek={}, bugun=date(2026, 9, 4))


def test_seri_cek_en_guncel_bultende_satir_tumu_tire_ise_yukselmez(monkeypatch):
    """Satırı var ama tüm ayları "-" (ör. Ocak bülteninde hiç üretmemiş
    firma) meşru sıfırdır — firma bültende VARDIR, ingest kırılmamalı.
    Sahte bülten gerçek ayrıştırıcıdan (`firma_aylik_noktalari`) geçer."""
    from types import SimpleNamespace

    from ingest import osd

    def sahte_ayristir(baytlar, anahtar):
        if anahtar == "2025.12":
            tablo = _tablo(_firma_satiri("KARSAN", "120"))
        else:
            tablo = _tablo(_firma_satiri("TOFAŞ", "5000"), _firma_satiri("KARSAN"))
        gorulen: set[str] = set()
        noktalar = firma_aylik_noktalari([tablo], int(anahtar[:4]), gorulen)
        return noktalar, frozenset(gorulen)

    monkeypatch.setattr(
        osd, "_indeks_cek",
        lambda session=None: {"2025.12": "u1", "2026.01": "u2"},
    )
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(osd, "_bulteni_ayristir", sahte_ayristir)

    seri = SimpleNamespace(id="otomotiv/karsan", osd_firma="KARSAN",
                           osd_eski_adlar=None, start_date=None)
    df = osd.seri_cek(seri, onbellek={}, bugun=date(2026, 2, 10))
    assert list(df["date"]) == ["2025-01-01"]


def test_firma_aylik_noktalari_tumu_tire_satiri_gorulenlere_eklenir():
    gorulen: set[str] = set()
    noktalar = firma_aylik_noktalari(
        [_tablo(_firma_satiri("KARSAN"), ["TOPLAM / TOTAL"] + ["-"] * 13)],
        2026, gorulen,
    )
    assert noktalar == []
    assert gorulen == {"KARSAN"}


def test_seri_cek_ayni_bultende_alias_carpismasi_toplanir(monkeypatch):
    """Aynı bültende hem eski hem yeni ad aynı ay için nokta üretirse biri
    diğerini sessizce ezmemeli — TOPLANMALI (100 + 5000 = 5100, 5000 değil)."""
    from types import SimpleNamespace

    from ingest import osd

    def sahte_ayristir(baytlar, anahtar):
        return [
            ("ESKİ AD", "2026-01-01", 100.0),
            ("YENİ AD", "2026-01-01", 5000.0),
        ]

    monkeypatch.setattr(osd, "_indeks_cek", lambda session=None: {"2026.07": "u"})
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(osd, "_bulteni_ayristir", _okumaya_cevir(sahte_ayristir))

    seri = SimpleNamespace(
        id="otomotiv/test", osd_firma="YENİ AD",
        osd_eski_adlar=("ESKİ AD",), start_date=None,
    )
    df = osd.seri_cek(seri, onbellek={}, bugun=date(2026, 9, 4))
    assert df["value"].iloc[0] == 5100.0


def test_seri_cek_baslangic_tarihinden_onceki_bultenler_kontrolden_muaf(monkeypatch):
    """`start_date` verilen bir seri için ondan önceki yılların bültenlerinde
    firma aranmaz — henüz üretime başlamamış bir firma için beklenen durum."""
    from types import SimpleNamespace

    from ingest import osd

    def sahte_ayristir(baytlar, anahtar):
        if anahtar == "2025.12":
            return [("BASKA FIRMA", "2025-01-01", 1.0)]  # YENİ FİRMA henüz yok
        return [("YENİ FİRMA", "2026-01-01", 50.0)]

    monkeypatch.setattr(
        osd, "_indeks_cek",
        lambda session=None: {"2025.12": "u1", "2026.07": "u2"},
    )
    monkeypatch.setattr(osd, "_pdf_indir", lambda url, session=None: b"x")
    monkeypatch.setattr(osd, "_bulteni_ayristir", _okumaya_cevir(sahte_ayristir))

    seri = SimpleNamespace(
        id="otomotiv/yeni-firma", osd_firma="YENİ FİRMA",
        osd_eski_adlar=None, start_date="2026-01-01",
    )
    df = osd.seri_cek(seri, onbellek={}, bugun=date(2026, 9, 4))
    assert list(df["date"]) == ["2026-01-01"]
