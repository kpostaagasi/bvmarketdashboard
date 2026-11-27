"""ORGE Enerji Elektrik Taahhüt A.Ş. çeyreklik Yatırımcı Sunumu istemcisi.

Şirket her çeyrek `https://www.orge.com.tr/<yıl>-yatirimci-sunumlari/`
sayfasında bir PDF slayt sunumu yayımlar (dosya adı `sunum_q<çeyrek>_<yıl>.pdf`).
Metin katmanı çıkarılabilir (görüntü değil) — "3A ve Sonrası Önemli
Gelişmeler" bölümünde iki rakam SABİT şablonla geçiyor (ölçüldü, 2026 Ç1 ve
Ç2 sunumları):

    "<GG.AA.YYYY> tarihi itibarıyla **Yeni Alınan İşler** toplamımız
    **<sayı> TL+KDV** tutarındadır."
    "<GG.AA.YYYY> tarihi itibarıyla **Devam Eden İşler** büyüklüğümüz
    **(backlog) <sayı> TL+KDV** seviyesinde bulunmaktadır."

Sayfa URL'si YIL bazında değişir (`<yıl>-yatirimci-sunumlari`); dosya adı
ÇEYREK bazında (`sunum_q1_2026.pdf`, `sunum_q2_2026.pdf`, …). Bu yüzden her
çeyrek için URL üretilir ve denenir (yıl başına sayfa taranıp dosya
bağlantıları çözülür). Bulunamayan çeyrek YALNIZCA en son bulunan çeyrekten
SONRA ve çeyrek sonundan bu yana `AZAMI_YAYIN_GECIKMESI_GUN` dolmamışsa
"henüz yayımlanmamış" sayılır (atlanır); arada kalan ya da süresi dolmuş
eksik çeyrek okunamamış demektir ve hata verir (bkz.
`_tum_noktalari_getir`). 2026-11-13 taramasının bulgusu: WordPress yinelenen
yüklemelere `-1`, `-3` soneki ekliyor (`sunum_q1_2024-3.pdf`,
`sunum_q3_2024-1.pdf`, `sunum_q2_2025-1.pdf`, ölçüldü 2026-11-27); eski desen
bunları eşleştirmiyor, üç çeyrek CSV'den sessizce düşüyordu.

"Backlog / Son 12 Ay Satış Oranı" ve "Piyasa Değeri / Backlog Oranı" AYRI
SERİ DEĞİLDİR — ilki TTM Hasılat (finansal tablo, bu adaptörün kapsamı
dışında), ikincisi BIST fiyatı × pay adedi ÷ USD/TRY gerektirir; ikisi de
`core/stats.py` katmanında, ilgili bileşen seriler eklendiğinde
hesaplanmalı (bkz. görev raporu "bloke"/gelecek iş notları).

Kalemler `orge_metrik` alanıyla seçilir (bkz.
`core.catalog.GECERLI_ORGE_METRIKLERI`).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import requests

from core.catalog import GECERLI_ORGE_METRIKLERI

TABAN = "https://www.orge.com.tr"
ZAMAN_ASIMI = 60
# Bir çeyreğin sunumu, çeyrek sonundan en geç bu kadar gün sonra yayımlanmış
# olmalı; süre dolduysa bulunamayan çeyrek "henüz yayımlanmamış" değil
# okunamamış sayılır. Kanıt (yükleme yolları, ölçüldü 2026-11-27, 2021–2026):
# Ç1 05–06., Ç2 08–09., Ç3 11., Ç4 ertesi yılın 02–05. ayında yükleniyor;
# en geç olanı sunum_q4_2023 (uploads/2024/05) — çeyrek sonundan ≤152 gün.
AZAMI_YAYIN_GECIKMESI_GUN = 180
ILK_YIL = 2023  # 2023 Ç1–2026 Ç3 şablonu doğrulandı (2026-11-27); sayfalar 2021 Ç1'e kadar kesintisiz.
# Sayfa yalnızca User-Agent ile isteklere 406 Not Acceptable döner (ölçüldü);
# Accept/Accept-Language de gerekiyor.
BASLIKLAR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

# pdfplumber ham metninde markdown kalın işareti (**) YOK — bu yalnızca bazı
# görüntüleme araçlarının OCR/markdown dönüşüm katmanına ait bir artefakt
# (ölçüldü 2026-09-19). Cümle içinde satır sonu düşebilir (ör. "...backlog)
# 5.589.950.948 TL+KDV seviyesinde\nbulunmaktadır") — bu SAYIYI etkilemiyor,
# yakalama grubu her iki sayıdan önce biter.
_TARIH_DESENI = r"\d{2}\.\d{2}\.\d{4}"
_SAYI = r"([\d.]+)\s*TL\+KDV"
YENI_IS_DESENI = re.compile(
    rf"{_TARIH_DESENI} tarihi itibarıyla Yeni Alınan İşler toplamımız {_SAYI}",
)
BACKLOG_DESENI = re.compile(
    rf"{_TARIH_DESENI} tarihi itibarıyla Devam Eden İşler büyüklüğümüz \(backlog\) {_SAYI}",
)

_METRIK_DESENLERI = {"backlog": BACKLOG_DESENI, "yeni-is-ytd": YENI_IS_DESENI}
assert set(_METRIK_DESENLERI) == GECERLI_ORGE_METRIKLERI


def _sayfa_url(yil: int) -> str:
    return f"{TABAN}/{yil}-yatirimci-sunumlari/"


# İsteğe bağlı `-<n>` soneki: WordPress aynı adlı yeniden yüklemeyi
# `sunum_q1_2024-3.pdf` diye kaydediyor (ölçüldü 2026-11-27; 2022 Ç4, 2024 Ç1,
# 2024 Ç3, 2025 Ç2 sunumları böyle).
_SUNUM_BAGLANTISI = re.compile(r'href="([^"]*sunum_q(\d)_(\d{4})(?:-\d+)?\.pdf)"', re.I)
# Kısmi eşleşme denetimi: adında "sunum" geçen her PDF bağlantısı yukarıdaki
# desene de uymalı — uymuyorsa dosya adı şablonu değişmiştir ve o çeyrek
# sessizce düşerdi.
_SUNUM_ADAYI = re.compile(r'href="([^"]*sunum[^"]*\.pdf)"', re.I)


def _sunum_baglantilari(session: requests.Session, yil: int) -> dict[int, str]:
    """`{yıl}-yatirimci-sunumlari` sayfasından `{çeyrek: pdf_url}` çıkarır.

    Sayfa 404 ise boş döner (o yılın sayfası henüz açılmamış olabilir — yıl
    başı); sayfası kaybolan bir yılın çeyreklerini `_tum_noktalari_getir`'in
    ara-boşluk ve yayın gecikmesi denetimleri yakalar.
    """
    yanit = session.get(_sayfa_url(yil), timeout=ZAMAN_ASIMI, headers=BASLIKLAR)
    if yanit.status_code == 404:
        return {}
    yanit.raise_for_status()
    eslesenler = _SUNUM_BAGLANTISI.findall(yanit.text)
    taninan = {url for url, _, _ in eslesenler}
    taninmayan = sorted(set(_SUNUM_ADAYI.findall(yanit.text)) - taninan)
    if taninmayan:
        raise RuntimeError(
            f"ORGE: {yil} yatırımcı sunumları sayfasında tanınmayan sunum "
            f"bağlantısı: {taninmayan} — dosya adı şablonu değişmiş olabilir"
        )
    bulunan: dict[int, str] = {}
    for url, ceyrek_str, yil_str in eslesenler:
        if int(yil_str) != yil:
            continue
        ceyrek = int(ceyrek_str)
        tam_url = url if url.startswith("http") else TABAN + url
        # Aynı çeyreğe iki FARKLI dosya bağlanmışsa (ör. düzeltilmiş yeniden
        # yükleme `-1` soneki + eski dosya) hangisinin geçerli olduğu
        # bilinemez — biri sessizce seçilmez. Aynı URL'nin tekrarı olağan
        # (sayfa her bağlantıyı iki kez veriyor, ölçüldü 2026-11-27).
        if ceyrek in bulunan and bulunan[ceyrek] != tam_url:
            raise RuntimeError(
                f"ORGE: {yil} Ç{ceyrek} için iki farklı sunum dosyası bağlanmış: "
                f"{bulunan[ceyrek]} ve {tam_url} — hangisinin geçerli olduğu belirsiz"
            )
        bulunan[ceyrek] = tam_url
    return bulunan


def _pdf_metnini_cek(session: requests.Session, url: str) -> str:
    import io

    import pdfplumber

    yanit = session.get(url, timeout=ZAMAN_ASIMI, headers=BASLIKLAR)
    yanit.raise_for_status()
    with pdfplumber.open(io.BytesIO(yanit.content)) as pdf:
        return "\n".join(sayfa.extract_text() or "" for sayfa in pdf.pages)


def deger_cek(metin: str, metrik: str) -> float:
    desen = _METRIK_DESENLERI[metrik]
    m = desen.search(metin)
    if not m:
        raise RuntimeError(f"ORGE: {metrik!r} için beklenen ifade PDF metninde bulunamadı — şablon değişmiş olabilir")
    return float(m.group(1).replace(".", "")) / 1_000_000  # TL -> Milyon TL


def _ceyrek_tarihi(yil: int, ceyrek: int) -> str:
    """Katalog sözleşmesi: çeyreksel seri tarihi çeyreğin İLK ayı (ör. Ç2 -> Nisan)."""
    ay = {1: 1, 2: 4, 3: 7, 4: 10}[ceyrek]
    return date(yil, ay, 1).isoformat()


def _ceyrek_sonu(yil: int, ceyrek: int) -> date:
    """Çeyreğin son günü (ör. 2026 Ç2 -> 2026-06-30)."""
    return {1: date(yil, 3, 31), 2: date(yil, 6, 30), 3: date(yil, 9, 30), 4: date(yil, 12, 31)}[ceyrek]


def cekilecek_ceyrekler(bugun: date) -> list[tuple[int, int]]:
    donemler = []
    for yil in range(ILK_YIL, bugun.year + 1):
        son_ceyrek = 4 if yil < bugun.year else (bugun.month - 1) // 3 + 1
        for ceyrek in range(1, son_ceyrek + 1):
            donemler.append((yil, ceyrek))
    return donemler


def _tum_noktalari_getir(onbellek: dict, metrik: str, session=None, bugun: date | None = None) -> list[tuple[str, float]]:
    cache_key = f"noktalar:{metrik}"
    if cache_key in onbellek:
        return onbellek[cache_key]
    http = session or requests.Session()
    bugun = bugun or date.today()
    baglanti_onbellegi: dict[int, dict[int, str]] = onbellek.setdefault("baglantilar", {})
    metin_onbellegi: dict[str, str] = onbellek.setdefault("metinler", {})
    donemler = cekilecek_ceyrekler(bugun)
    for yil in sorted({yil for yil, _ in donemler}):
        if yil not in baglanti_onbellegi:
            baglanti_onbellegi[yil] = _sunum_baglantilari(http, yil)
    bulunanlar = [(yil, ceyrek) for yil, ceyrek in donemler if ceyrek in baglanti_onbellegi[yil]]
    if not bulunanlar:
        raise RuntimeError(f"ORGE: {metrik!r} için hiçbir çeyrekte sunum bağlantısı bulunamadı")
    # Bulunamayan çeyrek yalnızca hem en son bulunan çeyrekten SONRA hem de
    # yayın gecikmesi penceresi İÇİNDE ise "henüz yayımlanmamış" sayılır.
    # ILK_YIL'dan itibaren her çeyrek yayımlandı (ölçüldü 2026-11-27, 2021 Ç1'den
    # beri kesintisiz) — arada eksik ya da süresi dolmuş eksik okunamamış
    # demektir (cari yılın sayfası kayboldu, son sunum yeniden adlandırıldı…).
    son_bulunan = bulunanlar[-1]
    eksikler = [
        d for d in donemler
        if d not in bulunanlar
        and (d < son_bulunan or _ceyrek_sonu(*d) + timedelta(days=AZAMI_YAYIN_GECIKMESI_GUN) < bugun)
    ]
    if eksikler:
        etiketler = ", ".join(f"{yil} Ç{ceyrek}" for yil, ceyrek in eksikler)
        raise RuntimeError(
            f"ORGE: {etiketler} yatırımcı sunumu bağlantısı bulunamadı; ya daha "
            f"yeni bir çeyrek yayımlanmış (son bulunan: {son_bulunan[0]} "
            f"Ç{son_bulunan[1]}) ya da çeyrek sonundan bu yana "
            f"{AZAMI_YAYIN_GECIKMESI_GUN} günden fazla geçmiş — sayfa ya da dosya "
            "adı şablonu değişmiş olabilir"
        )
    noktalar = []
    for yil, ceyrek in bulunanlar:
        url = baglanti_onbellegi[yil][ceyrek]
        if url not in metin_onbellegi:
            metin_onbellegi[url] = _pdf_metnini_cek(http, url)
        try:
            deger = deger_cek(metin_onbellegi[url], metrik)
        except RuntimeError as hata:
            raise RuntimeError(f"ORGE {yil} Ç{ceyrek} ({url}): {hata}") from hata
        noktalar.append((_ceyrek_tarihi(yil, ceyrek), deger))
    onbellek[cache_key] = noktalar
    return noktalar


def seri_cek(seri, *, onbellek: dict | None = None, session=None, bugun: date | None = None) -> pd.DataFrame:
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı).

    `date` çeyreğin İLK ayının 1'i (ör. 2026 Ç2 -> 2026-04-01).
    """
    onbellek = onbellek if onbellek is not None else {}
    metrik = seri.orge_metrik
    if metrik not in GECERLI_ORGE_METRIKLERI:
        raise RuntimeError(f"ORGE: bilinmeyen orge_metrik={metrik!r}")
    noktalar = _tum_noktalari_getir(onbellek, metrik, session, bugun)
    return pd.DataFrame(noktalar, columns=["date", "value"])
