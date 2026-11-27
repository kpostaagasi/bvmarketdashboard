"""Migros Ticaret A.Ş. (BIST: MGROS) "Ara Dönem Faaliyet Raporu" PDF
istemcisi testleri."""

from types import SimpleNamespace

import pytest

from ingest.migros import (
    GECERLI_METRIKLER,
    _belge_metnini_getir,
    magaza_sayisini_ayikla,
    seri_cek,
)


class SahteYanit:
    def __init__(self, status_code=200, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class SahteOturum:
    def __init__(self, status_code=404, text=""):
        self.status_code = status_code
        self.text = text
        self.istenen = []

    def get(self, url, headers=None, timeout=None):
        self.istenen.append(url)
        return SahteYanit(status_code=self.status_code, text=self.text)


def mgros_seri(**kwargs):
    varsayilan = dict(id="perakende/mgros-toplam-magaza-sayisi", migros_metrik="toplam-magaza-sayisi")
    varsayilan.update(kwargs)
    return SimpleNamespace(**varsayilan)


def _rapor_satiri(baslik, yil, url):
    return (
        f'<td>{baslik}</td>\n    <td align="center">{yil}</td>\n'
        f'    <td align="center"><a href="{url}">PDF</a></td>'
    )


# --- Rapor listesi ---


def test_rapor_listesi_uc_baslik_bicimini_okur_araligi_bilerek_atlar():
    """Ölçülen üç başlık biçimi (2014+, 2013'teki baştaki boşluk, 2008'in
    "Migros Ara Dönem") okunur; "Aralık" satırı kapsam dışı olarak atlanır."""
    from ingest.migros import _rapor_listesi

    html = "\n".join([
        _rapor_satiri("Migros Ticaret Ara Dönem Faaliyet Raporu Eylül", 2026, "http://x/e26.pdf"),
        _rapor_satiri(" Migros Ticaret Ara Dönem Faaliyet Raporu Mart", 2013, "http://x/m13.pdf"),
        _rapor_satiri(" Migros Ticaret Ara Dönem Faaliyet Raporu Aralık", 2013, "http://x/a13.pdf"),
        _rapor_satiri("Migros Ara Dönem Faaliyet Raporu Haziran", 2008, "http://x/h08.pdf"),
    ])
    sonuc = _rapor_listesi(session=SahteOturum(200, text=html))
    assert sonuc == [
        {"tarih": "2026-09-01", "url": "http://x/e26.pdf"},
        {"tarih": "2013-03-01", "url": "http://x/m13.pdf"},
        {"tarih": "2008-06-01", "url": "http://x/h08.pdf"},
    ]


def test_rapor_listesi_taninmayan_ay_adinda_patlar():
    """Önceden tanınmayan ay adı sessizce atlanıyordu."""
    from ingest.migros import _rapor_listesi

    html = _rapor_satiri("Migros Ticaret Ara Dönem Faaliyet Raporu Ekim", 2026, "http://x/e.pdf")
    with pytest.raises(RuntimeError, match="Raporu Ekim' \\(2026\\) satırının ay adı tanınmıyor"):
        _rapor_listesi(session=SahteOturum(200, text=html))


def test_rapor_listesi_satiri_ayristirilamayan_baslikta_patlar():
    """Başlık hücresi var ama yıl/bağlantı hücresi şablonu değişmiş: önceki
    katı desen bu satırı sessizce düşürüyordu (2008/2013 satırları gibi)."""
    from ingest.migros import _rapor_listesi

    html = "\n".join([
        _rapor_satiri("Migros Ticaret Ara Dönem Faaliyet Raporu Eylül", 2026, "http://x/e26.pdf"),
        '<td>Migros Ticaret Ara Dönem Faaliyet Raporu Haziran</td><td>2026</td><td>yok</td>',
    ])
    with pytest.raises(RuntimeError, match="2 'Ara Dönem Faaliyet Raporu' başlığı var ama yalnızca 1 satır"):
        _rapor_listesi(session=SahteOturum(200, text=html))


def test_kapsamdaki_raporlar_aradaki_donem_satiri_yoksa_patlar():
    from ingest.migros import _kapsamdaki_raporlar

    raporlar = [
        {"tarih": "2026-03-01", "url": "a"},
        {"tarih": "2026-09-01", "url": "c"},
        {"tarih": "2012-09-01", "url": "eski"},
    ]
    with pytest.raises(RuntimeError, match="şu dönemlerin 'Ara Dönem Faaliyet Raporu' satırı yok: 2026-06"):
        _kapsamdaki_raporlar(raporlar, "2026-03-01", "deneme")


def test_kapsamdaki_raporlar_henuz_yayimlanmamis_son_donemi_beklemez():
    """Meşru durum: Eylül 2026 raporu henüz yayımlanmadı — liste Haziran'da
    bitiyor, kapsam öncesi raporlar ise elenir."""
    from ingest.migros import _kapsamdaki_raporlar

    raporlar = [
        {"tarih": "2026-06-01", "url": "b"},
        {"tarih": "2026-03-01", "url": "a"},
        {"tarih": "2012-09-01", "url": "eski"},
    ]
    sonuc = _kapsamdaki_raporlar(raporlar, "2026-03-01", "deneme")
    assert [r["url"] for r in sonuc] == ["b", "a"]


# --- Toplam mağaza sayısı ---


def test_belge_metnini_getir_404te_artik_patlar():
    """Önceden 404 None dönüp dönemi sessizce atlıyordu. Kapsamdaki hiçbir
    raporda link çürümesi yok; 404 yanlış URL'dir ve kırmızı kalmalıdır."""
    with pytest.raises(RuntimeError, match="HTTP 404"):
        _belge_metnini_getir("http://x/yok.pdf", {}, session=SahteOturum(404))


def test_seri_cek_kapsam_oncesi_raporu_hic_getirmez(monkeypatch):
    """2021 Mart öncesi (yurt dışı dahil tanım; 2012 Eylül'ün ölçülen 404'ü
    de burada) hiç taranmaz — sessiz atlama değil, açık kapsam."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "MAGAZA_ILK_DONEM", "2026-06-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [
            {"tarih": "2012-09-01", "url": "http://x/eski.pdf"},
            {"tarih": "2026-06-01", "url": "http://x/haz.pdf"},
        ],
    )
    istenen = []

    def sahte_getir(url, onbellek, session=None):
        istenen.append(url)
        return "Haziran 2026 sonu itibarıyla toplam mağaza sayısı 3.830 oldu."

    monkeypatch.setattr(migros_modul, "_belge_metnini_getir", sahte_getir)
    df = seri_cek(mgros_seri())
    assert istenen == ["http://x/haz.pdf"]
    assert list(df["date"]) == ["2026-06-01"]
    assert list(df["value"]) == [3830.0]


def test_seri_cek_cumlesi_okunamayan_raporda_patlar(monkeypatch):
    """Önceden 2021-2025 arası 15 rapor belge okunduğu halde böyle sessizce
    atlanıyordu; artık dönem ve URL adıyla yükselir."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "MAGAZA_ILK_DONEM", "2026-03-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [
            {"tarih": "2026-06-01", "url": "http://x/haz.pdf"},
            {"tarih": "2026-03-01", "url": "http://x/mar.pdf"},
        ],
    )
    icerikler = {
        "http://x/haz.pdf": "30 Haziran 2026 itibarıyla toplam\nmağaza sayısı 3.830 oldu.",
        "http://x/mar.pdf": "metin katmanı yok",
    }
    monkeypatch.setattr(
        migros_modul, "_belge_metnini_getir", lambda url, onbellek, session=None: icerikler[url]
    )
    with pytest.raises(RuntimeError, match="2026-03 Ara Dönem Faaliyet Raporu'nda toplam mağaza sayısı cümlesi okunamadı"):
        seri_cek(mgros_seri())


def test_magaza_sayisini_ayikla_detayli_dokum_kalibi():
    metin = (
        "Şirketimiz, 30 Haziran 2026 itibarıyla yurt içinde 7 coğrafi bölgede 2.220 Migros, "
        "1.186 Migros Jet, 157 Macrocenter, 109 Macrokiosk, 50 hipermarket, 24 Toptan, 80 Mion "
        "ve 4 Petimo mağazası olmak üzere toplam\n3.830 mağazaya ulaştı."
    )
    assert magaza_sayisini_ayikla(metin) == 3830.0


def test_magaza_sayisini_ayikla_ulasmistir_kalibi():
    """2021-2022 raporları "ulaşmıştır" diyor (ölçüldü 31 Mart 2021: 2.330)."""
    metin = (
        "Şirketimiz, 31 Mart 2021 itibarıyla yurt içinde 7 coğrafi bölgede 1.315 süpermarket, "
        "872 Migros Jet, 55 hipermarket, 62 Macrocenter, 23 Toptan mağazası olmak üzere toplam "
        "2.330 mağazaya ulaşmıştır."
    )
    assert magaza_sayisini_ayikla(metin) == 2330.0


def test_magaza_sayisini_ayikla_ozet_cumle_kalibi():
    """Bazı çeyreklerde yalnızca kısa özet cümlesi var (ölçülen ikinci biçim)."""
    metin = "30 Eylül 2025 itibarıyla toplam\nmağaza sayısı 3.730 oldu."
    assert magaza_sayisini_ayikla(metin) == 3730.0


def test_magaza_sayisini_ayikla_ekli_ozet_kaliplari():
    """2022-2025 raporlarının ölçülen özet biçimleri (sayıya ek gelir)."""
    assert magaza_sayisini_ayikla("Şirketin toplam mağaza sayısı 2.681'e yükseldi.") == 2681.0
    assert magaza_sayisini_ayikla("Şirketin toplam mağaza sayısı 3.100'e ulaştı.") == 3100.0
    assert magaza_sayisini_ayikla(
        "Şirketin toplam mağaza sayısı 31 Mart 2025 itibarıyla 3.642'ye ulaştı."
    ) == 3642.0
    assert magaza_sayisini_ayikla(
        "30 Haziran 2025 itibarıyla, Migros'un ülke genelinde toplam mağaza sayısı 3.683 oldu."
    ) == 3683.0


def test_magaza_sayisini_ayikla_parantezli_deprem_notunda_baslik_rakamini_alir():
    """2023 Mart: başlık rakamı (2.991) alınır, parantezdeki 2.981 değil."""
    metin = (
        "Şirketin toplam mağaza sayısı 2.991'e (deprem bölgesinde kalıcı olarak kapanan 10 "
        "mağaza dahil edilmediğinde 2.981'e) yükseldi."
    )
    assert magaza_sayisini_ayikla(metin) == 2991.0


def test_magaza_sayisini_ayikla_yurt_disi_dahil_tanimda_patlar():
    metin = (
        "Şirketimiz, 30 Eylül 2020 itibarıyla yurt içinde 7 coğrafi bölgede 1.263 süpermarket "
        "ile yurt dışında iştirakleri vasıtasıyla Kazakistan'da 12 Ramstore olmak üzere toplam "
        "2.301 mağazaya ulaşmıştır."
    )
    with pytest.raises(RuntimeError, match="yurt dışı mağazaları da içeriyor"):
        magaza_sayisini_ayikla(metin)


def test_magaza_sayisini_ayikla_iki_cumle_celisirse_patlar():
    metin = (
        "Şirketin toplam mağaza sayısı 2.681'e yükseldi. Şirketimiz, 30 Haziran 2022 itibarıyla "
        "yurt içinde 7 coğrafi bölgede 1.504 Migros mağazası olmak üzere toplam 2.680 mağazaya "
        "ulaşmıştır."
    )
    with pytest.raises(RuntimeError, match="iki cümlede farklı"):
        magaza_sayisini_ayikla(metin)


def test_magaza_sayisini_ayikla_eslesme_yoksa_none():
    assert magaza_sayisini_ayikla("ilgisiz içerik") is None


def test_seri_cek_bilinmeyen_metrik_hata_verir():
    with pytest.raises(RuntimeError, match="Bilinmeyen migros_metrik"):
        seri_cek(mgros_seri(migros_metrik="olmayan"))


def test_seri_cek_dogru_seriyi_uretir(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "MAGAZA_ILK_DONEM", "2026-03-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [
            {"tarih": "2026-06-01", "url": "http://x/haz.pdf"},
            {"tarih": "2026-03-01", "url": "http://x/mar.pdf"},
        ],
    )
    icerikler = {
        "http://x/haz.pdf": "30 Haziran 2026 itibarıyla toplam\nmağaza sayısı 3.830 oldu.",
        "http://x/mar.pdf": "31 Mart 2026 itibarıyla toplam\nmağaza sayısı 3.812 oldu.",
    }
    monkeypatch.setattr(
        migros_modul, "_belge_metnini_getir",
        lambda url, onbellek, session=None: icerikler[url],
    )
    df = seri_cek(mgros_seri())
    assert list(df["date"]) == ["2026-03-01", "2026-06-01"]
    assert list(df["value"]) == [3812.0, 3830.0]


def test_gecerli_metrikler_tek_seriyi_kapsar():
    assert GECERLI_METRIKLER == {"toplam-magaza-sayisi"}


# --- Format bazında açılışlar ---

# Gövdeler canlı raporlardan (2026-11-27): kalemlerin toplamı cümlenin
# toplamına eşit (84+41+14+11+2+2=154; 61+34+7+9+2+2=115).
_ACILIS_2026_09 = (
    "1 Ocak – 30 Eylül 2026 döneminde 84 adet Migros, 41 adet Migros Jet, 14 adet Macrocenter, "
    "11 adet Macrokiosk,\nkişisel bakım mağazacılığı formatında 2 adet Mion ve evcil hayvan mama "
    "ve aksesuarları formatında 2 adet\nPetimo olmak üzere toplam 154 yeni mağaza açılmıştır."
)
_ACILIS_2026_06 = (
    "1 Ocak – 30 Haziran 2026 döneminde 61 adet Migros, 34 adet Migros Jet, 7 adet Macrocenter, "
    "9 adet Macrokiosk,\nkişisel bakım mağazacılığı formatında 2 adet Mion ve evcil hayvan mama "
    "ve aksesuarları formatında 2 adet\nPetimo olmak üzere toplam 115 yeni mağaza açılmıştır."
)


def test_format_acilislari_ceyreklige_cevrilir(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "ACILIS_ILK_DONEM", "2026-06-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [
            {"tarih": "2026-09-01", "url": "e"},
            {"tarih": "2026-06-01", "url": "h"},
            {"tarih": "2023-06-01", "url": "eski"},
        ],
    )
    icerik = {"e": _ACILIS_2026_09, "h": _ACILIS_2026_06}
    monkeypatch.setattr(
        migros_modul, "_belge_metnini_getir", lambda url, onbellek, session=None: icerik[url]
    )
    df = seri_cek(mgros_seri(migros_metrik="toplam-yeni-magaza-acilis"))
    # 2026-06 ilk kapsam dönemi: önceki çeyrek (Mart) kapsam dışı -> meşru
    # olarak çeyreğe çevrilemez; 2026-09 = 154 - 115.
    assert list(df["date"]) == ["2026-09-01"]
    assert list(df["value"]) == [39.0]


def test_format_acilislari_cumlesi_okunamayan_raporda_patlar(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "ACILIS_ILK_DONEM", "2026-06-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [{"tarih": "2026-09-01", "url": "e"}, {"tarih": "2026-06-01", "url": "h"}],
    )
    icerik = {"e": "şablon değişti", "h": _ACILIS_2026_06}
    monkeypatch.setattr(
        migros_modul, "_belge_metnini_getir", lambda url, onbellek, session=None: icerik[url]
    )
    with pytest.raises(RuntimeError, match="2026-09 Ara Dönem Faaliyet Raporu'nda yeni mağaza açılış cümlesi okunamadı"):
        seri_cek(mgros_seri(migros_metrik="mion-format-magaza-acilis"))


def test_kumulatif_ceyrek_taranan_raporda_olmayan_metrikte_patlar():
    from ingest.migros import _kumulatif_ceyregi_cevir

    # Ayıklayıcı her raporda dört formatı döndüğü için eksik anahtar bir
    # okuma hatasıdır — yılın İLK raporunda eksik olsa bile (savunma katmanı).
    with pytest.raises(RuntimeError, match="'migros-jet-format-magaza-acilis' 2026-03 raporunda yok"):
        _kumulatif_ceyregi_cevir(
            {"2026-06-01": 20.0, "2026-09-01": 30.0},
            "migros-jet-format-magaza-acilis",
            ["2026-03-01", "2026-06-01", "2026-09-01"],
        )


def test_kumulatif_ceyrek_negatif_farkta_patlar():
    from ingest.migros import _kumulatif_ceyregi_cevir

    with pytest.raises(RuntimeError, match="'mion-format-magaza-acilis' 2026-09 çeyrek farkı negatif"):
        _kumulatif_ceyregi_cevir(
            {"2026-03-01": 2.0, "2026-06-01": 5.0, "2026-09-01": 4.0},
            "mion-format-magaza-acilis",
            ["2026-03-01", "2026-06-01", "2026-09-01"],
        )


def test_kumulatif_ceyrek_ilk_donem_ceyrege_cevrilemez():
    from ingest.migros import _kumulatif_ceyregi_cevir

    # ACILIS_ILK_DONEM (2023 Eylül) 9 aylık kümülatif: önceki çeyrek raporu
    # cümleyi taşımadığı için çeyreğe çevrilemez; sonraki yıl normal.
    sonuc = _kumulatif_ceyregi_cevir(
        {"2023-09-01": 17.0, "2024-03-01": 8.0, "2024-06-01": 15.0},
        "mion-format-magaza-acilis",
        ["2023-09-01", "2024-03-01", "2024-06-01"],
    )
    assert sonuc == {"2024-03-01": 8.0, "2024-06-01": 7.0}


def test_format_acilislari_1c_raporunda_yeniden_adlandirma_patlar():
    """Yılın ilk raporunda "Migros Jet" -> "Jet" olursa format seriden
    sessizce düşmez: tanınmayan ad yükselir."""
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Jet, 2 adet Macrocenter, "
        "2 adet Macrokiosk ve kişisel\nbakım mağazacılığı formatında 2 adet Mion olmak üzere "
        "toplam 51 yeni mağaza açılmıştır."
    )
    with pytest.raises(RuntimeError, match="tanınmayan format adı 'Jet'"):
        format_acilislarini_ayikla(metin)


def test_format_acilislari_bilinmeyen_format_patlar():
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Migros Jet, 6 adet Mopaş "
        "olmak üzere toplam 51 yeni mağaza açılmıştır."
    )
    with pytest.raises(RuntimeError, match="tanınmayan format adı 'Mopaş'"):
        format_acilislarini_ayikla(metin)


def test_format_acilislari_toplam_uyusmazliginda_patlar():
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Migros Jet olmak üzere "
        "toplam 51 yeni mağaza açılmıştır."
    )
    with pytest.raises(RuntimeError, match="format kalemlerinin toplamı 45, cümlenin toplamı 51"):
        format_acilislarini_ayikla(metin)


def test_format_acilislari_kaleme_baglanamayan_sayida_patlar():
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Migros Jet ve Macrocenter (6) "
        "olmak üzere toplam 51 yeni mağaza açılmıştır."
    )
    with pytest.raises(RuntimeError, match="format kalemine bağlanamayan sayı"):
        format_acilislarini_ayikla(metin)


def test_format_acilislari_iki_kez_gecen_formatta_patlar():
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Migros Jet, 6 adet Migros "
        "olmak üzere toplam 51 yeni mağaza açılmıştır."
    )
    with pytest.raises(RuntimeError, match="'Migros' formatı iki kez geçiyor"):
        format_acilislarini_ayikla(metin)


def test_format_acilislari_canli_govdenin_tamami_okunur():
    from ingest.migros import format_acilislarini_ayikla

    assert format_acilislarini_ayikla(_ACILIS_2026_09) == {
        "toplam-yeni-magaza-acilis": 154.0,
        "migros-format-magaza-acilis": 84.0,
        "migros-jet-format-magaza-acilis": 41.0,
        "macrocenter-format-magaza-acilis": 14.0,
        "mion-format-magaza-acilis": 2.0,
    }


def test_format_acilislari_2023_eylul_adetsiz_govde_okunur():
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 30 Eylül 2023 döneminde 195 Migros, 105 Migros Jet, 17 Mion kozmetik mağaza, "
        "11 Macrocenter, 9 Macrokiosk, 6\nMinigros ve 1 Toptan olmak üzere toplam 344 yeni "
        "mağaza açılmıştır."
    )
    assert format_acilislarini_ayikla(metin) == {
        "toplam-yeni-magaza-acilis": 344.0,
        "migros-format-magaza-acilis": 195.0,
        "migros-jet-format-magaza-acilis": 105.0,
        "macrocenter-format-magaza-acilis": 11.0,
        "mion-format-magaza-acilis": 17.0,
    }


def test_format_acilislari_gecmeyen_format_toplam_tutunca_sifir_olur():
    """Toplam denetimi geçince gövdede geçmeyen bilinen format kanıtla 0
    açılıştır (yayımlanan toplamdan türetilir) — delik bırakmaz."""
    from ingest.migros import format_acilislarini_ayikla

    metin = (
        "1 Ocak – 31 Mart 2026 döneminde 31 adet Migros, 14 adet Migros Jet olmak üzere "
        "toplam 45 yeni mağaza açılmıştır."
    )
    assert format_acilislarini_ayikla(metin) == {
        "toplam-yeni-magaza-acilis": 45.0,
        "migros-format-magaza-acilis": 31.0,
        "migros-jet-format-magaza-acilis": 14.0,
        "macrocenter-format-magaza-acilis": 0.0,
        "mion-format-magaza-acilis": 0.0,
    }


def test_format_acilislari_gecmeyen_format_seri_cekte_sifir_ceyrek_olur(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "ACILIS_ILK_DONEM", "2026-06-01")
    monkeypatch.setattr(
        migros_modul, "_rapor_listesi",
        lambda session=None: [{"tarih": "2026-09-01", "url": "e"}, {"tarih": "2026-06-01", "url": "h"}],
    )
    # Haziran'da Mion hiç açılmamış (gövdede yok, toplam yine tutuyor),
    # Eylül'de 2 açılmış: Eylül çeyreği 2 - 0 = 2, seri delik bırakmaz.
    haziran_mionsuz = (
        "1 Ocak – 30 Haziran 2026 döneminde 61 adet Migros, 34 adet Migros Jet, 7 adet "
        "Macrocenter, 9 adet Macrokiosk ve 2 adet Petimo olmak üzere toplam 113 yeni mağaza "
        "açılmıştır."
    )
    icerik = {"e": _ACILIS_2026_09, "h": haziran_mionsuz}
    monkeypatch.setattr(
        migros_modul, "_belge_metnini_getir", lambda url, onbellek, session=None: icerik[url]
    )
    df = seri_cek(mgros_seri(migros_metrik="mion-format-magaza-acilis"))
    assert list(df["date"]) == ["2026-09-01"]
    assert list(df["value"]) == [2.0]


# --- Yatırımcı sunumu listesi / PDF ---


def test_sunum_listesi_baglantisiz_satirda_patlar():
    from ingest.migros import _sunum_listesi

    html = (
        '<tr><td>2Ç 2026 Yatırımcı Sunumu</td><td><a href="http://x/2c26.pdf">PDF</a></td></tr>\n'
        "<tr><td>3Ç 2026 Yatırımcı Sunumu</td><td>yakında</td></tr>"
    )
    with pytest.raises(RuntimeError, match="'3Ç 2026 Yatırımcı Sunumu' satırında PDF bağlantısı ayrıştırılamadı"):
        _sunum_listesi(session=SahteOturum(200, text=html))


def test_sunum_listesi_kapsamdaki_yilin_bozuk_basliginda_patlar():
    from ingest.migros import _sunum_listesi

    html = (
        '<tr><td>2Ç 2026 Yatırımcı Sunumu</td><td><a href="http://x/2c26.pdf">PDF</a></td></tr>\n'
        '<tr><td>3Ç 2026 Yatırımcı Sunumu (Revize)</td><td><a href="http://x/3c26.pdf">PDF</a></td></tr>'
    )
    with pytest.raises(RuntimeError, match=r"'3Ç 2026 Yatırımcı Sunumu \(Revize\)' satırı kapsamdaki"):
        _sunum_listesi(session=SahteOturum(200, text=html))


def test_sunum_listesi_kapsam_disi_sunum_ailelerini_atlar():
    from ingest.migros import _sunum_listesi

    html = (
        '<tr><td>CMD Sunumu</td><td><a href="http://x/cmd.pdf">PDF</a></td></tr>\n'
        '<tr><td>9A 2016 Migros Yatırımcı Sunumu</td><td><a href="http://x/9a16.pdf">PDF</a></td></tr>\n'
        '<tr><td>3Ç 2019 Şirket Sunumu</td><td><a href="http://x/3c19.pdf">PDF</a></td></tr>\n'
        '<tr><td>2Ç 2026 Yatırımcı Sunumu</td><td><a href="http://x/2c26.pdf">PDF</a></td></tr>'
    )
    sonuc = _sunum_listesi(session=SahteOturum(200, text=html))
    assert sonuc == [{"yil": 2026, "ceyrek": 2, "url": "http://x/2c26.pdf"}]


def test_sunum_pdfsini_getir_404te_patlar():
    from ingest.migros import _sunum_pdfsini_getir

    with pytest.raises(RuntimeError, match="HTTP 404"):
        _sunum_pdfsini_getir("http://x/yok.pdf", {}, session=SahteOturum(404))


# --- 2Ç 2026 "Online Operasyonlar" sayfası ---
#
# Koordinatlar 2Ç 2026 sunumunun s.24'ünden ÖLÇÜLMÜŞTÜR (2026-09-30):
# dört grafik, her biri 2Ç24/2Ç25/2Ç26 sütunlu, "Çeyreksel Öne
# Çıkanlar" şeridi + grafik başlıkları + değer kutuları + en alttaki
# "NÇ YYYY" eksen etiketleri. Test bu geometriyi birebir taklit eder.

_SAYFA24_METIN = (
    "Online Operasyonlar\nEnflasyondan (TÜFE) arındırılmış\nÇeyreksel Öne Çıkanlar\n"
    "28,5 milyar TL Migros One GMV\n5,0 milyar TL Migros Yemek GMV\n"
    "Aktif kullanıcı Migros One GMV Günlük Sipariş Migros’ta e- ticaret payı sayısı(2)\n"
    "(milyar TL) (milyon)\n"
    "2Ç 2024 2Ç 2025 2Ç 2026\n"
)


def _sayfa24_kelimeler(ceyrekler):
    """s.24 geometrisini verilen üç çeyrek için üretir. `ceyrekler`
    soldan sağa (geçmiş -> sunumun kendi çeyreği)."""
    eksen_topu = 420.0
    kelimeler = []
    # üstteki "Çeyreksel Öne Çıkanlar" şeridi — aynı anahtar sözcükleri
    # burada da geçiyor, ayrıştırıcı bunları elemesi gerekiyor
    kelimeler += [
        {"text": "28,5", "top": 123.0, "x0": 90.0, "x1": 117.0},
        {"text": "GMV", "top": 138.3, "x0": 158.5, "x1": 187.5},
        {"text": "GMV", "top": 145.5, "x0": 290.6, "x1": 319.7},
        {"text": "6,6", "top": 115.8, "x0": 603.6, "x1": 623.5},
        {"text": "%23,1", "top": 115.8, "x0": 457.1, "x1": 492.3},
        {"text": "240", "top": 184.2, "x0": 428.8, "x1": 454.2},
        # sağdaki dipnot şeridinde de "2Ç" geçiyor
        {"text": "2Ç", "top": 262.1, "x0": 865.3, "x1": 877.8},
        {"text": "677", "top": 260.6, "x0": 746.6, "x1": 767.9},
    ]
    # grafik başlıkları
    kelimeler += [
        {"text": "Aktif", "top": 243.7, "x0": 598.8, "x1": 623.4},
        {"text": "GMV", "top": 248.2, "x0": 155.5, "x1": 179.9},
        {"text": "Sipariş", "top": 248.5, "x0": 311.5, "x1": 345.6},
    ]
    # değer kutuları: (metin, top, merkez) — sütun merkezleri ölçülen
    # eksen etiketi merkezlerine göre
    kutular = [
        (("18,6", 321.3, 94.4), ("23,5", 300.5, 133.6), ("28,5", 279.3, 173.4),
         ("1,9", 337.8, 96.1), ("2,9", 319.7, 134.0), ("5,0", 299.9, 173.8)),
        (("226k", 316.6, 266.9), ("263k", 303.2, 307.0), ("327k", 279.9, 347.0),
         ("45k", 335.3, 266.1), ("57k", 322.9, 306.8), ("91k", 299.4, 348.0)),
        (("18,5", 303.6, 433.7), ("20,7", 292.4, 472.4), ("23,1", 280.2, 513.6)),
        (("5,1", 305.5, 597.1), ("5,8", 292.8, 636.1), ("6,6", 278.2, 675.9)),
    ]
    for grup in kutular:
        for metin, top, merkez in grup:
            kelimeler.append({"text": metin, "top": top, "x0": merkez - 6, "x1": merkez + 6})
    for x0, (ceyrek, yil) in zip((78.7, 119.0, 158.7, 252.4, 292.7, 332.4, 417.8, 458.1,
                                  497.9, 580.8, 621.1, 660.8), ceyrekler * 4):
        kelimeler += [
            {"text": f"{ceyrek}Ç", "top": eksen_topu, "x0": x0, "x1": x0 + 10.5},
            {"text": str(yil), "top": eksen_topu - 0.4, "x0": x0 + 12.8, "x1": x0 + 25.3},
        ]
    return kelimeler


class SahteSayfa:
    def __init__(self, metin, kelimeler):
        self._metin = metin
        self._kelimeler = kelimeler

    def extract_text(self):
        return self._metin

    def extract_words(self):
        return self._kelimeler


class SahtePdf:
    def __init__(self, sayfalar):
        self.pages = sayfalar

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SahtePdfplumber:
    def __init__(self, sayfalar):
        self._sayfalar = sayfalar

    def open(self, *a, **k):
        return SahtePdf(self._sayfalar)


def _sayfa24_kur(ceyrekler):
    import ingest.migros as migros_modul

    sayfa = SahteSayfa(_SAYFA24_METIN, _sayfa24_kelimeler(ceyrekler))
    return SahtePdfplumber([sayfa])


def test_online_operasyonlari_gmv_ve_kullaniciyi_okur(monkeypatch):
    """2Ç 2026 sunumu s.24: GMV 28,5 milyar TL, aktif kullanıcı 6,6 mn.
    Her ikisi de sayfanın SAĞINDAKİ (kendi çeyrek) sütunundan."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", _sayfa24_kur([(2, 2024), (2, 2025), (2, 2026)]))
    sonuc = migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 2)
    assert sonuc["migros-one-gmv"] == 28.5
    assert sonuc["migros-one-aktif-kullanici"] == 6.6


def test_online_operasyonlari_siparis_gunlukten_ceyrek_toplam_turetir(monkeypatch):
    """BİRİM TUZAĞI: sayfa GÜNLÜK ortalama veriyor (2Ç 2026: 327k/gün),
    seri ise ÇEYREKLİK TOPLAM tutuyor (birim "milyon"). Çarpan sabit 90/91
    değil, eksen etiketindeki çeyreğin GERÇEK gün sayısından gelir:
    2Ç 2026 = 30+31+30 = 91 gün -> 327.000 x 91 / 1e6 = 29,757 mn.
    1Ç 2026 olsaydı (31+28+31 = 90 gün) 29,43 mn çıkardı — çarpan
    etiketten türetildiği için iki çeyrek birbirine karışmaz."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", _sayfa24_kur([(2, 2024), (2, 2025), (2, 2026)]))
    deger = migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 2)["migros-one-siparis-sayisi"]
    assert deger == pytest.approx(327_000 * 91 / 1e6)
    assert deger == pytest.approx(29.757)
    assert deger != pytest.approx(327.0)  # günlük ham değer sızmamalı

    # Etiketler sunumun kendi çeyreğiyle uyuşmuyorsa (etiket 2Ç 2026,
    # sunum 1Ç 2026) yanlış çeyreğe yazmaktansa patlanır (önceden
    # sessizce None dönüyordu).
    with pytest.raises(RuntimeError, match="son sütunu 2Ç 2026, sunumun kendi çeyreği değil"):
        migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 1)


def test_online_operasyonlari_gun_sayisi_etiketten_turetilir(monkeypatch):
    """Aynı sayfa, kendi çeyreği 3Ç 2026 (Temmuz+Ağustos+Eylül = 92 gün)
    olarak etiketlendiğinde çarpan değişir — sabit gün sayısı değil."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", _sayfa24_kur([(1, 2026), (2, 2026), (3, 2026)]))
    deger = migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 3)["migros-one-siparis-sayisi"]
    assert deger == pytest.approx(327_000 * 92 / 1e6)


def test_ceyrek_gun_sayisi_gercek_takvim_gunleri():
    import ingest.migros as migros_modul

    gun = migros_modul._ceyrek_gun_sayisi
    assert [gun(2026, c) for c in (1, 2, 3, 4)] == [90, 91, 92, 92]
    assert gun(2024, 4) == 92  # artık yıl: 30+31+30+31
    assert gun(2025, 1) == 90


def test_online_operasyonlari_sayfa_yoksa_none(monkeypatch):
    """2Ç 2026 öncesi sunumların hiçbirinde bu sayfa yok (ölçüldü:
    2Ç 2025 sunumunda 'Online Operasyonlar' geçmiyor) — None döner."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(
        migros_modul, "pdfplumber",
        SahtePdfplumber([SahteSayfa("Online ve Dijital Ödeme Çözümleri", [])]),
    )
    assert migros_modul.online_operasyonlarini_ayikla(b"x", 2025, 2) is None


def test_ekosistem_izgarasi_sayfa_var_deger_sayisi_tutmazsa_patlar(monkeypatch):
    """Sayfa BULUNDU ama ızgara okunamadı: önceden None dönüp beş
    çeyreği sessizce düşürüyordu. Sayfanın hiç olmaması (2Ç26+) ayrı ve
    meşru durumdur, aşağıdaki teste bakın."""
    import ingest.migros as migros_modul

    kelimeler = [{"text": "Aktif", "top": 189.0, "x0": 44.0, "x1": 90.0}]
    kelimeler += [{"text": "6,3", "top": 255.0, "x0": 138.0 + 20 * i, "x1": 150.0 + 20 * i} for i in range(7)]
    sayfa = SahteSayfa("Migros Dijital Ekosistemi Performans Göstergeleri", kelimeler)
    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([sayfa]))
    with pytest.raises(RuntimeError, match="1Ç 2026 sunumunda ekosistem ızgarası sayfası var ama 30 yerine 7 değer"):
        migros_modul.ekosistem_izgarasini_ayikla(b"x", 2026, 1)


def test_ekosistem_izgarasi_sayfa_yoksa_none(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa("Online Operasyonlar", [])]))
    assert migros_modul.ekosistem_izgarasini_ayikla(b"x", 2026, 2) is None


def test_seri_cek_yeni_sayfadan_ucuncu_ceyrek_noktasini_yazar(monkeypatch):
    """Entegrasyon: 2Ç 2026 sunumu yayımladı, eski ızgara yok -> seri
    1Ç 2026'da kesilmemeli, 2Ç 2026 noktasını almalı."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(
        migros_modul, "_sunum_listesi",
        lambda session=None: [{"yil": 2026, "ceyrek": 2, "url": "http://x/2c26.pdf"}],
    )
    monkeypatch.setattr(migros_modul, "_sunum_pdfsini_getir", lambda url, onbellek, session=None: b"pdf")
    monkeypatch.setattr(migros_modul, "pdfplumber", _sayfa24_kur([(2, 2024), (2, 2025), (2, 2026)]))

    df = seri_cek(
        SimpleNamespace(
            id="perakende/mgros-one-siparis-sayisi", migros_metrik="migros-one-siparis-sayisi"
        )
    )
    assert list(df["date"]) == ["2026-04-01"]
    assert list(df["value"]) == [pytest.approx(29.757)]


# --- Online Operasyonlar: sayfa tanıma ve okunamama ---


def test_online_operasyonlari_ifade_ilk_satir_degilse_sayfa_sayilmaz(monkeypatch):
    """İfade İçindekiler'de, bölüm ayracında ("Online | Operasyonlar | &")
    ve "Online Operasyonlar Daha Verimli" gibi başka slaytlarda da geçiyor
    (ölçüldü 2023-2025 sunumları); 2Ç25'in "Online Operations" ayracı da
    artık eşleşmez. Bunlar hedef sayfa değildir -> None (patlamaz)."""
    import ingest.migros as migros_modul

    sayfalar = [
        SahteSayfa("İçindekiler\nBüyüme\nOnline Operasyonlar & Stratejik Gelişmeler", []),
        SahteSayfa("Online\nOperasyonlar\n&\nStratejik\nGelişmeler", []),
        SahteSayfa("Online Operasyonlar Daha Verimli\nPerakende Brüt Ticaret Hacmi", []),
        SahteSayfa("Online\nOperations\n&\nStrategy\nUpdate", []),
    ]
    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber(sayfalar))
    assert migros_modul.online_operasyonlarini_ayikla(b"x", 2025, 2) is None


def test_online_operasyonlari_deger_kutusu_yoksa_patlar(monkeypatch):
    import ingest.migros as migros_modul

    kelimeler = [
        k for k in _sayfa24_kelimeler([(2, 2024), (2, 2025), (2, 2026)]) if k["text"] != "6,6"
    ]
    monkeypatch.setattr(
        migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(_SAYFA24_METIN, kelimeler)])
    )
    with pytest.raises(RuntimeError, match="'migros-one-aktif-kullanici' için 2Ç 2026 sütununda değer kutusu yok"):
        migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 2)


def test_online_operasyonlari_baslik_eksikse_patlar(monkeypatch):
    import ingest.migros as migros_modul

    kelimeler = [
        k for k in _sayfa24_kelimeler([(2, 2024), (2, 2025), (2, 2026)])
        if not (k["text"] == "Sipariş")
    ]
    monkeypatch.setattr(
        migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(_SAYFA24_METIN, kelimeler)])
    )
    with pytest.raises(RuntimeError, match="grafik başlığı bulunamadı: \\['migros-one-siparis-sayisi'\\]"):
        migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 2)


def test_online_operasyonlari_dipnotlu_baslik_ve_ust_seritte_dogru_bandi_secer(monkeypatch):
    """1Ç26 s.16 (ölçüldü): başlık "Sipariş(2)" diye çıkıyor ve üstteki
    şerit de iki anahtar taşıyor; en çok FARKLI anahtarı taşıyan bant seçilir."""
    import ingest.migros as migros_modul

    kelimeler = []
    for k in _sayfa24_kelimeler([(2, 2024), (2, 2025), (2, 2026)]):
        k = dict(k)
        if k["text"] == "Sipariş":
            k["text"] = "Sipariş(2)"
        kelimeler.append(k)
    # Şeride ikinci bir anahtar ekle: şerit artık {GMV, Sipariş} taşıyor.
    kelimeler.append({"text": "Sipariş(2)", "top": 140.0, "x0": 400.0, "x1": 440.0})
    monkeypatch.setattr(
        migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(_SAYFA24_METIN, kelimeler)])
    )
    sonuc = migros_modul.online_operasyonlarini_ayikla(b"x", 2026, 2)
    assert sonuc["migros-one-gmv"] == 28.5
    assert sonuc["migros-one-aktif-kullanici"] == 6.6
    assert sonuc["migros-one-siparis-sayisi"] == pytest.approx(29.757)


# --- Moneypay sayfası ---


def test_moneypay_sayfa_var_sayi_okunamazsa_patlar(monkeypatch):
    import ingest.migros as migros_modul

    sayfa = SahteSayfa("Fintek Operasyonları: Moneypay\nKayıtlı kullanıcı sayısı\nçok", [])
    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([sayfa]))
    with pytest.raises(RuntimeError, match="Moneypay' sayfası var ama kayıtlı kullanıcı sayısı"):
        migros_modul._moneypay_kayitli_kullanici_ayikla(b"x")


def test_moneypay_sayfa_yoksa_none(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa("Net Kar", [])]))
    assert migros_modul._moneypay_kayitli_kullanici_ayikla(b"x") is None


# --- 3Ç 2026 "Migros Ekosistemi Öne Çıkanlar" sayfası ---

# 3Ç 2026 sunumu s.12'nin pdfplumber metni (ölçüldü 2026-11-27, kısaltılmış).
_SAYFA12_METIN = (
    "Migros Ekosistemi Öne Çıkanlar\nOperasyonel Gelişmeler 5/5\n12\n"
    "e-Ticaret İş Kolu Fintek\nMigros One Moneypay\n"
    "3Ç26’da reel GMV (Brüt İşlem Hacmi) 3Ç26’da ödeme hacminde (TPV) reel\n+%17 +%73\n"
    "büyümesi büyüme\nMigros One günlük sipariş sayısında\n+%19 +%55\n"
    "günlük işlem adedinde 3Ç25’e göre artış\n3Ç25’e göre artış, 317 bine ulaştı\n"
    "kayıtlı kullanıcı sayısında yıllık artış ,\n100 bin +1,3 mn\n"
    "9A26’da, 100 bin olan 2026\n5,7 milyona ulaştı\nbeklentisiyle uyumlu\n"
)


def test_one_cikanlar_siparis_ve_moneypay_okur(monkeypatch):
    """317 bin/gün x 92 gün (3Ç) = 29,164 mn; Moneypay 5,7 mn. Çapraz
    kontrol: 3Ç25 24,5 mn x 1,19 ≈ 29,2; 4,4 + 1,3 = 5,7."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(_SAYFA12_METIN, [])]))
    sonuc = migros_modul.ekosistem_one_cikanlarini_ayikla(b"x", 2026, 3)
    assert sonuc["migros-one-siparis-sayisi"] == pytest.approx(317_000 * 92 / 1e6)
    assert sonuc["moneypay-kayitli-kullanici"] == 5.7
    assert set(sonuc) == {"migros-one-siparis-sayisi", "moneypay-kayitli-kullanici"}


def test_one_cikanlar_sayfa_yoksa_none(monkeypatch):
    """2Ç26'daki "Çeyreksel Öne Çıkanlar: Migros Ekosistemi" farklı sıra -> hedef değil."""
    import ingest.migros as migros_modul

    sayfa = SahteSayfa("Çeyreksel Öne Çıkanlar: Migros Ekosistemi\n2Ç 2026", [])
    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([sayfa]))
    assert migros_modul.ekosistem_one_cikanlarini_ayikla(b"x", 2026, 2) is None


def test_one_cikanlar_kendi_ceyrek_etiketi_yoksa_patlar(monkeypatch):
    import ingest.migros as migros_modul

    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(_SAYFA12_METIN, [])]))
    with pytest.raises(RuntimeError, match="kendi çeyrek etiketi \\('4Ç26'\\) yok"):
        migros_modul.ekosistem_one_cikanlarini_ayikla(b"x", 2026, 4)


def test_one_cikanlar_cumle_okunamazsa_patlar(monkeypatch):
    import ingest.migros as migros_modul

    metin = _SAYFA12_METIN.replace("5,7 milyona ulaştı", "5,7 milyon oldu")
    monkeypatch.setattr(migros_modul, "pdfplumber", SahtePdfplumber([SahteSayfa(metin, [])]))
    with pytest.raises(RuntimeError, match="'moneypay-kayitli-kullanici' cümlesi okunamadı"):
        migros_modul.ekosistem_one_cikanlarini_ayikla(b"x", 2026, 3)


# --- Dijital seriler: delik denetimi ---


def test_dijital_bosluk_denetimi_aradaki_eksik_ceyrekte_patlar():
    from ingest.migros import _dijital_bosluklarini_denetle

    birlesik = {"migros-one-siparis-sayisi": {"2025-10-01": 27.1, "2026-04-01": 29.8}}
    with pytest.raises(RuntimeError, match="'migros-one-siparis-sayisi': .*okunamadı: 1Ç 2026"):
        _dijital_bosluklarini_denetle(birlesik, 2026, 2)


def test_dijital_bosluk_denetimi_son_sunumun_ceyregi_eksikse_patlar():
    """3Ç26 sunumu listelendi ama değeri okunmadı: kuyruk sessizce bayatlamaz."""
    from ingest.migros import _dijital_bosluklarini_denetle

    birlesik = {"moneypay-kayitli-kullanici": {"2026-01-01": 5.1, "2026-04-01": 5.5}}
    with pytest.raises(RuntimeError, match="okunamadı: 3Ç 2026"):
        _dijital_bosluklarini_denetle(birlesik, 2026, 3)


def test_dijital_bosluk_denetimi_bilinen_yayimlanmayan_ve_yayimlanmamis_ceyregi_gecer():
    """Meşru iki durum: 3Ç26'da mutlak GMV hiç yayımlanmadı (kanıtlı sabit)
    ve en yeni sunumdan sonraki çeyrek (4Ç26) henüz yok."""
    from ingest.migros import _dijital_bosluklarini_denetle

    birlesik = {"migros-one-gmv": {"2026-01-01": 24.9, "2026-04-01": 28.5}, "moneypay-tpv": {}}
    _dijital_bosluklarini_denetle(birlesik, 2026, 3)


def test_seri_cek_one_cikanlar_ile_ucuncu_ceyrek_siparisini_yazar(monkeypatch):
    """Entegrasyon: 2Ç26 (Online Operasyonlar) + 3Ç26 (Öne Çıkanlar)."""
    import ingest.migros as migros_modul

    monkeypatch.setattr(
        migros_modul, "_sunum_listesi",
        lambda session=None: [
            {"yil": 2026, "ceyrek": 2, "url": "2c26"},
            {"yil": 2026, "ceyrek": 3, "url": "3c26"},
        ],
    )
    sayfa24 = SahteSayfa(_SAYFA24_METIN, _sayfa24_kelimeler([(2, 2024), (2, 2025), (2, 2026)]))
    sayfa12 = SahteSayfa(_SAYFA12_METIN, [])

    class SecmeliPdfplumber:
        def open(self, akis, *a, **k):
            return SahtePdf([sayfa24] if akis.getvalue() == b"2c26" else [sayfa12])

    monkeypatch.setattr(migros_modul, "pdfplumber", SecmeliPdfplumber())
    monkeypatch.setattr(migros_modul, "_sunum_pdfsini_getir", lambda url, onbellek, session=None: url.encode())

    df = seri_cek(
        SimpleNamespace(id="perakende/mgros-one-siparis-sayisi", migros_metrik="migros-one-siparis-sayisi")
    )
    assert list(df["date"]) == ["2026-04-01", "2026-07-01"]
    assert list(df["value"]) == [pytest.approx(29.757), pytest.approx(29.164)]
