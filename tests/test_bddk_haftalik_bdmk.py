"""BDDK Haftalık Bülten (NPL) ve BDMK (Faktoring/Finansal Kiralama) testleri.

`tests/test_bddk.py` (Aylık Bülten) DEĞİŞTİRİLMEDİ; bu dosya yalnızca
ikinci dalgada eklenen `seri_cek_haftalik` ve `seri_cek_bdmk` adaptörlerini
kapsar. Sahte HTTP yanıtları gerçek uçlardan 2026-09-18'de ölçülen biçimleri
taklit eder (bkz. `ingest/bddk.py` docstring'leri).
"""

from datetime import date
from types import SimpleNamespace

import pytest

from ingest.bddk import (
    _bdmk_sayi,
    _haftalik_tarih_parse,
    _haftalik_tarih_str,
    bdmk_aylik_gecmis_cek,
    bdmk_satirlari_ayikla,
    haftalik_noktalar_cek,
    seri_cek_bdmk,
    seri_cek_haftalik,
)


class SahteYanit:
    def __init__(self, metin="", govde=None, status_code=200):
        self.text = metin
        self.status_code = status_code
        self._govde = govde
        self.content = b"-----BEGIN CERTIFICATE-----\nsahte\n-----END CERTIFICATE-----\n"

    def json(self):
        return self._govde


@pytest.fixture(autouse=True)
def _ca_paketini_atla(monkeypatch, tmp_path):
    paket = tmp_path / "ca.pem"
    paket.write_text("sahte", encoding="utf-8")
    monkeypatch.setattr("ingest.bddk._ca_paketi", lambda session=None: str(paket))


# --- Tarih yardımcıları -----------------------------------------------------


def test_haftalik_tarih_str_sifir_doldurmasiz_gun():
    assert _haftalik_tarih_str(date(2024, 10, 4)) == "4.10.2024"


def test_haftalik_tarih_parse_tek_haneli_gunu_okur():
    assert _haftalik_tarih_parse("4.10.2024") == "2024-10-04"
    assert _haftalik_tarih_parse("11.09.2026") == "2026-09-11"


# --- Haftalık sayfalama ------------------------------------------------------


class SahteHaftalikOturum:
    """`gun` parametresini yok sayıp `tarih`e göre sabit pencere döner."""

    def __init__(self, pencereler: dict[str, dict]):
        self.pencereler = pencereler
        self.gonderilen_tarihler: list[str] = []

    def post(self, url, data=None, headers=None, timeout=None, verify=None):
        tarih = data["tarih"]
        self.gonderilen_tarihler.append(tarih)
        return SahteYanit(govde=self.pencereler[tarih])


def test_haftalik_noktalar_cek_geriye_sayfalar_ve_birlestirir(monkeypatch):
    """İki pencere (13'er nokta) art arda çekilip tek sözlükte birleşir."""
    monkeypatch.setattr("ingest.bddk.HAFTALIK_ILK_TARIH", "2026-08-28")
    pencereler = {
        "11.09.2026": {
            "XEkseni": ["4.09.2026", "11.09.2026"],
            "YEkseni": [862191.39, 867231.58],
        },
        "3.09.2026": {
            "XEkseni": ["28.08.2026", "4.09.2026"],
            "YEkseni": [844947.29, 862191.39],
        },
    }
    oturum = SahteHaftalikOturum(pencereler)
    noktalar = haftalik_noktalar_cek("2.0.1", 3, "10001", "11.09.2026", session=oturum)
    assert noktalar == {
        "2026-08-28": 844947.29,
        "2026-09-04": 862191.39,
        "2026-09-11": 867231.58,
    }
    assert oturum.gonderilen_tarihler == ["11.09.2026", "3.09.2026"]


def test_haftalik_noktalar_cek_pencere_ilerlemezse_sonsuz_donguye_girmeden_hata():
    """Sunucu aynı pencereyi tekrar döndürürse döngü kırılır; HAFTALIK_ILK_TARIH'e
    varılmadığı için sessizce durmak yerine (geçmiş kısalırdı) hata yükselir."""
    sabit_pencere = {
        "XEkseni": ["4.09.2026", "11.09.2026"],
        "YEkseni": [862191.39, 867231.58],
    }
    oturum = SahteHaftalikOturum({"11.09.2026": sabit_pencere, "3.09.2026": sabit_pencere})
    with pytest.raises(RuntimeError, match="pencere ilerlemedi.*2026-09-04 öncesi"):
        haftalik_noktalar_cek("2.0.1", 3, "10001", "11.09.2026", session=oturum)
    assert len(oturum.gonderilen_tarihler) == 2


def test_haftalik_noktalar_cek_bos_degerli_haftada_hata():
    """`None` değer eskiden atlanıyordu: o hafta CSV'de sessiz delik olurdu."""
    pencereler = {
        "11.09.2026": {
            "XEkseni": ["4.09.2026", "11.09.2026"],
            "YEkseni": [None, 867231.58],
        },
    }
    oturum = SahteHaftalikOturum(pencereler)
    with pytest.raises(RuntimeError, match="4.09.2026 haftası için değer boş"):
        haftalik_noktalar_cek("2.0.1", 3, "10001", "11.09.2026", session=oturum)


def test_haftalik_noktalar_cek_tarih_deger_sayisi_tutmazsa_hata():
    """`zip` kısa listede durur; fazla tarihler sessizce düşerdi."""
    pencereler = {
        "11.09.2026": {
            "XEkseni": ["28.08.2026", "4.09.2026", "11.09.2026"],
            "YEkseni": [862191.39, 867231.58],
        },
    }
    oturum = SahteHaftalikOturum(pencereler)
    with pytest.raises(RuntimeError, match=r"tarih \(3\) ve değer \(2\) sayısı tutmuyor"):
        haftalik_noktalar_cek("2.0.1", 3, "10001", "11.09.2026", session=oturum)


def test_seri_cek_haftalik_onbellegi_id_sutun_taraf_bazinda_paylasir(monkeypatch):
    monkeypatch.setattr("ingest.bddk.HAFTALIK_ILK_TARIH", "2026-09-04")
    pencereler = {
        "11.09.2026": {
            "XEkseni": ["4.09.2026", "11.09.2026"],
            "YEkseni": [283.5, 293.5],
        },
    }
    oturum = SahteHaftalikOturum(pencereler)
    seri = SimpleNamespace(
        bddk_haftalik_id="2.0.4", bddk_haftalik_sutun=3,
        bddk_haftalik_taraf="10001", start_date=None,
    )
    onbellek = {"haftalik_cari_tarih": "11.09.2026"}
    df = seri_cek_haftalik(seri, onbellek=onbellek, session=oturum)
    assert list(df["value"]) == [283.5, 293.5]
    # Aynı anahtar tekrar istenirse yeni istek atılmaz.
    df2 = seri_cek_haftalik(seri, onbellek=onbellek, session=oturum)
    assert len(oturum.gonderilen_tarihler) == 1
    assert list(df2["value"]) == [283.5, 293.5]


def test_seri_cek_haftalik_bos_seride_hata():
    oturum = SahteHaftalikOturum({"11.09.2026": {"XEkseni": [], "YEkseni": []}})
    seri = SimpleNamespace(
        bddk_haftalik_id="2.0.4", bddk_haftalik_sutun=3,
        bddk_haftalik_taraf="10001", start_date=None,
    )
    onbellek = {"haftalik_cari_tarih": "11.09.2026"}
    with pytest.raises(RuntimeError, match="hiç nokta"):
        seri_cek_haftalik(seri, onbellek=onbellek, session=oturum)


# --- BDMK sayı ve satır ayrıştırma ------------------------------------------


def test_bdmk_sayi_turk_bicimini_okur():
    assert _bdmk_sayi("601.648") == 601648.0
    assert _bdmk_sayi("10.104") == 10104.0
    assert _bdmk_sayi("-1.234") == -1234.0


def test_bdmk_sayi_bos_ve_tire_none_doner():
    assert _bdmk_sayi("") is None
    assert _bdmk_sayi("-") is None


def test_bdmk_sayi_okunamayan_metinde_hata():
    """Eskiden None dönüyordu = kalem o ay yok sayılıyordu (sessiz delik)."""
    with pytest.raises(RuntimeError, match="sayı olarak okunamadı: 'n/a'"):
        _bdmk_sayi("n/a")


BDMK_TABLO_HTML = """
<table id="TabloBasitGosterim">
<thead><tr><th>Sıra</th><th>Kalem</th><th>TP</th><th>YP</th><th>Toplam</th></tr></thead>
<tbody>
<tr>
    <td style="font-weight:bold">1</td>
        <td style="font-weight:bold">
    I. ESAS FAALİYET GELİRLERİ
</td>
                                    <td style="text-align:right;">119.973</td>
        <td style="text-align:right;">4.163</td>
        <td style="text-align:right;">124.136</td>
</tr>
<tr>
    <td style="font-style:italic">17</td>
        <td style="font-style:italic">
                &nbsp;&nbsp;&nbsp;&nbsp;
    5.4.1 Finansal Kiralama Alacakları
</td>
                                    <td style="text-align:right;">186.257</td>
        <td style="text-align:right;">415.390</td>
        <td style="text-align:right;">601.648</td>
</tr>
</tbody>
</table>
"""


def test_bdmk_satirlari_ayikla_etiket_ve_toplami_eslerler():
    satirlar = bdmk_satirlari_ayikla(BDMK_TABLO_HTML)
    assert satirlar["I. ESAS FAALİYET GELİRLERİ"] == 124136.0
    assert satirlar["5.4.1 Finansal Kiralama Alacakları"] == 601648.0
    # Başlık satırı (yalnızca <th>) bir kalem üretmemeli.
    assert len(satirlar) == 2


def test_bdmk_satirlari_ayikla_kisa_satirda_hata():
    tablo = """
<table id="TabloBasitGosterim"><tbody>
<tr><td>1</td><td>I. ESAS FAALİYET GELİRLERİ</td><td>124.136</td></tr>
</tbody></table>
"""
    with pytest.raises(RuntimeError, match="5 hücre yerine 3 hücre"):
        bdmk_satirlari_ayikla(tablo)


BOS_TABLO_HTML = """
<table id="TabloBasitGosterim">
<thead><tr><th>Sıra</th><th>Kalem</th><th>TP</th><th>YP</th><th>Toplam</th></tr></thead>
<tbody></tbody>
</table>
"""


class SahteBdmkOturum:
    """GET → antiforgery token sayfası; POST → (yil, ay) anahtarlı tablo HTML'i."""

    def __init__(self, aylik_html: dict[tuple[int, int], str], token="tok"):
        self.aylik_html = aylik_html
        self.token = token
        self.istekler: list[tuple[int, int]] = []

    def get(self, url, timeout=None, verify=None):
        return SahteYanit(
            metin=f'<input name="__RequestVerificationToken" type="hidden" value="{self.token}" />'
        )

    def post(self, url, data=None, timeout=None, verify=None):
        yil, ay = int(data["yil"]), int(data["ay"])
        self.istekler.append((yil, ay))
        html = self.aylik_html.get((yil, ay), BOS_TABLO_HTML)
        return SahteYanit(metin=html)


def _bdmk_seri(**kwargs):
    varsayilan = dict(
        bddk_bdmk_urun="faktoring", bddk_bdmk_tablo=2,
        bddk_bdmk_kalem="XXI. DÖNEM NET KARI/ZARARI (XV+XX)",
        bddk_bdmk_kumulatif=True, start_date=None,
    )
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


def _karzarar_html(net_kar_toplam: float) -> str:
    """`net_kar_toplam` gerçek (küçük) değeri Türk binlik-ayraçlı metne çevirir."""
    metin = f"{net_kar_toplam:,.0f}".replace(",", ".")
    return f"""
<table id="TabloBasitGosterim">
<thead><tr><th>Sıra</th><th>Kalem</th><th>TP</th><th>YP</th><th>Toplam</th></tr></thead>
<tbody>
<tr>
    <td>79</td><td>XXI. DÖNEM NET KARI/ZARARI (XV+XX)</td>
    <td style="text-align:right;">0</td>
    <td style="text-align:right;">0</td>
    <td style="text-align:right;">{metin}</td>
</tr>
</tbody>
</table>
"""


# Gerçek ölçüm: Faktöring Net Kârı (kümülatif) 2026 Mayıs–Temmuz; önceki
# aylar testin kurgusu.
KUMULATIF_2026 = {1: 3000, 2: 6100, 3: 9400, 4: 11800, 5: 14604, 6: 18076, 7: 21888}


def _tam_gecmis(degerler: dict[int, float] = KUMULATIF_2026, yil: int = 2026):
    return {(yil, ay): _karzarar_html(deger) for ay, deger in degerler.items()}


@pytest.fixture
def _ilk_yil_2026(monkeypatch):
    """Geçmiş BDMK_ILK_YIL Ocak'a kadar eksiksiz istenir; sahte veriyi kısa
    tutmak için alt sınır 2026'ya çekilir."""
    monkeypatch.setattr("ingest.bddk.BDMK_ILK_YIL", 2026)


def test_bdmk_aylik_gecmis_cek_yayimlanmamis_ayi_geriye_yururek_atlar(_ilk_yil_2026):
    """Eylül/Ağustos henüz yayımlanmamışsa (başlık-only tablo) Temmuz'a kadar
    geriye yürünür — bu meşru durum hata vermez."""
    oturum = SahteBdmkOturum(_tam_gecmis())
    aylik = bdmk_aylik_gecmis_cek("faktoring", 2, date(2026, 9, 18), session=oturum)
    assert sorted(aylik) == [f"2026-{ay:02d}-01" for ay in range(1, 8)]
    assert aylik["2026-07-01"]["XXI. DÖNEM NET KARI/ZARARI (XV+XX)"] == pytest.approx(21888)
    assert aylik["2026-06-01"]["XXI. DÖNEM NET KARI/ZARARI (XV+XX)"] == pytest.approx(18076)
    # Ağustos ve Eylül boş tablo döndürdüğü için hiç eklenmemeli.
    assert "2026-08-01" not in aylik
    assert "2026-09-01" not in aylik


def test_seri_cek_bdmk_kumulatifi_aylik_akima_cevirir(_ilk_yil_2026):
    """Reel ölçüm: Faktöring Net Kârı Tem=21888, Haz=18076 kümülatif → Tem akımı 3812."""
    oturum = SahteBdmkOturum(_tam_gecmis())
    df = seri_cek_bdmk(_bdmk_seri(), session=oturum, bugun=date(2026, 9, 18))
    satirlar = dict(zip(df["date"], df["value"]))
    assert satirlar["2026-07-01"] == pytest.approx(3812)
    assert satirlar["2026-06-01"] == pytest.approx(3472)


def test_seri_cek_bdmk_onbellek_tablo_bazinda_paylasilir(_ilk_yil_2026):
    """Aynı (ürün, tabloNo) çifti iki farklı kalem için tek indirmeyi paylaşır."""
    oturum = SahteBdmkOturum(_tam_gecmis())
    onbellek: dict = {}
    seri_cek_bdmk(_bdmk_seri(bddk_bdmk_kumulatif=False), onbellek=onbellek, session=oturum, bugun=date(2026, 9, 18))
    istek_sayisi = len(oturum.istekler)
    # Aynı tablo için ikinci kalem: yeni HTTP isteği atılmamalı.
    seri_cek_bdmk(
        _bdmk_seri(bddk_bdmk_kalem="XXI. DÖNEM NET KARI/ZARARI (XV+XX)", bddk_bdmk_kumulatif=False),
        onbellek=onbellek, session=oturum, bugun=date(2026, 9, 18),
    )
    assert len(oturum.istekler) == istek_sayisi


def test_seri_cek_bdmk_bulunamayan_kalemde_hata(_ilk_yil_2026):
    oturum = SahteBdmkOturum(_tam_gecmis())
    seri = _bdmk_seri(bddk_bdmk_kalem="OLMAYAN KALEM")
    with pytest.raises(RuntimeError, match="kalemi bulunamadı"):
        seri_cek_bdmk(seri, session=oturum, bugun=date(2026, 9, 18))



def test_haftalik_noktalar_cek_arada_bos_yanit_gelirse_hata():
    """Geriye sayfalarken boş yanıt = geçici sunucu hatası. Sessizce durmak,
    baştan yazılan CSV'de eski yılları silerdi."""
    pencereler = {
        "11.09.2026": {
            "XEkseni": ["4.09.2026", "11.09.2026"],
            "YEkseni": [862191.39, 867231.58],
        },
        "3.09.2026": {"XEkseni": [], "YEkseni": []},
    }
    oturum = SahteHaftalikOturum(pencereler)
    with pytest.raises(RuntimeError, match="geriye sayfalarken boş yanıt"):
        haftalik_noktalar_cek("2.0.1", 3, "10001", "11.09.2026", session=oturum)


# --- BDMK: okunamayan ay sessizce atlanmaz -----------------------------------


def test_bdmk_aylik_gecmis_cek_ara_aydaki_bos_tabloda_hata(_ilk_yil_2026):
    """Yayımlanmış son aydan (Temmuz) önce boş dönen bir ay (Nisan) eskiden
    atlanıyordu; CSV baştan yazıldığı için delik kalırdı."""
    aylar = _tam_gecmis()
    del aylar[(2026, 4)]
    oturum = SahteBdmkOturum(aylar)
    with pytest.raises(RuntimeError, match="2026-04 tablosu boş döndü.*son ay 2026-07"):
        bdmk_aylik_gecmis_cek("faktoring", 2, date(2026, 9, 18), session=oturum)


def test_bdmk_aylik_gecmis_cek_bilinen_bos_ay_hata_vermez(_ilk_yil_2026, monkeypatch):
    """Kaynağın gerçekten yayımlamadığı ay açık sabitle kayda geçirilirse atlanır."""
    monkeypatch.setattr("ingest.bddk.BDMK_BILINEN_BOS_AYLAR", frozenset({(2026, 4)}))
    aylar = _tam_gecmis()
    del aylar[(2026, 4)]
    oturum = SahteBdmkOturum(aylar)
    aylik = bdmk_aylik_gecmis_cek("faktoring", 2, date(2026, 9, 18), session=oturum)
    assert "2026-04-01" not in aylik
    assert "2026-01-01" in aylik


def test_bdmk_aylik_gecmis_cek_tablo_hic_yoksa_hata(_ilk_yil_2026):
    """TabloBasitGosterim'in olmadığı yanıt (hata sayfası/şablon değişikliği)
    eskiden "ay henüz yok" sayılıyordu."""
    aylar = _tam_gecmis()
    aylar[(2026, 3)] = "<html><body>Hata oluştu</body></html>"
    oturum = SahteBdmkOturum(aylar)
    with pytest.raises(RuntimeError, match="TabloBasitGosterim tablosu yok.*2026-03"):
        bdmk_aylik_gecmis_cek("faktoring", 2, date(2026, 9, 18), session=oturum)


def test_bdmk_aylik_gecmis_cek_satirlar_okunamazsa_hata(_ilk_yil_2026):
    """Veri satırı olan ama tek kalemi okunamayan tablo yayımlanmamış ay değildir."""
    aylar = _tam_gecmis()
    aylar[(2026, 5)] = """
<table id="TabloBasitGosterim"><tbody>
<tr><td>1</td><td>I. ESAS FAALİYET GELİRLERİ</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
"""
    oturum = SahteBdmkOturum(aylar)
    with pytest.raises(RuntimeError, match="hiçbir kalem okunamadı.*2026-05"):
        bdmk_aylik_gecmis_cek("faktoring", 2, date(2026, 9, 18), session=oturum)


def _iki_kalemli_html(net_kar: float | None, gelir: float) -> str:
    net_kar_satiri = (
        f"<tr><td>79</td><td>XXI. DÖNEM NET KARI/ZARARI (XV+XX)</td>"
        f"<td>0</td><td>0</td><td>{net_kar:,.0f}</td></tr>".replace(",", ".")
        if net_kar is not None else ""
    )
    return f"""
<table id="TabloBasitGosterim"><tbody>
<tr><td>1</td><td>I. ESAS FAALİYET GELİRLERİ</td><td>0</td><td>0</td><td>{gelir:,.0f}</td></tr>
{net_kar_satiri}
</tbody></table>
""".replace(",", ".")


def test_seri_cek_bdmk_kalem_ara_ayda_yoksa_hata(_ilk_yil_2026):
    """Tablo dolu ama kalem Mart'ta yok: eskiden o ay sessizce düşüyordu."""
    aylar = {(2026, ay): _iki_kalemli_html(1000 * ay, 5000) for ay in range(1, 8)}
    aylar[(2026, 3)] = _iki_kalemli_html(None, 5000)
    oturum = SahteBdmkOturum(aylar)
    with pytest.raises(RuntimeError, match=r"'XXI. DÖNEM NET KARI/ZARARI \(XV\+XX\)'.*okunamadı: 2026-03"):
        seri_cek_bdmk(_bdmk_seri(bddk_bdmk_kumulatif=False), session=oturum, bugun=date(2026, 9, 18))


def test_seri_cek_bdmk_kalem_ilk_ayindan_onceki_eksiklik_hata_vermez(_ilk_yil_2026, monkeypatch):
    """BDMK_KALEM_ILK_AY'da kayıtlı kalem (ör. 2021-09 yeniden numaralama)
    ilk ayından önce bulunmasa da hata vermez; seri o aydan başlar."""
    monkeypatch.setattr(
        "ingest.bddk.BDMK_KALEM_ILK_AY",
        {("faktoring", 2, "XXI. DÖNEM NET KARI/ZARARI (XV+XX)"): "2026-04-01"},
    )
    aylar = {(2026, ay): _iki_kalemli_html(1000 * ay, 5000) for ay in range(1, 8)}
    for ay in (1, 2, 3):
        aylar[(2026, ay)] = _iki_kalemli_html(None, 5000)
    oturum = SahteBdmkOturum(aylar)
    df = seri_cek_bdmk(_bdmk_seri(bddk_bdmk_kumulatif=False), session=oturum, bugun=date(2026, 9, 18))
    assert list(df["date"]) == [f"2026-{ay:02d}-01" for ay in range(4, 8)]
    assert list(df["value"]) == [4000, 5000, 6000, 7000]
