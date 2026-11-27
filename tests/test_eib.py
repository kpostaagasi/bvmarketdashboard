"""EİB (Ege İhracatçı Birlikleri) ESÜHMİB aylık ihracat istatistiği istemcisi
testleri."""

from datetime import date
from io import BytesIO
from types import SimpleNamespace

import openpyxl
import pandas as pd
import pytest

import requests

from ingest.eib import (
    AY_ADLARI,
    _dogrula,
    ay_baglantilarini_cikar,
    hedef_ay_linki,
    seri_cek,
    yil_verisini_cikar,
    yillara_ayir,
)


def eib_seri(**kwargs):
    varsayilan = dict(
        id="su-urunleri/toplam-ihracat", eib_kalem="SU ÜRÜNLERİ", eib_olcut="fobusd",
        start_date=None,
    )
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


# --- yillara_ayir / ay_baglantilarini_cikar: HTML ayrıştırma ---


def test_yillara_ayir_h3_basliklariyla_boler():
    icerik = "<p>giriş</p><h3>2026</h3><p>2026 içerik</p><h3>2025</h3><p>2025 içerik</p>"
    sonuc = yillara_ayir(icerik)
    assert sonuc == {"2026": "<p>2026 içerik</p>", "2025": "<p>2025 içerik</p>"}


def test_yillara_ayir_taninmayan_basliktaki_yili_sessizce_kaybetmez():
    """Başlık biçimi değişirse (`<h3 class=..>`) 2026 bloğu bir önceki dilime
    karışıp atılırdı; yükseltilir."""
    icerik = '<h3 class="baslik">2026</h3><p>2026 içerik</p><h3>2025</h3><p>2025 içerik</p>'
    with pytest.raises(RuntimeError, match="2 yıl başlığından yalnızca 1 ayrıştırılabildi"):
        yillara_ayir(icerik)


def test_yillara_ayir_ic_ice_etiketli_basligi_da_yakalar():
    icerik = "<h3><strong>2026</strong></h3><p>x</p><h3>2025</h3><p>y</p>"
    with pytest.raises(RuntimeError, match="tanınmayan"):
        yillara_ayir(icerik)


def test_ay_baglantilarini_cikar_ayni_ay_iki_kez_gecerse_hata():
    """Kasım yanlışlıkla ikinci bir 'Ekim' diye etiketlenirse en yeni ay
    üzerine yazılıp sessizce kaybolurdu."""
    yil_html = (
        '<p><strong>Ekim: </strong> <a href="https://eib.li/K26">EİB Aylık</a></p>'
        '<p><strong>Ekim: </strong> <a href="https://eib.li/S26">EİB Aylık</a></p>'
    )
    with pytest.raises(RuntimeError, match="2026 Ekim ay etiketi aynı yıl diliminde iki kez"):
        ay_baglantilarini_cikar(yil_html, 2026)


def test_ay_baglantilarini_cikar_etiket_ve_url_esler():
    yil_html = (
        '<p><strong>Ağustos: </strong> '
        '<a href="https://eib.li/D339C" target="_blank">EİB Aylık</a>, '
        '<a href="https://eib.li/8BEC7" target="_blank">Türkiye Geneli Aylık</a></p>'
    )
    sonuc = ay_baglantilarini_cikar(yil_html)
    assert sonuc["AĞUSTOS"] == {
        "EİB Aylık": "https://eib.li/D339C",
        "Türkiye Geneli Aylık": "https://eib.li/8BEC7",
    }


def test_ay_baglantilarini_cikar_bozuk_urlu_duzeltir():
    """Kaynakta ölçülen gerçek anomalı: Şubat 2024 `http://https//eib.li/BE6FE`."""
    yil_html = (
        '<p><strong>Şubat: </strong> '
        '<a href="http://https//eib.li/BE6FE" target="_blank">EİB Aylık</a></p>'
    )
    sonuc = ay_baglantilarini_cikar(yil_html)
    assert sonuc["ŞUBAT"]["EİB Aylık"] == "https://eib.li/BE6FE"


def test_ay_baglantilarini_cikar_entity_ve_nbsp_li_etiketi_tanir():
    """Kaynakta ölçülen gerçek biçim (2026-11-27): Eylül/Ekim 2026 etiketleri
    `Eyl&uuml;l:&nbsp;` — eskiden sessizce atlanıyor, panoda Ağustos'ta
    kalınıyordu."""
    yil_html = (
        '<p><strong>Eyl&uuml;l:&nbsp;</strong><a href="https://eib.li/C7998" target="_blank" '
        'rel="noopener">EİB Aylık</a>, <a href="https://eib.li/0AF58" target="_blank" '
        'rel="noopener"> T&uuml;rkiye Geneli Aylık</a></p>\n'
        '<p><strong>Ekim:&nbsp;</strong><a href="https://eib.li/WfC8v" target="_blank" '
        'rel="noopener">EİB Aylık</a></p>'
    )
    sonuc = ay_baglantilarini_cikar(yil_html)
    assert sonuc["EYLÜL"] == {
        "EİB Aylık": "https://eib.li/C7998",
        "Türkiye Geneli Aylık": "https://eib.li/0AF58",
    }
    assert sonuc["EKİM"] == {"EİB Aylık": "https://eib.li/WfC8v"}


def test_ay_baglantilarini_cikar_tanimayan_etikette_hata():
    yil_html = '<p><strong>Eylul: </strong> <a href="https://eib.li/X">EİB Aylık</a></p>'
    with pytest.raises(RuntimeError, match="tanınmayan ay etiketi 'Eylul: '"):
        ay_baglantilarini_cikar(yil_html)


def test_ay_baglantilarini_cikar_ayrismayan_baglantida_hata():
    yil_html = (
        '<p><strong>Ekim: </strong> <a href="https://eib.li/X">EİB Aylık</a>, '
        "<a href='https://eib.li/Y'>EİB Kümülatif</a></p>"
    )
    with pytest.raises(RuntimeError, match="Ekim bağlantılarının bir kısmı ayrıştırılamadı"):
        ay_baglantilarini_cikar(yil_html)


def test_ay_baglantilarini_cikar_b_etiketli_ayda_hata():
    """Kasım `<strong>` yerine `<b>` ile yazılırsa ay bloğu düzenli ifadeye
    hiç girmez; Ekim'de kalınıp Kasım "henüz yayımlanmadı" sanılırdı."""
    yil_html = (
        '<p><strong>Ekim:&nbsp;</strong><a href="https://eib.li/E26">EİB Aylık</a></p>\n'
        '<p><b>Kasım:&nbsp;</b><a href="https://eib.li/K26">EİB Aylık</a></p>'
    )
    with pytest.raises(RuntimeError, match="2026 diliminde ay bloğu olarak ayrıştırılamayan içerik var"):
        ay_baglantilarini_cikar(yil_html, 2026)


def test_ay_baglantilarini_cikar_oznitelikli_strong_ayda_hata():
    yil_html = (
        '<p><strong>Ekim: </strong><a href="https://eib.li/E26">EİB Aylık</a></p>'
        '<p><strong style="x">Kasım: </strong><a href="https://eib.li/K26">EİB Aylık</a></p>'
    )
    with pytest.raises(RuntimeError, match=r"2026 diliminde .*\(1 <strong>, 1 bağlantı; 1 ay okundu\)"):
        ay_baglantilarini_cikar(yil_html, 2026)


def test_ay_baglantilarini_cikar_metinsiz_bos_baglantiyi_yok_sayar():
    """Kaynakta ölçülen gerçek biçim (2024 dilimi, 2026-11-27): ay bloğunun
    önünde metinsiz `<a href=…> </a>` — veri taşımaz, hata sayılmaz."""
    yil_html = (
        '<p><a href="https://eib.li/DA29B" target="_blank"> </a> '
        '<strong>Mayıs: </strong> <a href="https://eib.li/M24">EİB Aylık</a></p>'
    )
    assert ay_baglantilarini_cikar(yil_html, 2024) == {"MAYIS": {"EİB Aylık": "https://eib.li/M24"}}


# --- hedef_ay_linki: cari yıl en son ay, geçmiş yıl Aralık ---


def test_hedef_ay_linki_cari_yilda_en_son_ayi_secer():
    ay_linkleri = {
        "OCAK": {"EİB": "u1"},
        "ŞUBAT": {"EİB Aylık": "u2"},
        "AĞUSTOS": {"EİB Aylık": "u3"},
    }
    ay, url = hedef_ay_linki(2026, ay_linkleri, date(2026, 9, 18))
    assert (ay, url) == ("AĞUSTOS", "u3")


def test_hedef_ay_linki_gecmis_yilda_araligi_secer():
    ay_linkleri = {"OCAK": {"EİB Aylık": "u1"}, "ARALIK": {"EİB Aylık": "u12"}}
    ay, url = hedef_ay_linki(2025, ay_linkleri, date(2026, 9, 18))
    assert (ay, url) == ("ARALIK", "u12")


def test_hedef_ay_linki_gecmis_yilda_aralik_yoksa_hata():
    ay_linkleri = {"OCAK": {"EİB": "u1"}, "KASIM": {"EİB Aylık": "u11"}}
    with pytest.raises(RuntimeError, match="2025 için ARALIK bağlantısı yok \\(en son KASIM\\)"):
        hedef_ay_linki(2025, ay_linkleri, date(2026, 9, 18))


def test_hedef_ay_linki_yeni_biten_yilin_araligi_henuz_yayimlanmadiysa_son_aya_duser():
    """Henüz yayımlanmadı: Ocak'ta geçen yılın Aralık dosyası gelmemiş olabilir."""
    ay_linkleri = {"OCAK": {"EİB": "u1"}, "KASIM": {"EİB Aylık": "u11"}}
    assert hedef_ay_linki(2026, ay_linkleri, date(2027, 1, 10)) == ("KASIM", "u11")


def test_hedef_ay_linki_aralik_toleransi_bitince_hata():
    ay_linkleri = {"KASIM": {"EİB Aylık": "u11"}}
    with pytest.raises(RuntimeError, match="ARALIK bağlantısı yok"):
        hedef_ay_linki(2026, ay_linkleri, date(2027, 4, 1))


def test_hedef_ay_linki_ocakta_tek_eib_etiketini_kabul_eder():
    ay, url = hedef_ay_linki(2026, {"OCAK": {"EİB": "u1", "TÜRKİYE GENELİ": "u2"}}, date(2026, 1, 15))
    assert (ay, url) == ("OCAK", "u1")


def test_hedef_ay_linki_bos_yilda_none_doner():
    assert hedef_ay_linki(2026, {}, date(2026, 9, 18)) is None


def test_hedef_ay_linki_eib_aylik_yoksa_hata():
    with pytest.raises(RuntimeError, match="EİB Aylık"):
        hedef_ay_linki(2026, {"OCAK": {"TÜRKİYE GENELİ": "u2"}}, date(2026, 1, 15))


# --- yil_verisini_cikar: XLSX bütünlük testi ---


def _yillik_dosya_baytlari(satirlar, sayfa_adi="GTIP ULKE GB TARIH"):
    """`satirlar`: [(ay, ürün_grubu, alt_grup1, agirlik_kg, fobusd)] listesi
    ile gerçekçi ama minimal bir yıllık bülten üretir."""
    kitap = openpyxl.Workbook()
    sayfa = kitap.active
    sayfa.title = sayfa_adi
    sayfa.append(["Aylar", "ürün grubu", "alt grup 1 ", "alt grup 2", "GTIP", "GTIPAD", "ULKEAD", "AGIRLIK", "FOBUSD", "FOBEUR"])
    for ay, urun, alt1, agirlik, fob in satirlar:
        sayfa.append([ay, urun, alt1, "alt2", "000000", "ürün adı", "ÜLKE", agirlik, fob, fob * 0.9])
    arabellek = BytesIO()
    kitap.save(arabellek)
    return arabellek.getvalue()


def _ay_satirlari(ay):
    """Bir ayın, izlenen her kalemi taşıyan gerçekçi minimal satırları."""
    return [
        (ay, "SU ÜRÜNLERİ", "LEVREK", 1000.0, 5000.0),
        (ay, "SU ÜRÜNLERİ", "ÇİPURA", 500.0, 2000.0),
        (ay, "SU ÜRÜNLERİ", "TÜRK SOMONU", 40.0, 400.0),
        (ay, "SU ÜRÜNLERİ", "ALABALIK", 60.0, 600.0),
        (ay, "SU ÜRÜNLERİ", "KAYA LEVREĞİ", 10.0, 100.0),
        (ay, "SU ÜRÜNLERİ", "DİĞER SU ÜRÜNLERİ", 100.0, 300.0),
        (ay, "SU ÜRÜNLERİ", "ORKİNOS", 20.0, 200.0),
        (ay, "KANATLI", "KANATLI", 200.0, 900.0),
        (ay, "YUMURTA", "YUMURTA", 50.0, 400.0),
        (ay, "SÜT VE SÜT ÜRÜNLERİ", "SÜT", 10.0, 100.0),
        (ay, "SOSİS VE BENZERİ ÜRÜNLER (KIRMIZI ET VE KANATLI)", "SOSİS", 5.0, 50.0),
        (ay, "BAL", "BAL", 3.0, 30.0),
        (ay, "DİĞER", "DİĞER", 2.0, 20.0),
        (ay, "CANLI HAYVAN", "CANLI HAYVAN", 1.0, 10.0),
        (ay, "KIRMIZI ET VE SAKATAT", "KIRMIZI ET", 0.5, 5.0),
    ]


_TEMEL_SATIRLAR = _ay_satirlari("OCAK")


def test_yil_verisini_cikar_su_urunleri_kalan_diger_urunlere_katlanir():
    """5 adlandırılmış ürün dışındaki her şey (alt grubu ne olursa olsun,
    Orkinos dahil) TOPLAM − 5 üründen hesaplanan DİĞER SU ÜRÜNLERİ'nde toplanır."""
    noktalar = yil_verisini_cikar(_yillik_dosya_baytlari(_TEMEL_SATIRLAR), 2025, "OCAK")
    assert noktalar[("LEVREK", "fobusd")]["2025-01-01"] == pytest.approx(5000.0)
    assert noktalar[("ÇİPURA", "fobusd")]["2025-01-01"] == pytest.approx(2000.0)
    assert noktalar[("DİĞER SU ÜRÜNLERİ", "fobusd")]["2025-01-01"] == pytest.approx(500.0)
    assert noktalar[("SU ÜRÜNLERİ", "fobusd")]["2025-01-01"] == pytest.approx(8600.0)


def test_yil_verisini_cikar_agirligi_kg_dan_tona_cevirir():
    noktalar = yil_verisini_cikar(_yillik_dosya_baytlari(_TEMEL_SATIRLAR), 2025, "OCAK")
    assert noktalar[("LEVREK", "agirlik")]["2025-01-01"] == pytest.approx(1.0)


def test_yil_verisini_cikar_hayvansal_toplami_gruplarin_toplamidir():
    noktalar = yil_verisini_cikar(_yillik_dosya_baytlari(_TEMEL_SATIRLAR), 2025, "OCAK")
    assert noktalar[("HAYVANSAL_TOPLAM", "fobusd")]["2025-01-01"] == pytest.approx(1515.0)


def test_yil_verisini_cikar_sayfa_adi_farkli_olsa_da_baslikla_bulunur():
    """Sayfa adı yıldan yıla değişiyor (2024: 'Sayfa1', 2026: 'GTIP ULKE GB
    TARIH') — başlık satırının ilk hücresi 'AYLAR' olan sayfa bulunmalı."""
    noktalar = yil_verisini_cikar(_yillik_dosya_baytlari(_TEMEL_SATIRLAR, sayfa_adi="Sayfa1"), 2025, "OCAK")
    assert noktalar[("SU ÜRÜNLERİ", "fobusd")]["2025-01-01"] == pytest.approx(8600.0)


def test_yil_verisini_cikar_su_urunleri_yoksa_hata():
    with pytest.raises(RuntimeError, match="SU ÜRÜNLERİ"):
        yil_verisini_cikar(_yillik_dosya_baytlari([("OCAK", "KANATLI", "KANATLI", 1.0, 1.0)]), 2025, "OCAK")


def test_yil_verisini_cikar_hayvansal_grup_yoksa_hata():
    with pytest.raises(RuntimeError, match="hayvansal"):
        yil_verisini_cikar(
            _yillik_dosya_baytlari([("OCAK", "SU ÜRÜNLERİ", "LEVREK", 1.0, 1.0)]), 2025, "OCAK",
        )


def test_yil_verisini_cikar_kumulatif_dosyada_ara_ay_eksikse_hata():
    satirlar = _ay_satirlari("OCAK") + _ay_satirlari("MART")
    with pytest.raises(RuntimeError, match=r"OCAK..MART aylarını taşımıyor \(eksik: \['ŞUBAT'\]"):
        yil_verisini_cikar(_yillik_dosya_baytlari(satirlar), 2026, "MART")


def test_yil_verisini_cikar_kumulatif_dosyada_son_ay_eksikse_hata():
    with pytest.raises(RuntimeError, match=r"eksik: \['ŞUBAT'\]"):
        yil_verisini_cikar(_yillik_dosya_baytlari(_ay_satirlari("OCAK")), 2026, "ŞUBAT")


def test_yil_verisini_cikar_tanimayan_ay_degerinde_hata():
    satirlar = _ay_satirlari("OCAK") + [("Şubat ", "KANATLI", "KANATLI", 1.0, 1.0)]
    with pytest.raises(RuntimeError, match="tanınmayan 'Aylar' değeri 'Şubat '"):
        yil_verisini_cikar(_yillik_dosya_baytlari(satirlar), 2026, "OCAK")


def test_yil_verisini_cikar_hicbir_ayda_olmayan_kalemde_hata():
    satirlar = [s for s in _ay_satirlari("OCAK") if s[2] != "KAYA LEVREĞİ"]
    with pytest.raises(RuntimeError, match=r"satırı yok \(ay, kalem\): \[\('OCAK', 'KAYA LEVREĞİ'\)\]"):
        yil_verisini_cikar(_yillik_dosya_baytlari(satirlar), 2026, "OCAK")


def test_yil_verisini_cikar_bir_ayda_satiri_olmayan_kalemde_hata():
    """Kaynak sıfır ihracatlı ayda da 0 değerli satır yazıyor (ölçüldü
    2026-11-27): satırın yokluğu sıfır değil okunamamadır — ne delik ne 0."""
    subat = [s for s in _ay_satirlari("ŞUBAT") if s[1] != "BAL"]
    with pytest.raises(RuntimeError, match=r"satırı yok \(ay, kalem\): \[\('ŞUBAT', 'BAL'\)\]"):
        yil_verisini_cikar(_yillik_dosya_baytlari(_ay_satirlari("OCAK") + subat), 2026, "ŞUBAT")


def test_yil_verisini_cikar_sifir_degerli_satiri_sifir_olarak_okur():
    """Meşru durum: kaynağın 0 yazdığı ay (Kırmızı Et 2026-03 gibi) 0 kalır."""
    subat = [s if s[1] != "KIRMIZI ET VE SAKATAT" else (s[0], s[1], s[2], 0.0, 0.0) for s in _ay_satirlari("ŞUBAT")]
    noktalar = yil_verisini_cikar(_yillik_dosya_baytlari(_ay_satirlari("OCAK") + subat), 2026, "ŞUBAT")
    assert noktalar[("KIRMIZI ET VE SAKATAT", "fobusd")] == {"2026-01-01": pytest.approx(5.0), "2026-02-01": 0.0}


def test_dogrula_su_alt_kirilimi_yoksa_hata():
    aile = {("OCAK", "SU ÜRÜNLERİ"): [1.0, 1.0], ("OCAK", "KANATLI"): [1.0, 1.0]}
    su_alt = {("OCAK", "SU ÜRÜNLERİ"): [1.0, 1.0]}  # 2024 tarzı: kırılım yok
    with pytest.raises(RuntimeError, match="Levrek/Çipura"):
        _dogrula(aile, su_alt, 2024)


# --- seri_cek: ağ kabuğu ---


class SahteYanit:
    def __init__(self, status_code=200, json_veri=None, content=b"", url="https://x"):
        self.status_code = status_code
        self._json = json_veri
        self.content = content
        self.url = url

    def json(self):
        return self._json


class SahteOturum:
    def __init__(self, icerik_html, dosya_baytlari):
        self.icerik_html = icerik_html
        self.dosya_baytlari = dosya_baytlari
        self.cagrilar = []

    def get(self, url, params=None, timeout=None):
        self.cagrilar.append(url)
        if "Sayfa_Icerik_JSON" in url:
            return SahteYanit(json_veri={"icerik": self.icerik_html})
        return SahteYanit(content=self.dosya_baytlari)


def _tek_yillik_icerik_html(yil=2025, ay="Ocak"):
    return f'<h3>{yil}</h3><p><strong>{ay}: </strong> <a href="https://eib.li/X">EİB Aylık</a></p>'


def test_seri_cek_dogru_deger_dondurur():
    oturum = SahteOturum(_tek_yillik_icerik_html(), _yillik_dosya_baytlari(_TEMEL_SATIRLAR))
    df = seri_cek(
        eib_seri(eib_kalem="LEVREK", eib_olcut="fobusd"),
        onbellek={}, session=oturum, bugun=date(2025, 2, 18),
    )
    assert df["value"].iloc[0] == pytest.approx(5000.0)


def test_seri_cek_onbellegi_paylasir():
    oturum = SahteOturum(_tek_yillik_icerik_html(), _yillik_dosya_baytlari(_TEMEL_SATIRLAR))
    onbellek = {}
    seri_cek(eib_seri(eib_kalem="LEVREK", eib_olcut="fobusd"), onbellek=onbellek, session=oturum, bugun=date(2025, 2, 18))
    cagri_sayisi = len(oturum.cagrilar)
    seri_cek(eib_seri(eib_kalem="ÇİPURA", eib_olcut="fobusd"), onbellek=onbellek, session=oturum, bugun=date(2025, 2, 18))
    assert len(oturum.cagrilar) == cagri_sayisi


def test_seri_cek_start_date_oncesini_kirpar():
    satirlar = _TEMEL_SATIRLAR + _ay_satirlari("ŞUBAT")
    icerik = '<h3>2025</h3><p><strong>Ocak: </strong> <a href="https://eib.li/X">EİB</a></p><p><strong>Şubat: </strong> <a href="https://eib.li/Y">EİB Aylık</a></p>'
    oturum = SahteOturum(icerik, _yillik_dosya_baytlari(satirlar))
    df = seri_cek(
        eib_seri(eib_kalem="LEVREK", eib_olcut="fobusd", start_date="2025-02-01"),
        onbellek={}, session=oturum, bugun=date(2025, 2, 18),
    )
    assert list(df["date"]) == ["2025-02-01"]


def test_seri_cek_bilinmeyen_kombinasyonda_hata():
    oturum = SahteOturum(_tek_yillik_icerik_html(), _yillik_dosya_baytlari(_TEMEL_SATIRLAR))
    with pytest.raises(RuntimeError, match="bulunamadı"):
        seri_cek(eib_seri(eib_kalem="YOK-OLAN-KALEM", eib_olcut="fobusd"), onbellek={}, session=oturum, bugun=date(2025, 2, 18))


def test_seri_cek_icerik_http_hatasi_yukselir():
    class HataliOturum:
        def get(self, url, params=None, timeout=None):
            return SahteYanit(status_code=500)

    with pytest.raises(requests.HTTPError, match="HTTP 500"):
        seri_cek(eib_seri(), onbellek={}, session=HataliOturum(), bugun=date(2026, 9, 18))


class CokYilliOturum:
    """İçerik JSON'u + URL'e göre farklı yıllık dosya döndüren sahte oturum."""

    def __init__(self, icerik_html, dosyalar):
        self.icerik_html = icerik_html
        self.dosyalar = dosyalar

    def get(self, url, params=None, timeout=None):
        if "Sayfa_Icerik_JSON" in url:
            return SahteYanit(json_veri={"icerik": self.icerik_html})
        return SahteYanit(content=self.dosyalar[url])


def test_seri_cek_gecmis_yilin_basligi_yoksa_hata():
    oturum = SahteOturum(_tek_yillik_icerik_html(yil=2026, ay="Ocak"), _yillik_dosya_baytlari(_TEMEL_SATIRLAR))
    with pytest.raises(RuntimeError, match="2025 yılının başlığı ya da ay bağlantıları"):
        seri_cek(eib_seri(), onbellek={}, session=oturum, bugun=date(2026, 9, 18))


def test_seri_cek_cari_yil_henuz_yayimlanmadiysa_gecen_yille_doner():
    """Henüz yayımlanmadı: Ocak başında 2026 başlığı yok, 2025 Aralık var."""
    oturum = SahteOturum(
        _tek_yillik_icerik_html(yil=2025, ay="Aralık"),
        _yillik_dosya_baytlari([s for ay in AY_ADLARI for s in _ay_satirlari(ay)]),
    )
    df = seri_cek(eib_seri(eib_kalem="LEVREK"), onbellek={}, session=oturum, bugun=date(2026, 1, 5))
    assert len(df) == 12
    assert df["date"].iloc[-1] == "2025-12-01"


def test_seri_cek_cari_yilin_eylul_ekimini_atlamaz():
    """Gerçek olay (2026-11-27): Eylül/Ekim etiketleri entity'li olduğu için
    cari yıl Ağustos'ta kalıyordu. Artık Ekim kümülatif dosyası seçilir ve
    OCAK..EKİM delik olmadan gelir."""
    icerik = (
        '<h3>2026</h3><p><strong>Ocak: </strong> <a href="https://eib.li/O26">EİB</a></p>'
        '<p><strong>Ağustos: </strong> <a href="https://eib.li/A26">EİB Aylık</a></p>'
        '<p><strong>Eyl&uuml;l:&nbsp;</strong><a href="https://eib.li/E26">EİB Aylık</a></p>'
        '<p><strong>Ekim:&nbsp;</strong><a href="https://eib.li/K26">EİB Aylık</a></p>'
        '<h3>2025</h3><p><strong>Aralık: </strong> <a href="https://eib.li/R25">EİB Aylık</a></p>'
    )
    dosyalar = {
        "https://eib.li/K26": _yillik_dosya_baytlari([s for ay in AY_ADLARI[:10] for s in _ay_satirlari(ay)]),
        "https://eib.li/R25": _yillik_dosya_baytlari([s for ay in AY_ADLARI for s in _ay_satirlari(ay)]),
    }
    df = seri_cek(eib_seri(), onbellek={}, session=CokYilliOturum(icerik, dosyalar), bugun=date(2026, 11, 27))
    assert len(df) == 22
    assert df["date"].iloc[-1] == "2026-10-01"
    assert pd.date_range("2025-01-01", "2026-10-01", freq="MS").strftime("%Y-%m-%d").tolist() == list(df["date"])


def test_seri_cek_cari_yilin_basligi_yil_ortasinda_yoksa_hata():
    """Kasım'da 2026 başlığı görünmüyorsa "henüz yayımlanmadı" değildir:
    sessizce geçmek tüm EİB CSV'lerini 2025-12'de bitirirdi."""
    oturum = SahteOturum(
        _tek_yillik_icerik_html(yil=2025, ay="Aralık"),
        _yillik_dosya_baytlari([s for ay in AY_ADLARI for s in _ay_satirlari(ay)]),
    )
    with pytest.raises(RuntimeError, match="2026 yılının başlığı ya da ay bağlantıları"):
        seri_cek(eib_seri(eib_kalem="LEVREK"), onbellek={}, session=oturum, bugun=date(2026, 11, 27))


def test_seri_cek_cari_yil_toleransin_son_gununde_henuz_yoksa_gecen_yille_doner():
    oturum = SahteOturum(
        _tek_yillik_icerik_html(yil=2025, ay="Aralık"),
        _yillik_dosya_baytlari([s for ay in AY_ADLARI for s in _ay_satirlari(ay)]),
    )
    df = seri_cek(eib_seri(eib_kalem="LEVREK"), onbellek={}, session=oturum, bugun=date(2026, 3, 31))
    assert df["date"].iloc[-1] == "2025-12-01"


def test_seri_cek_cari_yil_toleransi_bitince_hata():
    oturum = SahteOturum(
        _tek_yillik_icerik_html(yil=2025, ay="Aralık"),
        _yillik_dosya_baytlari([s for ay in AY_ADLARI for s in _ay_satirlari(ay)]),
    )
    with pytest.raises(RuntimeError, match="2026 yılının başlığı ya da ay bağlantıları"):
        seri_cek(eib_seri(eib_kalem="LEVREK"), onbellek={}, session=oturum, bugun=date(2026, 4, 1))
