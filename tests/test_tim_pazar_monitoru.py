"""TİM İhracat Pazar Monitörü aylık PDF bülteni istemcisi
(`ingest/tim.py::pazar_monitoru_*`) testleri.

Ayrı dosyada: `tests/test_tim.py` sektörel/il/ülke XLSX bültenlerinin
sahibi; bu dosya yalnızca İPM eklemesini kapsar, mevcut dosyalara dokunmaz.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import requests

from ingest.tim import (
    PM_METINSIZ_BULTENLER,
    PM_SEKTORLER,
    PmMetinKatmaniYokHatasi,
    _pazar_monitoru_onbellegi_getir,
    _pm_dosya_tarihi,
    PM_ULKELER,
    _pm_milli_degerlerini_ayikla,
    _pm_satirlari_ayikla,
    _pm_sayfa_tipi,
    pazar_monitoru_bulten_baglantilari,
    pazar_monitoru_seri_cek,
    pm_bultenini_ayristir,
)


def pm_seri(**kwargs):
    varsayilan = dict(
        id="ihracat-pazar-monitoru/test", tim_pm_endeks="talep",
        tim_pm_sektor=None, tim_pm_ulke=None, start_date=None,
    )
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


# --- _pm_sayfa_tipi: başlık metnine göre sayfa sınıflandırma ---


def test_pm_sayfa_tipi_sektor_talep():
    metin = "TEMMUZ 2026\nTİM SEKTÖR SINIFLANDIRMASINA GÖRE İHRACAT TALEP ENDEKSİ\n..."
    assert _pm_sayfa_tipi(metin) == "sektor-talep"


def test_pm_sayfa_tipi_sektor_dayaniklilik():
    metin = "TEMMUZ 2026\nTİM SEKTÖR SINIFLANDIRMASINA GÖRE PAZAR DAYANIKLILIK ENDEKSİ\n..."
    assert _pm_sayfa_tipi(metin) == "sektor-dayaniklilik"


def test_pm_sayfa_tipi_ulke_talep():
    metin = "SEÇİLMİŞ ÜLKELER İÇİN İHRACAT TALEP ENDEKSİ\n..."
    assert _pm_sayfa_tipi(metin) == "ulke-talep"


def test_pm_sayfa_tipi_ulke_dayaniklilik():
    metin = "SEÇİLMİŞ ÜLKELER İÇİN PAZAR DAYANIKLILIK ENDEKSİ\n..."
    assert _pm_sayfa_tipi(metin) == "ulke-dayaniklilik"


def test_pm_sayfa_tipi_milli():
    metin = "TİM İHRACAT TALEP ENDEKSİ\n...\nTİM PAZAR DAYANIKLILIK ENDEKSİ\n..."
    assert _pm_sayfa_tipi(metin) == "milli"


def test_pm_sayfa_tipi_metodoloji_sayfasinda_none():
    assert _pm_sayfa_tipi("MET ODOLOJİ\nİhracat Talep Endeksi ...") is None


# --- _pm_satirlari_ayikla: sektör/ülke tablosu satırları ---


def test_pm_satirlari_ayikla_gecerli_satiri_okur():
    """Ölçülen gerçek satır (Temmuz 2026 bülteni, sektör Talep tablosu)."""
    metin = "Çelik 101,4 0,5 0,8 1,7"
    sonuc = _pm_satirlari_ayikla(metin, PM_SEKTORLER)
    assert sonuc == {"Çelik": 101.4}


def test_pm_satirlari_ayikla_negatif_degisimli_satiri_okur():
    metin = "Gemi, Yat ve Hizmetleri 101,3 -5,1 1,8 4,0"
    sonuc = _pm_satirlari_ayikla(metin, PM_SEKTORLER)
    assert sonuc == {"Gemi, Yat ve Hizmetleri": 101.3}
 
 
def test_pm_satirlari_ayikla_ocak_tire_dusen_ytd_hucreyi_okur():
    """Ocak 2025 Talep tablosu: Yılbaşına sütunu `-` basılı geliyor."""
    metin = "Çelik 99,4 - -1,4 -0,5"
    assert _pm_satirlari_ayikla(metin, PM_SEKTORLER) == {"Çelik": 99.4}


def test_pm_satirlari_ayikla_ocak_sarmalanmis_ytd_satirini_okur():
    """Ocak 2025 Dayanıklılık tablosunda o `-` hücresi satırdan ayrılıp
    kendi satırına düşüyor; satırda yalnızca üç sayı kalıyor."""
    metin = "Çelik 99,7 - 0,5 0,3\n-\nÇimento, Cam, Ser. Topr. Ür. 98,9 0,7 0,6\n-"
    assert _pm_satirlari_ayikla(metin, PM_SEKTORLER) == {
        "Çelik": 99.7,
        "Çimento, Cam, Ser. Topr. Ür.": 98.9,
    }


def test_pm_satirlari_ayikla_bilinmeyen_adi_atlar():
    metin = "Bilinmeyen Sektör 101,4 0,5 0,8 1,7"
    assert _pm_satirlari_ayikla(metin, PM_SEKTORLER) == {}


def test_pm_satirlari_ayikla_footer_satirini_atlar():
    assert _pm_satirlari_ayikla("Sektörler alfabetik olarak sıralanmıştır.", PM_SEKTORLER) == {}


def test_pm_satirlari_ayikla_ulke_listesiyle_calisir():
    metin = "Danimarka 102,9 2,1 2,4 3,6"
    assert _pm_satirlari_ayikla(metin, PM_ULKELER) == {"Danimarka": 102.9}


# --- _pm_milli_degerlerini_ayikla ---


def test_pm_milli_degerlerini_ayikla_iki_satiri_da_okur():
    metin = (
        "İhracat Talep Endeksi 100,4 0,1 0,3 0,5\n"
        "Pazar Dayanıklılık Endeksi 99,8 0,6 0,2 0,7\n"
    )
    assert _pm_milli_degerlerini_ayikla(metin) == {"talep": 100.4, "dayaniklilik": 99.8}


def test_pm_milli_degerlerini_ayikla_eksikse_kismi_doner():
    """Aralık 2025 gibi bazı aylarda haber metninde yalnızca Talep var —
    ama bu fonksiyon PDF bülten metnini işler; kısmi eksiklik olağan."""
    metin = "İhracat Talep Endeksi 99,4 -0,5 -0,3 -0,5\n"
    assert _pm_milli_degerlerini_ayikla(metin) == {"talep": 99.4}


# --- pm_bultenini_ayristir: tam bülten şablon doğrulaması ---

def _deger(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")



def _tam_bulten_sayfalari() -> list[str]:
    milli = (
        "TİM İHRACAT TALEP ENDEKSİ\nİhracat Talep Endeksi 100,4 0,1 0,3 0,5\n"
        "TİM PAZAR DAYANIKLILIK ENDEKSİ\nPazar Dayanıklılık Endeksi 99,8 0,6 0,2 0,7\n"
    )
    sektor_talep = "TİM SEKTÖR SINIFLANDIRMASINA GÖRE İHRACAT TALEP ENDEKSİ\n" + "\n".join(
        f"{ad} {_deger(101.0 + i * 0.1)} 0,5 0,8 1,7"
        for i, ad in enumerate(PM_SEKTORLER)
    )
    sektor_day = "TİM SEKTÖR SINIFLANDIRMASINA GÖRE PAZAR DAYANIKLILIK ENDEKSİ\n" + "\n".join(
        f"{ad} 100,0 0,5 0,8 1,7" for ad in PM_SEKTORLER
    )
    ulke_talep = "SEÇİLMİŞ ÜLKELER İÇİN İHRACAT TALEP ENDEKSİ\n" + "\n".join(
        f"{ad} 101,0 0,5 0,8 1,7" for ad in PM_ULKELER
    )
    ulke_day = "SEÇİLMİŞ ÜLKELER İÇİN PAZAR DAYANIKLILIK ENDEKSİ\n" + "\n".join(
        f"{ad} 99,0 0,5 0,8 1,7" for ad in PM_ULKELER
    )
    return [milli, sektor_talep, sektor_day, ulke_talep, ulke_day]


class _SahteSayfa:
    def __init__(self, metin):
        self._metin = metin

    def extract_text(self):
        return self._metin


class _SahtePdf:
    def __init__(self, sayfalar):
        self.pages = [_SahteSayfa(m) for m in sayfalar]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_pm_bultenini_ayristir_tam_sablonda_gecer(monkeypatch):
    import ingest.tim as tim_mod

    monkeypatch.setattr(tim_mod.pdfplumber, "open", lambda _b: _SahtePdf(_tam_bulten_sayfalari()))
    sonuc = pm_bultenini_ayristir(b"x")
    assert sonuc["milli"] == {"talep": 100.4, "dayaniklilik": 99.8}
    assert sonuc["sektor-talep"]["Çelik"] == pytest.approx(101.0)
    assert set(sonuc["sektor-talep"]) == set(PM_SEKTORLER)
    assert set(sonuc["ulke-talep"]) == set(PM_ULKELER)


def test_pm_bultenini_ayristir_eksik_sektorde_hata(monkeypatch):
    import ingest.tim as tim_mod

    sayfalar = _tam_bulten_sayfalari()
    # sektör-talep sayfasından bir sektörü çıkar (şablon kayması simülasyonu)
    sayfalar[1] = sayfalar[1].replace("Çelik 101,0 0,5 0,8 1,7\n", "")
    monkeypatch.setattr(tim_mod.pdfplumber, "open", lambda _b: _SahtePdf(sayfalar))
    with pytest.raises(RuntimeError, match="şablonu değişmiş olabilir"):
        pm_bultenini_ayristir(b"x")


def test_pm_bultenini_ayristir_milli_eksikse_hata(monkeypatch):
    import ingest.tim as tim_mod

    sayfalar = _tam_bulten_sayfalari()
    sayfalar[0] = "TİM İHRACAT TALEP ENDEKSİ\nİhracat Talep Endeksi 100,4 0,1 0,3 0,5\n"  # Dayanıklılık kelimesi yok -> "milli" tipi tanınmaz
    monkeypatch.setattr(tim_mod.pdfplumber, "open", lambda _b: _SahtePdf(sayfalar))
    with pytest.raises(RuntimeError, match="şablonu değişmiş olabilir"):
        pm_bultenini_ayristir(b"x")


# --- pazar_monitoru_bulten_baglantilari: yıl arşivi -> aylık PDF ---


class SahteYanit:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class SahteOturum:
    def __init__(self, yanitlar):
        self.yanitlar = yanitlar

    def get(self, url, timeout=None):
        return self.yanitlar.get(url, SahteYanit(status_code=404))


def test_bulten_baglantilari_yil_sayfalarindan_pdf_toplar():
    ana_html = (
        '<a href="raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2026">2026</a>'
    )
    yil_html = (
        '<a href="/files/downloads/T%C4%B0M%20%C4%B0hracat%20Pazar%20Monit%C3%B6r%C3%BC/'
        'TIMIhracatPazarMonitoru202607.pdf">Temmuz</a>'
    )
    oturum = SahteOturum({
        "https://tim.org.tr/tr/raporlar-yayinlar-tim-ihracat-pazar-monitoru": SahteYanit(text=ana_html),
        "https://tim.org.tr/tr/raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2026": SahteYanit(text=yil_html),
    })
    baglantilar = pazar_monitoru_bulten_baglantilari(session=oturum)
    assert (2026, 7) in baglantilar
    assert baglantilar[(2026, 7)].endswith("TIMIhracatPazarMonitoru202607.pdf")


def test_bulten_baglantilari_bozuk_dosya_adini_da_bulur():
    """Ölçülen gerçek anomali: Nisan 2026 dosyasında 'İ' eklenip tire
    kullanılmış (`TİMIhracatPazarMonitoru-202604.pdf`)."""
    ana_html = '<a href="raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2026">2026</a>'
    yil_html = (
        '<a href="/files/downloads/x/T%C4%B0MIhracatPazarMonitoru-202604.pdf">Nisan</a>'
    )
    oturum = SahteOturum({
        "https://tim.org.tr/tr/raporlar-yayinlar-tim-ihracat-pazar-monitoru": SahteYanit(text=ana_html),
        "https://tim.org.tr/tr/raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2026": SahteYanit(text=yil_html),
    })
    baglantilar = pazar_monitoru_bulten_baglantilari(session=oturum)
    assert (2026, 4) in baglantilar


def test_bulten_baglantilari_yil_baglantisi_yoksa_hata():
    oturum = SahteOturum({
        "https://tim.org.tr/tr/raporlar-yayinlar-tim-ihracat-pazar-monitoru": SahteYanit(text="<html>boş</html>"),
    })
    with pytest.raises(RuntimeError, match="yıl bağlantısı bulunamadı"):
        pazar_monitoru_bulten_baglantilari(session=oturum)


# --- pazar_monitoru_seri_cek: dispatcher ---


def _onbellek():
    return {
        "pm_veri": {
            "milli-talep": {"2026-06-01": 98.9, "2026-07-01": 100.4},
            "milli-dayaniklilik": {"2026-06-01": 98.8, "2026-07-01": 99.8},
            "sektor-talep": {"Çelik": {"2026-07-01": 101.4}, "Tütün": {"2026-07-01": 100.7}},
            "sektor-dayaniklilik": {"Çelik": {"2026-07-01": 100.5}},
            "ulke-talep": {"Danimarka": {"2026-07-01": 102.9}, "İspanya": {"2026-07-01": 96.7}},
            "ulke-dayaniklilik": {"Danimarka": {"2026-07-01": 101.6}},
        }
    }


def test_seri_cek_milli_talep_dogru_deger_dondurur():
    df = pazar_monitoru_seri_cek(pm_seri(tim_pm_endeks="talep"), onbellek=_onbellek())
    assert df["value"].iloc[-1] == pytest.approx(100.4)


def test_seri_cek_milli_dayaniklilik_dogru_deger_dondurur():
    df = pazar_monitoru_seri_cek(pm_seri(tim_pm_endeks="dayaniklilik"), onbellek=_onbellek())
    assert df["value"].iloc[-1] == pytest.approx(99.8)


def test_seri_cek_sektor_talep_dogru_deger_dondurur():
    df = pazar_monitoru_seri_cek(
        pm_seri(tim_pm_endeks="talep", tim_pm_sektor="Çelik"), onbellek=_onbellek(),
    )
    assert df["value"].iloc[-1] == pytest.approx(101.4)


def test_seri_cek_ulke_talep_dogru_deger_dondurur():
    df = pazar_monitoru_seri_cek(
        pm_seri(tim_pm_endeks="talep", tim_pm_ulke="Danimarka"), onbellek=_onbellek(),
    )
    assert df["value"].iloc[-1] == pytest.approx(102.9)


def test_seri_cek_sektor_dayaniklilik_ayri_eksenden_okur():
    df = pazar_monitoru_seri_cek(
        pm_seri(tim_pm_endeks="dayaniklilik", tim_pm_sektor="Çelik"), onbellek=_onbellek(),
    )
    assert df["value"].iloc[-1] == pytest.approx(100.5)


def test_seri_cek_bilinmeyen_sektorde_hata():
    with pytest.raises(RuntimeError, match="sektörü İPM bültenlerinde bulunamadı"):
        pazar_monitoru_seri_cek(
            pm_seri(tim_pm_endeks="talep", tim_pm_sektor="Olmayan Sektör"), onbellek=_onbellek(),
        )


def test_seri_cek_bilinmeyen_ulkede_hata():
    with pytest.raises(RuntimeError, match="ülkesi İPM bültenlerinde bulunamadı"):
        pazar_monitoru_seri_cek(
            pm_seri(tim_pm_endeks="talep", tim_pm_ulke="Olmayan Ülke"), onbellek=_onbellek(),
        )


def test_seri_cek_start_date_oncesini_kirpar():
    df = pazar_monitoru_seri_cek(
        pm_seri(tim_pm_endeks="talep", start_date="2026-07-01"), onbellek=_onbellek(),
    )
    assert list(df["date"]) == ["2026-07-01"]


# --- 2026-11-27 sessiz atlama düzeltmesi: bağlantı toplama ---

ANA_URL = "https://tim.org.tr/tr/raporlar-yayinlar-tim-ihracat-pazar-monitoru"
YIL_URL_2025 = "https://tim.org.tr/tr/raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2025"
ANA_HTML_2025 = '<a href="raporlar-yayinlar-bultenler-tim-ihracat-pazar-monitoru-2025">2025</a>'
PM_DIZIN = "/files/downloads/T%C4%B0M%20%C4%B0hracat%20Pazar%20Monit%C3%B6r%C3%BC/"


def _yil_html(*dosyalar: str) -> str:
    return "".join(f'<a href="{PM_DIZIN}{d}">x</a>' for d in dosyalar)


def _oturum_2025(yil_html: str) -> SahteOturum:
    return SahteOturum({
        ANA_URL: SahteYanit(text=ANA_HTML_2025),
        YIL_URL_2025: SahteYanit(text=yil_html),
    })


def test_pm_dosya_tarihi_haziran_adinda_yili_sayfadan_alir():
    """Ölçülen gerçek ad: 2025 sayfasında `TIM_Ihracat_Pazar_Monitoru_Haziran.pdf`."""
    assert _pm_dosya_tarihi(PM_DIZIN + "TIM_Ihracat_Pazar_Monitoru_Haziran.pdf", 2025) == (2025, 6)


def test_pm_dosya_tarihi_yil_ve_ay_adini_okur():
    assert _pm_dosya_tarihi("/x/tim_ihracat_pazar_monit%C3%B6r%C3%BC_2024_subat.pdf", 2024) == (2024, 2)


def test_pm_dosya_tarihi_umlautlu_ve_bosluklu_adlari_okur():
    assert _pm_dosya_tarihi("/x/TIM_ihracat_Pazar_Monit%C3%B6r%C3%BC_202410.pdf", 2024) == (2024, 10)
    assert _pm_dosya_tarihi("/x/T%C4%B0M%20%C4%B0hracat%20Pazar%20Monit%C3%B6r%C3%BC%20-%20202401.pdf", 2024) == (2024, 1)


def test_pm_dosya_tarihi_ay_okunamazsa_hata():
    with pytest.raises(RuntimeError, match="dosya adından ay okunamadı"):
        _pm_dosya_tarihi("/x/TIMIhracatPazarMonitoruMetodoloji.pdf", 2025)


def test_bulten_baglantilari_eski_desene_uymayan_adlari_kacirmaz():
    """Eski `azarmonitoru` deseni Haziran 2025'i sessizce düşürüyordu."""
    yil_html = _yil_html(
        "TIMIhracatPazarMonitoru202505.pdf",
        "TIM_Ihracat_Pazar_Monitoru_Haziran.pdf",
        "TIMIhracatPazarMonitoru202507.pdf",
    )
    baglantilar = pazar_monitoru_bulten_baglantilari(session=_oturum_2025(yil_html))
    assert sorted(baglantilar) == [(2025, 5), (2025, 6), (2025, 7)]
    assert baglantilar[(2025, 6)].endswith("TIM_Ihracat_Pazar_Monitoru_Haziran.pdf")


def test_bulten_baglantilari_baska_yayin_pdfini_yok_sayar():
    yil_html = _yil_html("TIMIhracatPazarMonitoru202505.pdf") + (
        '<a href="/files/downloads/Raporlar/Frascati K%C4%B1lavuzu 2015.pdf">x</a>'
    )
    assert sorted(pazar_monitoru_bulten_baglantilari(session=_oturum_2025(yil_html))) == [(2025, 5)]


def test_bulten_baglantilari_son_ay_henuz_yayimlanmamissa_gecer():
    """Meşru durum: en yeni ayın bülteni henüz yok — son bağlantı Mayıs."""
    yil_html = _yil_html("TIMIhracatPazarMonitoru202504.pdf", "TIMIhracatPazarMonitoru202505.pdf")
    baglantilar = pazar_monitoru_bulten_baglantilari(session=_oturum_2025(yil_html))
    assert max(baglantilar) == (2025, 5)


def test_bulten_baglantilari_ara_ay_eksikse_hata():
    yil_html = _yil_html("TIMIhracatPazarMonitoru202504.pdf", "TIMIhracatPazarMonitoru202507.pdf")
    with pytest.raises(RuntimeError, match="ara ay.*2025-05, 2025-06"):
        pazar_monitoru_bulten_baglantilari(session=_oturum_2025(yil_html))


def test_bulten_baglantilari_ayni_aya_iki_farkli_dosyada_hata():
    yil_html = _yil_html("TIMIhracatPazarMonitoru202505.pdf", "TIM_Ihracat_Pazar_Monitoru_202505.pdf")
    with pytest.raises(RuntimeError, match="2025-05 için iki farklı bülten bağlantısı"):
        pazar_monitoru_bulten_baglantilari(session=_oturum_2025(yil_html))


def test_bulten_baglantilari_yil_sayfasi_okunamazsa_hata():
    """Eskiden 200 dönmeyen yıl sayfası sessizce atlanıp o yılın bütün
    ayları düşüyordu."""
    oturum = SahteOturum({ANA_URL: SahteYanit(text=ANA_HTML_2025)})  # yıl sayfası 404
    with pytest.raises(requests.HTTPError, match="HTTP 404"):
        pazar_monitoru_bulten_baglantilari(session=oturum)


# --- metin katmanı ve önbellek döngüsü ---


def test_pm_bultenini_ayristir_metinsiz_bultende_ozel_hata(monkeypatch):
    import ingest.tim as tim_mod

    sayfalar = ["TİM İHRACAT PAZAR MONİTÖRÜ EYLÜL 2025", "", "", "", "", "", "www.tim.org.tr"]
    monkeypatch.setattr(tim_mod.pdfplumber, "open", lambda _b: _SahtePdf(sayfalar))
    with pytest.raises(PmMetinKatmaniYokHatasi, match="metin katmanı yok"):
        pm_bultenini_ayristir(b"x")


class PdfYaniti:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code
        self.text = ""


METINSIZ_SAYFALAR = ["KAPAK", "", "", "", "", "www.tim.org.tr"]


def _onbellek_kur(monkeypatch, aylar: dict[tuple[int, int], object]):
    """`aylar`: (yıl, ay) -> sayfa listesi ya da HTTP durum kodu (int)."""
    import ingest.tim as tim_mod

    baglantilar = {k: f"https://tim.org.tr/pm/{k[0]}{k[1]:02d}.pdf" for k in aylar}
    yanitlar, icerikler = {}, {}
    for anahtar, deger in aylar.items():
        icerik = f"{anahtar}".encode()
        if isinstance(deger, int):
            yanitlar[baglantilar[anahtar]] = PdfYaniti(icerik, status_code=deger)
        else:
            yanitlar[baglantilar[anahtar]] = PdfYaniti(icerik)
            icerikler[icerik] = deger
    monkeypatch.setattr(tim_mod, "pazar_monitoru_bulten_baglantilari", lambda session=None: baglantilar)
    monkeypatch.setattr(tim_mod.pdfplumber, "open", lambda bio: _SahtePdf(icerikler[bio.getvalue()]))
    return SahteOturum(yanitlar)


def test_onbellek_bilinen_metinsiz_ayi_acikca_atlar(monkeypatch):
    assert (2025, 6) in PM_METINSIZ_BULTENLER
    oturum = _onbellek_kur(monkeypatch, {
        (2025, 5): METINSIZ_SAYFALAR, (2025, 6): METINSIZ_SAYFALAR,
        (2026, 1): _tam_bulten_sayfalari(),
    })
    veri = _pazar_monitoru_onbellegi_getir({}, session=oturum)
    assert veri["milli-talep"] == {"2026-01-01": pytest.approx(100.4)}
    assert set(veri["sektor-talep"]["Çelik"]) == {"2026-01-01"}


def test_onbellek_listede_olmayan_metinsiz_ayda_hata(monkeypatch):
    assert (2026, 2) not in PM_METINSIZ_BULTENLER
    oturum = _onbellek_kur(monkeypatch, {
        (2026, 1): _tam_bulten_sayfalari(), (2026, 2): METINSIZ_SAYFALAR,
    })
    with pytest.raises(RuntimeError, match="2026-02 bülteni okunamadı.*PM_METINSIZ_BULTENLER"):
        _pazar_monitoru_onbellegi_getir({}, session=oturum)


def test_onbellek_bilinen_metinsiz_ayda_sablon_kaymasi_yine_hata(monkeypatch):
    """Listedeki ay yalnızca METİN YOKSA atlanır; metin gelip şablon
    tutmazsa bu bir okuyamamadır."""
    sayfalar = _tam_bulten_sayfalari()
    sayfalar[1] = sayfalar[1].replace("Çelik 101,0 0,5 0,8 1,7\n", "")
    oturum = _onbellek_kur(monkeypatch, {(2025, 6): sayfalar})
    with pytest.raises(RuntimeError, match="2025-06 bülteni ayrıştırılamadı.*sektor-talep"):
        _pazar_monitoru_onbellegi_getir({}, session=oturum)


def test_onbellek_sablon_kaymasinda_ay_adiyla_hata(monkeypatch):
    sayfalar = _tam_bulten_sayfalari()
    sayfalar[3] = sayfalar[3].replace("Danimarka 101,0 0,5 0,8 1,7\n", "")
    oturum = _onbellek_kur(monkeypatch, {
        (2026, 1): _tam_bulten_sayfalari(), (2026, 2): sayfalar,
    })
    with pytest.raises(RuntimeError, match="2026-02 bülteni ayrıştırılamadı.*ulke-talep"):
        _pazar_monitoru_onbellegi_getir({}, session=oturum)


def test_onbellek_bulten_indirilemezse_hata(monkeypatch):
    """Eskiden 200 dönmeyen bülten "henüz yayımlanmamış" sayılıp atlanıyordu;
    oysa bağlantısı arşivde VAR."""
    oturum = _onbellek_kur(monkeypatch, {
        (2026, 1): _tam_bulten_sayfalari(), (2026, 2): 404,
    })
    with pytest.raises(requests.HTTPError, match="HTTP 404"):
        _pazar_monitoru_onbellegi_getir({}, session=oturum)
