"""Migros Ticaret A.Ş. (BIST: MGROS) "Ara Dönem Faaliyet Raporu" PDF istemcisi.

`migroskurumsal.com/yatirimci-iliskileri/finansal-bilgiler` sayfası her yıl
için üç ayrı "Migros Ticaret Ara Dönem Faaliyet Raporu {Mart|Haziran|Eylül}"
satırı listeliyor (4. çeyrek/yıl sonu AYRI bir belge ailesinde —
"Migros Entegre Faaliyet Raporu {Yıl}", çok daha uzun ve farklı yapıda,
bu adaptörün KAPSAMI DIŞINDA bırakıldı, bkz. aşağı). Her ara dönem raporunun
"Operasyonel Faaliyetler" bölümünde tek bir cümle dönem sonu mağaza
envanterini veriyor: "Şirketimiz, [TARİH] itibarıyla yurt içinde N coğrafi
bölgede ... olmak üzere toplam T mağazaya ulaştı."

**Bu, marketvisuals.net'in AYLIK "Toplam Mağaza Sayısı" kartıyla AYNI
KADANS DEĞİL** — yalnızca üç çeyrek-sonu anlık görüntüsü (Mart/Haziran/Eylül
sonu) veriyor, ayın her biri için değil. Migros'un KAP'a yaptığı aylık
mağaza sayısı bildirimi bu şirket sitesinde AYNA'LANMIYOR (BigChefs'in
aksine) — yalnızca KAP'ın kendisinden (resmî ama JS-render'lı SPA, yalnızca
gayrı-resmî/tersine-mühendislik API'si var) erişilebilir, bu yüzden aylık
seri KAPSAM DIŞI bırakıldı (bkz. ölçüm raporu). Bu adaptör yalnızca genuine
(gerçek, kümülatif olmayan anlık görüntü) çeyreklik veriyi sunuyor.

Ölçüldü (2026-09-18, marketvisuals.net/mgros.html'deki Haziran 2026 ayı
değeriyle birebir): 30 Haziran 2026 itibarıyla toplam mağaza sayısı 3.830.

4. çeyrek/yıl sonu KAPSAM DIŞI: "Migros Entegre Faaliyet Raporu" belgesinin
aynı cümleyi taşıyıp taşımadığı doğrulanmadı (belge çok daha uzun,
sürdürülebilirlik/kurumsal yönetim ağırlıklı — aynı tek-cümlelik özet
garanti değil).
"""

from __future__ import annotations

import calendar
import io
import re

import pandas as pd
import pdfplumber
import requests

from ingest.ir_sunum import pdf_ayikla, pdf_metnini_normallestir

TABAN = "https://www.migroskurumsal.com/yatirimci-iliskileri/finansal-bilgiler"
ZAMAN_ASIMI = 60
_BASLIKLAR = {"User-Agent": "Mozilla/5.0"}

_AYLAR = {"mart": "03", "haziran": "06", "eylül": "09", "eylul": "09"}
# "Aralık" satırları yalnızca 2008/2012/2013 için listeleniyor (ölçüldü
# 2026-11-27); 4. çeyrek bugün ayrı "Entegre Faaliyet Raporu" ailesinde
# ve bu adaptörün KAPSAMI DIŞINDA (bkz. modül başı). Bu ay adı bilerek
# atlanır; başka TANINMAYAN bir ay adı ise şablon değişikliğidir ve
# yükselir (önceden sessizce atlanıyordu — teslim notu bakım işi).
_KAPSAM_DISI_AYLAR = {"aralık"}

# Başlık hücresi üç biçimde gözlemlendi (ölçüldü 2026-11-27): "Migros
# Ticaret Ara Dönem ..." (2012, 2014+), " Migros Ticaret Ara Dönem ..."
# (2013, baştaki boşlukla) ve "Migros Ara Dönem ..." (2008). Önceki katı
# desen son ikisini SESSİZCE düşürüyordu; artık hepsi eşleşir ve ham
# başlık hücresi sayısıyla karşılaştırılır (`_rapor_listesi`).
_ARA_DONEM_SATIRI = re.compile(
    r'<td>\s*Migros(?:\s+Ticaret)?\s+Ara\s+Dönem\s+Faaliyet\s+Raporu\s+(\w+)\s*</td>\s*'
    r'<td align="center">\s*(\d{4})\s*</td>\s*'
    r'<td align="center">\s*<a href="([^"]+)"',
)
_ARA_DONEM_BASLIK_HUCRESI = re.compile(r"<td>[^<]*Ara\s+Dönem\s+Faaliyet\s+Raporu[^<]*</td>")

# Toplam mağaza sayısı cümlesi raporlarda üç ayrı kalıpla geçiyor
# (ölçüldü 2026-11-27, 2021 Mart - 2026 Eylül raporlarının tamamı):
#   1) ayrıntılı döküm: "Şirketimiz, 31 Mart 2021 itibarıyla yurt içinde 7
#      coğrafi bölgede ... olmak üzere toplam 2.330 mağazaya ulaşmıştır."
#      (2021-2022'de "ulaşmıştır", daha yenilerde "ulaştı")
#   2) özet: "Şirketin toplam mağaza sayısı 2.681'e yükseldi" / "... 3.100'e
#      ulaştı" / "toplam mağaza sayısı 31 Mart 2025 itibarıyla 3.642'ye
#      ulaştı" / "Migros'un ülke genelinde toplam mağaza sayısı 3.683 oldu"
#   3) 2023 Mart: "toplam mağaza sayısı 2.991'e (deprem bölgesinde kalıcı
#      olarak kapanan 10 mağaza dahil edilmediğinde 2.981'e) yükseldi" —
#      başlık rakamı (ilk sayı) alınır.
# Önceki desenler yalnızca "ulaştı" ve "itibarıyla toplam mağaza sayısı N
# oldu" biçimini tanıyordu: 2021 Mart - 2025 Haziran arasındaki 15 rapor
# belge OKUNDUĞU halde SESSİZCE atlanıyor, seri 2025 Eylül'den başlıyordu.
_MAGAZA_CUMLESI = re.compile(
    r"itibarıyla\s+yurt\s+içinde\s+\d+\s+coğrafi\s+bölgede\s+(.{1,600}?)\s+olmak\s+üzere\s+"
    r"toplam\s+([\d.]+)\s+mağazaya\s+ulaş(?:tı|mıştır)",
    re.S,
)
_MAGAZA_CUMLESI_OZET = re.compile(
    r"toplam\s+mağaza\s+sayısı\s+(?:\d{1,2}\s+\w+\s+\d{4}\s+itibarıyla\s+)?"
    r"(\d{1,3}(?:\.\d{3})*)(?:'\w+)?\s*(?:\([^)]{0,200}\)\s*)?(?:oldu|ulaştı|yükseldi)",
)

GECERLI_METRIKLER = {"toplam-magaza-sayisi"}

# 2021 Mart'tan ÖNCEKİ raporların toplamı yurt dışı mağazaları da içeriyor
# (ör. 30 Eylül 2020: "... yurt dışında iştirakleri vasıtasıyla Kuzey
# Makedonya'da 28 Ramstore ve Kazakistan'da 12 Ramstore olmak üzere toplam
# 2.301 mağazaya ulaşmıştır"); 31 Mart 2021'den itibaren toplam yalnızca
# yurt içi ("yurt içinde 7 coğrafi bölgede ... toplam 2.330"). Seri yurt
# içi tanımla tutarlı olsun diye bu dönemden başlar; öncesi tanım farkı
# nedeniyle BİLEREK kapsam dışıdır (sessiz atlama değil, hiç taranmaz).
MAGAZA_ILK_DONEM = "2021-03-01"


def _rapor_listesi(session=None) -> list[dict]:
    http = session or requests
    yanit = http.get(TABAN, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    yanit.raise_for_status()
    yanit.encoding = "utf-8"
    satirlar = _ARA_DONEM_SATIRI.findall(yanit.text)
    baslik_sayisi = len(_ARA_DONEM_BASLIK_HUCRESI.findall(yanit.text))
    if baslik_sayisi != len(satirlar):
        raise RuntimeError(
            f"Migros finansal bilgiler sayfasında {baslik_sayisi} 'Ara Dönem Faaliyet "
            f"Raporu' başlığı var ama yalnızca {len(satirlar)} satır (yıl + bağlantı) "
            "ayrıştırılabildi — satır şablonu değişmiş olabilir"
        )
    sonuc = []
    for ay_adi, yil, url in satirlar:
        ay_kucuk = ay_adi.lower()
        if ay_kucuk in _KAPSAM_DISI_AYLAR:
            continue
        ay = _AYLAR.get(ay_kucuk)
        if ay is None:
            raise RuntimeError(
                f"Migros 'Ara Dönem Faaliyet Raporu {ay_adi}' ({yil}) satırının ay adı "
                "tanınmıyor — şablon değişmiş olabilir"
            )
        sonuc.append({"tarih": f"{yil}-{ay}-01", "url": url})
    if not sonuc:
        raise RuntimeError(
            "Migros finansal bilgiler sayfasında hiç 'Ara Dönem Faaliyet "
            "Raporu' bağlantısı ayrıştırılamadı — şablon değişmiş olabilir"
        )
    return sonuc


def _eksik_ara_donemler(tarihler: list[str], ilk_donem: str) -> list[str]:
    """`ilk_donem`'den listedeki en yeni döneme kadar beklenen her Mart/
    Haziran/Eylül döneminden listede OLMAYANLARI döner. En yeni dönemden
    sonrası (henüz yayımlanmamış rapor) beklenmez."""
    if not tarihler:
        return []
    son = max(tarihler)
    mevcut = set(tarihler)
    eksik = []
    for yil in range(int(ilk_donem[:4]), int(son[:4]) + 1):
        for ay in ("03", "06", "09"):
            tarih = f"{yil}-{ay}-01"
            if ilk_donem <= tarih <= son and tarih not in mevcut:
                eksik.append(tarih)
    return eksik


def _kapsamdaki_raporlar(raporlar: list[dict], ilk_donem: str, ne_icin: str) -> list[dict]:
    """`ilk_donem` ve sonrasındaki raporları döner; aradaki bir dönemin
    satırı sayfadan kaybolmuşsa yükselir (sessiz delik yerine)."""
    kapsam = [r for r in raporlar if r["tarih"] >= ilk_donem]
    eksik = _eksik_ara_donemler([r["tarih"] for r in kapsam], ilk_donem)
    if eksik:
        raise RuntimeError(
            f"Migros {ne_icin}: finansal bilgiler sayfasında şu dönemlerin 'Ara Dönem "
            f"Faaliyet Raporu' satırı yok: {', '.join(t[:7] for t in eksik)}"
        )
    return kapsam


def magaza_sayisini_ayikla(metin: str) -> float | None:
    """Toplam (yurt içi) mağaza sayısını döner; hiçbir kalıp eşleşmezse
    None. Ayrıntılı döküm yurt dışı mağaza içeriyorsa (2021 öncesi tanım)
    ya da iki kalıp AYNI raporda farklı sayı veriyorsa yükselir — ikisi de
    yanlış değer yazmaktansa patlamayı gerektirir."""
    ayrintili = _MAGAZA_CUMLESI.search(metin)
    ozet = _MAGAZA_CUMLESI_OZET.search(metin)
    if ayrintili and "yurt dışında" in ayrintili.group(1):
        raise RuntimeError(
            "Migros mağaza envanteri cümlesi yurt dışı mağazaları da içeriyor — "
            "seri yalnızca yurt içi toplamı tutar (bkz. MAGAZA_ILK_DONEM)"
        )
    degerler = []
    if ayrintili:
        degerler.append(float(ayrintili.group(2).replace(".", "")))
    if ozet:
        degerler.append(float(ozet.group(1).replace(".", "")))
    if not degerler:
        return None
    if len(set(degerler)) > 1:
        raise RuntimeError(
            f"Migros raporunda toplam mağaza sayısı iki cümlede farklı: {degerler}"
        )
    return degerler[0]


def _belge_metnini_getir(url: str, onbellek: dict, session=None) -> str:
    """Belge metnini döner. 404 dahil her HTTP hatası yükselir: kapsamdaki
    (bkz. `MAGAZA_ILK_DONEM`, `ACILIS_ILK_DONEM`) hiçbir raporda link
    çürümesi yok (ölçüldü 2026-11-27); tek ölçülen 404 (2012 Eylül) artık
    taranmıyor. Önceden 404 None dönüp dönemi SESSİZCE atlıyordu."""
    if url in onbellek:
        return onbellek[url]
    http = session or requests
    yanit = http.get(url, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    yanit.raise_for_status()
    baytlar = pdf_ayikla(yanit.content)
    with pdfplumber.open(io.BytesIO(baytlar)) as pdf:
        metin = pdf_metnini_normallestir("\n".join(sayfa.extract_text() or "" for sayfa in pdf.pages))
    onbellek[url] = metin
    return metin


# --- Format bazında yeni mağaza açılışları (2023 3Ç'ten itibaren) ---
#
# Aynı "Ara Dönem Faaliyet Raporu"nun GİRİŞ bölümünde (mağaza envanteri
# cümlesinden AYRI, ondan ÖNCE gelen) yıl-başından-itibaren kümülatif bir
# açılış cümlesi var: "1 Ocak – [tarih] döneminde N1 adet Migros, N2 adet
# Migros Jet, ... olmak üzere toplam T yeni mağaza açılmıştır." Ölçüldü
# (2026-09-19): 2023 3Ç'ten önce (2023 1Ç/2Ç raporları) bu cümle YOK —
# seri o çeyrekten başlar. Bu GERÇEK brüt açılış sayısıdır (toplam mağaza
# sayısındaki NET değişimden bilhassa farklı: aynı çeyrekte kapanışlar da
# olabiliyor, ör. 2Ç 2026'da format optimizasyonuyla 19 Mion kapatıldı —
# bkz. Migros 2Ç 2026 Yatırımcı Sunumu s.7), bu yüzden toplam mağaza
# sayısı serisinden fark alarak ÜRETİLEMEZ.
GECERLI_FORMAT_ACILIS_METRIKLERI = {
    "toplam-yeni-magaza-acilis",
    "migros-format-magaza-acilis",
    "migros-jet-format-magaza-acilis",
    "macrocenter-format-magaza-acilis",
    "mion-format-magaza-acilis",
}

_ACILIS_CUMLESI = re.compile(
    r"1\s*Ocak\s*[-–]\s*\d{1,2}\s+\w+\s+\d{4}\s+döneminde\s+(.{1,400}?)\s+"
    r"olmak\s+üzere\s+toplam\s+([\d.]+)\s+yeni\s+mağaza\s+aç[ıi]lm[ıi]şt[ıi]r",
    re.S,
)
# Gövde uzunluğu SINIRLI: raporun başka bölümlerinde de "1 Ocak – [tarih]
# döneminde ..." kalıbıyla başlayan alakasız cümleler var (ör. "esas
# sözleşmede değişiklik yapılmamıştır" — 2024 Mart raporunda ölçüldü).
# Sınırsız `.+?` bu alakasız cümleden başlayıp binlerce karakter sonraki
# GERÇEK açılış cümlesinin "olmak üzere toplam ... açılmıştır" ucuna
# atlayıp gövdeyi tamamen yanlış içerikle dolduruyordu. 400 karakter en
# uzun gözlemlenen gövdeden (Petimo dahil tam format dökümü, ~200 kr.)
# bolca pay bırakır.
# Cümle gövdesindeki HER "N [adet] <format>" kalemi okunur ve format adı
# aşağıdaki AÇIK listeyle karşılaştırılır. "adet" bazı çeyreklerde yok
# (ör. 2023 3Ç: "195 Migros, 105 Migros Jet"), format sırası ve tam liste
# çeyrekten çeyreğe değişiyor, araya "kişisel bakım mağazacılığı
# formatında" gibi niteleyiciler giriyor — sabit pozisyon varsayılmaz.
# Ölçüldü (2026-11-27, 2023 Eylül–2026 Eylül arası 10 raporun tamamı):
# gövdede geçen adlar yalnızca bunlar; kartlarımız ilk dördünü karşılıyor
# (değer None = okunur, toplam denetimine girer ama seri yazılmaz).
_BILINEN_ACILIS_FORMATLARI = {
    "Migros": "migros-format-magaza-acilis",
    "Migros Jet": "migros-jet-format-magaza-acilis",
    "Macrocenter": "macrocenter-format-magaza-acilis",
    "Mion": "mion-format-magaza-acilis",
    "Macrokiosk": None,
    "Petimo": None,
    "hipermarket": None,
    "Minigros": None,
    "Toptan": None,
}
_ACILIS_KALEMI = re.compile(r"(\d[\d.]*)\s+(?:adet\s+)?(Migros\s+Jet\b|\w+)")
_GOVDE_SAYISI = re.compile(r"\d[\d.]*")


# Açılış cümlesinin ilk göründüğü rapor (ölçüldü 2026-09-19, yeniden
# ölçüldü 2026-11-27: 2023 Mart/Haziran raporlarında YOK, 2023 Eylül'den
# 2026 Eylül'e kadar her raporda VAR). Bu dönemden önceki raporlar hiç
# taranmaz; bu dönemden sonra cümlesi okunamayan rapor YÜKSELİR.
ACILIS_ILK_DONEM = "2023-09-01"


def format_acilislarini_ayikla(metin: str) -> dict[str, float] | None:
    """Rapor GİRİŞ bölümündeki yıl-başından-kümülatif açılış cümlesinden
    toplamı ve format bazında dökümü okur; cümle yoksa (2023 3Ç öncesi)
    None döner.

    Gövdedeki her sayı bir "N [adet] <format>" kalemi olmalı ve her format
    adı `_BILINEN_ACILIS_FORMATLARI`'nda bulunmalı; kalemlerin toplamı
    cümlenin "toplam T" değerine EŞİT olmalı (2023 Eylül–2026 Eylül arası
    her raporda tutuyor, ör. 2026 Eylül: 84+41+14+11+2+2=154). Tanınmayan
    ad (ör. "Migros Jet" -> "Jet" yeniden adlandırması), kaleme bağlanamayan
    sayı, aynı formatın iki kez geçmesi ya da toplam uyuşmazlığı yükselir.
    İki denetim de geçince listede olup gövdede GEÇMEYEN bir format kanıtla
    0 açılış demektir (yayımlanan toplamdan türetilir, uydurulmaz) ve 0
    yazılır — böylece bir çeyrekte hiç açılmayan format (ör. Mion) seride
    delik bırakmaz ya da seriyi sonlandırmaz."""
    m = _ACILIS_CUMLESI.search(metin)
    if not m:
        return None
    toplam = float(m.group(2).replace(".", ""))
    govde = m.group(1)
    kalemler = _ACILIS_KALEMI.findall(govde)
    if len(kalemler) != len(_GOVDE_SAYISI.findall(govde)):
        raise RuntimeError(
            f"Migros açılış cümlesinde bir format kalemine bağlanamayan sayı var: {govde[:300]!r}"
        )
    okunan: dict[str, float] = {}
    for sayi, ad in kalemler:
        ad = re.sub(r"\s+", " ", ad)
        if ad not in _BILINEN_ACILIS_FORMATLARI:
            raise RuntimeError(
                f"Migros açılış cümlesinde tanınmayan format adı {ad!r} — format "
                f"eklenmiş ya da yeniden adlandırılmış olabilir: {govde[:300]!r}"
            )
        if ad in okunan:
            raise RuntimeError(f"Migros açılış cümlesinde {ad!r} formatı iki kez geçiyor: {govde[:300]!r}")
        okunan[ad] = float(sayi.replace(".", ""))
    if sum(okunan.values()) != toplam:
        raise RuntimeError(
            f"Migros açılış cümlesinde format kalemlerinin toplamı "
            f"{sum(okunan.values()):g}, cümlenin toplamı {toplam:g} — döküm eksik "
            f"ya da yanlış okundu: {govde[:300]!r}"
        )
    sonuc: dict[str, float] = {"toplam-yeni-magaza-acilis": toplam}
    for ad, metrik in _BILINEN_ACILIS_FORMATLARI.items():
        if metrik is not None:
            sonuc[metrik] = okunan.get(ad, 0.0)
    return sonuc


_CEYREK_ONCEKI_AY = {"06": "03", "09": "06"}


def _kumulatif_ceyregi_cevir(
    noktalar: dict[str, float], metrik: str = "", rapor_tarihleri: list[str] | None = None
) -> dict[str, float]:
    """Yılbaşından kümülatif çeyrek-sonu değerini o çeyreğe özgü akışa
    çevirir (bkz. `ingest.bddk.kumulatifi_ayliga_cevir` — aynı desenin
    çeyreklik hali). Tarihler `_rapor_listesi`'nin kendi damgasını
    kullanır (raporun kapsadığı TAKVİM AYI — Mart="03", Haziran="06",
    Eylül="09"; bu adaptör hiç Ç4/"12" görmüyor), genel "çeyreğin ilk
    ayı" kuralı DEĞİL. 1Ç (Mart damgası) zaten tek çeyrekliktir. Sonraki
    çeyrekler aynı yıl içindeki BİR ÖNCEKİ çeyrek damgasından farkla
    bulunur; önceki çeyrek eksikse bu çeyrek ATLANIR — eksiğin üstüne
    fark almak iki çeyreği tek çeyreğe yığar ve sessizce yanlış değer
    üretir. Bu atlama yalnızca tek MEŞRU durumda olur: `ACILIS_ILK_DONEM`
    (2023 Eylül, 9 aylık kümülatif) — 2023 Haziran raporu cümleyi hiç
    taşımadığı için bu nokta yapısal olarak çeyreğe çevrilemez.
    `format_acilislarini_ayikla` her raporda dört formatın HEPSİNİ döner
    (gövdede geçmeyen = toplam denetimiyle kanıtlanmış 0), okunamayan rapor
    bu noktaya gelmeden `_format_acilislarini_getir`'de yükselir.

    Cümle YILBAŞINDAN KÜMÜLATİF olduğu için aynı yılın önceki bir raporunda
    değeri olan (YTD > 0) bir format sonraki raporda meşru olarak YOK
    OLAMAZ: `rapor_tarihleri` (taranan tüm raporlar) verildiğinde taranan
    bir raporda metriğin hiç olmaması yükselir (yılın ilk raporu dahil) —
    ayıklayıcı her raporda dört formatı döndüğü için bu bir savunma katmanı;
    yeniden adlandırma ("Migros Jet" -> "Jet") zaten ayıklayıcının tanınmayan
    ad denetiminde yükselir (teslim sonrası doğrulayıcı bulguları).
    Aynı nedenle negatif çeyrek farkı da (kümülatif geriledi) okuma
    hatasıdır ve yükselir."""
    if rapor_tarihleri is not None:
        for yil in sorted({t[:4] for t in rapor_tarihleri}):
            yilin_raporlari = sorted(t for t in rapor_tarihleri if t[:4] == yil)
            for tarih in yilin_raporlari:
                if tarih not in noktalar:
                    raise RuntimeError(
                        f"Migros {metrik!r} {tarih[:7]} raporunda yok — her taranan "
                        "raporda değeri olmalı (gövdede geçmeyen format 0 yazılır); "
                        "format adı ya da açılış cümlesi değişmiş olabilir"
                    )
    sonuc: dict[str, float] = {}
    for tarih in sorted(noktalar):
        yil, ay = tarih[:4], tarih[5:7]
        if ay == "03":
            sonuc[tarih] = noktalar[tarih]
            continue
        onceki_ay = _CEYREK_ONCEKI_AY.get(ay)
        onceki = f"{yil}-{onceki_ay}-01" if onceki_ay else None
        if onceki and onceki in noktalar:
            fark = noktalar[tarih] - noktalar[onceki]
            if fark < 0:
                raise RuntimeError(
                    f"Migros {metrik!r} {tarih[:7]} çeyrek farkı negatif: kümülatif "
                    f"{noktalar[onceki]:g} ({onceki[:7]}) -> {noktalar[tarih]:g} — "
                    "yılbaşından kümülatif değer gerileyemez, yanlış okuma"
                )
            sonuc[tarih] = fark
    return sonuc


def _format_acilislarini_getir(onbellek: dict, session=None) -> dict[str, dict[str, float]]:
    """Tüm raporları TARA (rapor listesi/metin önbelleği `seri_cek`'in
    `toplam-magaza-sayisi` dalıyla paylaşılır), her metriği yılbaşından-
    kümülatiften çeyrekliğe çevirip {metrik: {tarih: değer}} döner. Beş
    metrik (toplam + 4 format) aynı tek taramayı paylaşır."""
    if "format_acilis" in onbellek:
        return onbellek["format_acilis"]
    if "raporlar" not in onbellek:
        onbellek["raporlar"] = _rapor_listesi(session=session)
    kumulatif: dict[str, dict[str, float]] = {m: {} for m in GECERLI_FORMAT_ACILIS_METRIKLERI}
    raporlar = _kapsamdaki_raporlar(onbellek["raporlar"], ACILIS_ILK_DONEM, "format açılışları")
    for r in raporlar:
        metin = _belge_metnini_getir(r["url"], onbellek, session=session)
        ayiklanan = format_acilislarini_ayikla(metin)
        if ayiklanan is None:
            raise RuntimeError(
                f"Migros {r['tarih'][:7]} Ara Dönem Faaliyet Raporu'nda yeni mağaza "
                f"açılış cümlesi okunamadı ({r['url']}) — şablon değişmiş olabilir"
            )
        for metrik, deger in ayiklanan.items():
            kumulatif[metrik][r["tarih"]] = deger
    rapor_tarihleri = [r["tarih"] for r in raporlar]
    sonuc = {
        metrik: _kumulatif_ceyregi_cevir(noktalar, metrik, rapor_tarihleri)
        for metrik, noktalar in kumulatif.items()
    }
    onbellek["format_acilis"] = sonuc
    return sonuc


# --- Migros One / MoneyPay dijital ekosistem ölçütleri (Yatırımcı Sunumu) ---
#
# migroskurumsal.com'un aynı finansal-bilgiler sayfasında "Yatırımcı
# Sunumları" sekmesi 1Ç 2011'den bugüne çeyreklik PDF listeler (Ara Dönem
# Faaliyet Raporu'ndan AYRI belge ailesi, aynı sayfadaki AYRI bir
# `<table>`). Migros One (e-ticaret/GMV/aktif kullanıcı) ve MoneyPay
# (fintek) verisi yalnızca yakın geçmişte ortaya çıktı; `SUNUM_ILK_YIL`
# öncesi hiç taranmıyor (performans + zaten veri yok).
SUNUM_ILK_YIL = 2023

_SUNUM_BASLIK = re.compile(r"^(\d)Ç\s*(\d{4})(?:\s+Migros)?\s+Yatırımcı Sunumu$")

GECERLI_DIJITAL_METRIKLERI = {
    "migros-one-gmv", "migros-one-aktif-kullanici",
    "migros-one-siparis-sayisi", "moneypay-kayitli-kullanici",
}


def _sunum_listesi(session=None) -> list[dict]:
    """finansal-bilgiler sayfasının "Yatırımcı Sunumları" tablosundan
    (yıl, çeyrek, url) satırlarını okur. Başlık ya "NÇ YYYY Yatırımcı
    Sunumu" (2026'dan itibaren) ya da "NÇ YYYY Migros Yatırımcı Sunumu"
    (daha eski) biçiminde — "Migros" sözcüğü opsiyonel eşleşir.

    DİL: tabloda her çeyrek için TAM OLARAK BİR satır var ve başlık
    TÜRKÇE (ölçüldü 2026-09-30: 1Ç 2011'den 2Ç 2026'ya kadar tek satır
    / çeyrek). Aynı çeyreğin hem Türkçe hem İngilizce varyantı
    sunulmadığı için dedupe/çok-dilli öncelik sorunu YOK; eklendiği gün
    çift görülürse ilk bulunan (tablo sırası) kazanır."""
    http = session or requests
    yanit = http.get(TABAN, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    yanit.raise_for_status()
    yanit.encoding = "utf-8"
    sonuc = []
    for baslik, hucre in re.findall(r"<tr>\s*<td>([^<]+)</td>\s*<td>(.*?)</td>\s*</tr>", yanit.text, re.S):
        eslesme = _SUNUM_BASLIK.match(baslik.strip())
        if not eslesme:
            # Eşleşmeyen satırlar başka belge aileleri ("CMD Sunumu", "3Ç 2019
            # Şirket Sunumu", "9A 2016 Migros Yatırımcı Sunumu" ...) — hepsi
            # SUNUM_ILK_YIL öncesi ya da çeyreklik değil (ölçüldü 2026-11-27).
            # Kapsamdaki bir yılı taşıyan "Yatırımcı Sunumu" başlığı desene
            # uymuyorsa bu şablon kaymasıdır; sessizce atlanmaz.
            yillar = [int(y) for y in re.findall(r"\b(\d{4})\b", baslik)]
            if "Yatırımcı Sunumu" in baslik and any(y >= SUNUM_ILK_YIL for y in yillar):
                raise RuntimeError(
                    f"Migros '{baslik.strip()}' satırı kapsamdaki bir yılın Yatırımcı "
                    "Sunumu gibi görünüyor ama başlık deseni ('NÇ YYYY ... Yatırımcı "
                    "Sunumu') eşleşmedi — şablon değişmiş olabilir"
                )
            continue
        yil = int(eslesme.group(2))
        if yil < SUNUM_ILK_YIL:
            continue
        href = re.search(r'href="([^"]+)"', hucre)
        if not href:
            # Satır listelenmiş ama bağlantısı yok: önceden sessizce
            # atlanıyordu. Ölçüldü (2026-11-27): 2023-2026 arası her satırın
            # bağlantısı var — bağlantısız satır şablon değişikliğidir.
            raise RuntimeError(
                f"Migros '{baslik.strip()}' satırında PDF bağlantısı ayrıştırılamadı — "
                "şablon değişmiş olabilir"
            )
        sonuc.append({"yil": yil, "ceyrek": int(eslesme.group(1)), "url": href.group(1)})
    if not sonuc:
        raise RuntimeError(
            "Migros finansal bilgiler sayfasında hiç 'Yatırımcı Sunumu' bağlantısı "
            "ayrıştırılamadı — şablon değişmiş olabilir"
        )
    return sonuc


def _sunum_pdfsini_getir(url: str, onbellek: dict, session=None) -> bytes:
    """Ham PDF baytlarını döner (metne değil — ekosistem ızgarası konum
    bilgisine ihtiyaç duyar). 404 dahil her HTTP hatası yükselir (önceden
    404 None dönüp sunumu sessizce atlıyordu; 2023+ sunumlarında link
    çürümesi ölçülmedi, 2026-11-27). Anahtarı
    `_belge_metnini_getir`'in METİN önbelleğinden AYRI tutulur (baytlar
    çok daha büyük ve iki farklı çıkarımda tekrar kullanılıyor)."""
    anahtar = ("sunum_bayt", url)
    if anahtar in onbellek:
        return onbellek[anahtar]
    http = session or requests
    yanit = http.get(url, headers=_BASLIKLAR, timeout=ZAMAN_ASIMI)
    yanit.raise_for_status()
    baytlar = pdf_ayikla(yanit.content)
    onbellek[anahtar] = baytlar
    return baytlar


def _moneypay_kayitli_kullanici_ayikla(pdf_baytlari: bytes) -> float | None:
    """'Fintek Operasyonları: Moneypay' başlık kutusunu taşıyan sayfayı
    bulup kayıtlı kullanıcı sayısını okur (sayfa-izole arama şart: sayı
    ve etiketler pdfplumber'da SÜTUN BAZLI satır-satır çıkarıldığından
    -- ör. "Migros Yemek GMV" gibi iki satırlı başlıklar komşu sütunların
    metniyle iç içe geçiyor -- tüm belge metninde arama yanlış sayfayı
    yakalayabilir; ölçüldü). Üç kardeş ölçüt (Toplam Ödeme Hacmi, Günlük
    İşlem, Hasılat) hep 'milyar TL'/'bin'/'milyon TL' birimi taşırken
    yalnız kayıtlı kullanıcı TL'siz çıplak 'milyon' alır — tek ölçüt bu
    birimle ayırt edilebiliyor. Sayfa bu başlığı taşımıyorsa (ör.
    3Ç/4Ç sunumlarının eski 'Hasılat/TPV' çerçevesi) None döner; sayfa
    VAR ama sayı okunamıyorsa yükselir (önceden None dönüp çeyreği
    sessizce düşürüyordu)."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        sayfa_metni = None
        for p in pdf.pages:
            t = p.extract_text() or ""
            if "Moneypay" in t and "Kayıtlı kullanıcı" in t:
                sayfa_metni = t
                break
        if sayfa_metni is None:
            return None
    metin = pdf_metnini_normallestir(sayfa_metni)
    sinir = metin.find("yıllık")
    govde = metin if sinir == -1 else metin[:sinir]
    m = re.search(r"(\d+[.,]\d+)\s+milyon\b(?!\s*TL)", govde)
    if not m:
        raise RuntimeError(
            "Migros sunumunda 'Fintek Operasyonları: Moneypay' sayfası var ama kayıtlı "
            "kullanıcı sayısı ('N milyon') okunamadı — şablon değişmiş olabilir"
        )
    return float(m.group(1).replace(",", "."))


_EKOSISTEM_ETIKET_KELIMELERI = {"Aktif", "Sipariş", "GMV", "Kayıtlı", "İşlem", "TPV"}
_EKOSISTEM_ANAHTARLARI = (
    "migros-one-aktif-kullanici", "migros-one-siparis-sayisi", "migros-one-gmv",
    "moneypay-kayitli-kullanici", "moneypay-islem-sayisi", "moneypay-tpv",
)
# Izgaranın kaç çeyrek geriye baktığı (x ekseni vektör olduğu için
# sayfa metninden okunamıyor, sunumun kendi çeyreğinden geriye doğru
# hesaplanıyor). Ölçüldü: 4Ç24/3Ç25/4Ç25/1Ç25 sunumlarında hep 5.
_IZGARA_CEYREK_SAYISI = 5


def ekosistem_izgarasini_ayikla(
    pdf_baytlari: bytes, sunum_yili: int, sunum_ceyregi: int
) -> dict[str, dict[str, float]] | None:
    """'Migros Dijital Ekosistemi Performans Göstergeleri' sayfasını
    (varsa) bulur ve 6 sütun x 5 çeyreklik ızgarayı x-konumuna göre
    ayrıştırır. Her sunumda YOK (ölçüldü: 4Ç24/3Ç25/4Ç25/1Ç26'da var,
    2Ç26'da yok) — yoksa None döner.

    Sayfa sunumun KENDİ çeyreğiyle biten 5 ardışık çeyreği gösterir. X
    ekseni metni PDF'te vektör/resim olarak gömülü olduğundan OCR
    EDİLMEZ: tarihler sunumun BİLİNEN kendi çeyreğinden geriye doğru
    hesaplanır. Görsel doğrulama (2026-09-19, 4Ç2025 sunumu sayfa 26):
    x ekseni "4Ç24 1Ç25 2Ç25 3Ç25 4Ç25" — soldan sağa eskiden yeniye.

    Yalnızca gösterge amaçlı üç ek sütun da (Sipariş Sayısı, MoneyPay
    İşlem Sayısı, MoneyPay TPV) döner; `seri_cek` yalnızca ihtiyaç
    duyduğu beşini kullanır."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        sayfa = None
        for p in pdf.pages:
            metin = p.extract_text() or ""
            if "Ekosistemi" in metin and "Göstergeleri" in metin:
                sayfa = p
                break
        if sayfa is None:
            return None
        kelimeler = sayfa.extract_words()

    baslik_topu = min(
        (k["top"] for k in kelimeler if k["text"] in _EKOSISTEM_ETIKET_KELIMELERI), default=None
    )
    if baslik_topu is None:
        raise RuntimeError("ekosistem ızgarası: sütun başlıkları bulunamadı")

    sayi_deseni = re.compile(r"^\d+[.,]\d+$")
    degerler = sorted(
        (k for k in kelimeler if sayi_deseni.match(k["text"]) and k["top"] > baslik_topu + 20),
        key=lambda k: k["x0"],
    )
    beklenen = len(_EKOSISTEM_ANAHTARLARI) * _IZGARA_CEYREK_SAYISI
    if len(degerler) != beklenen:
        # Sayfa BULUNDU ama ızgara okunamadı: bu "sayfa yok" değil, "okunamadı"
        # durumudur ve yükselir. (2Ç 2026'da sayfa TAMAMEN kaldırıldı — o
        # durumda yukarıdaki başlık araması zaten None döner. Ölçüldü
        # 2026-11-27: başlığı taşıyan 7 sunumun hepsinde tam 30 değer var.)
        raise RuntimeError(
            f"Migros {sunum_ceyregi}Ç {sunum_yili} sunumunda ekosistem ızgarası sayfası var "
            f"ama {beklenen} yerine {len(degerler)} değer okundu — şablon değişmiş olabilir"
        )

    # Sabit boyutlu dilimleme: 6 grup x 5 çeyrek her zaman x0'a göre
    # sıralandığında ARDIŞIK bloklar halinde gelir (gruplar arası boşluk
    # bazen bir grubun KENDİ içindeki iki çeyrek kümesi arasındaki
    # boşluktan küçük olabiliyor — ölçüldü, 2Ç2024 sunumu — bu yüzden en
    # büyük N boşluğu ayıraç seçen bir yöntem YANLIŞ gruplar üretebilir).
    # Toplam tam sayı doğrulandığı için basit 5'li dilimleme güvenlidir.
    dilim = _IZGARA_CEYREK_SAYISI
    gruplar = [degerler[i:i + dilim] for i in range(0, beklenen, dilim)]

    ceyrekler = []
    yil, ceyrek = sunum_yili, sunum_ceyregi
    for _ in range(_IZGARA_CEYREK_SAYISI):
        ceyrekler.append((yil, ceyrek))
        yil, ceyrek = (yil - 1, 4) if ceyrek == 1 else (yil, ceyrek - 1)
    ceyrekler.reverse()

    sonuc: dict[str, dict[str, float]] = {}
    for anahtar, grup in zip(_EKOSISTEM_ANAHTARLARI, gruplar):
        harita = {}
        for (yy, cc), kelime in zip(ceyrekler, grup):
            ay = {1: "01", 2: "04", 3: "07", 4: "10"}[cc]
            harita[f"{yy}-{ay}-01"] = float(kelime["text"].replace(",", "."))
        sonuc[anahtar] = harita
    return sonuc


# --- 2Ç 2026'dan itibaren "Online Operasyonlar" sayfası ---
#
# 2Ç 2026 sunumu (s.24) "Migros Dijital Ekosistemi Performans
# Göstergeleri" ızgarasını KALDIRDI; yerine aynı çeyreğin dört
# tekil mini-grafiğini taşıyan "Online Operasyonlar" sayfası geldi.
# Ölçülen değerler (x-konumlarıyla eşleştirilerek, s.24):
#   grup 1 "Migros One GMV (milyar TL)"   18,6 | 23,5 | 28,5  (2Ç24|25|26)
#           (+ altında ikinci seri: Migros Yemek GMV 1,9 | 2,9 | 5,0)
#   grup 2 "Günlük Sipariş"               226k | 263k | 327k
#           (+ altında ikinci seri: 45k | 57k | 91k)
#   grup 3 "Migros'ta e-ticaret payı (%)(1)" 18,5 | 20,7 | 23,1
#   grup 4 "Aktif kullanıcı sayısı(2) (milyon)" 5,1 | 5,8 | 6,6
# (2) dipnotu "Yıllıklandırılmış (Son 12 ay)" — ESKİ ızgaranın "Son 12
# aylık aktif kullanıcı sayısı" tanımıyla AYNI.
#
# ÇAPRAZ KONTROL (s.5 özeti): "28,5 milyar TL GMV", "6,6 milyon tekil
# online müşteri (2Ç 2025: 5,8 milyon)" ve "günlük siparişlerde %24
# artışla 327 bine ulaşıldı" — 327k/263k = 1,244 ✓. Yani sütun
# eşleştirmesi doğru ve üç değer de sunumun KENDİ çeyreğine ait.
#
# BİRİM TUZAĞI: "Günlük Sipariş" GÜNLÜK ORTALAMA. `migros-one-
# siparis-sayisi` ise ÇEYREKLİK TOPLAM tutuyor. Doğrulama: eski
# ızgaranın 2Ç25 çeyreklik sipariş değeri 23,9 mn; 263k × 91 gün =
# 23,93 mn ✓ birebir. Bu yüzden günlük değer, EKSEN ETİKETİNDEN
# türetilen çeyreğin gerçek gün sayısıyla çarpılır — sabit 90/91
# hardcode edilmez (1Ç 2026 = 90 gün, 2Ç 2026 = 30+31+30 = 91 gün).
#
# GEÇMİŞ ÇEYREKLERİ ALMIYORUZ: yeni sayfadaki 2Ç24/2Ç25 sütunları eski
# ızgarayla AYNI DEĞİL (GMV 2Ç25: yeni 23,5, eski 17,5; 2Ç24: 18,6 vs
# 11,5) ve farkın nedeni belgelenemedi. Sessiz bir seviye sıçraması
# yaratmamak için yalnızca sunumun KENDİ çeyreği alınır, geçmiş eski
# ızgaradan gelmeye devam eder.

_ONLINE_SAYFA_BASLIGI = re.compile(r"\s*Online\s+Operasyonlar\s*")
# Başlık sayfanın İLK SATIRININ TAMAMI olmalı (`fullmatch`): ifade
# başka sayfalarda da geçiyor (ölçüldü 2026-11-27) — İçindekiler (2023
# s.2), bölüm ayracı "Online | Operasyonlar | & | Stratejik" (2023 s.12),
# "Migros Online Operasyonlar" (4Ç24 s.20), "Online Operasyonlar Daha
# Verimli" (3Ç25/4Ç25), "Online Operasyonlar Brüt Ticaret Hacmi" ve
# "Migros'un Ana Faaliyet Alanını Destekleyen Girişimler". Hedef şablon
# yalnızca 1Ç26 s.16 ve 2Ç26 s.24'te.
# DİL: sunumlar YALNIZCA TÜRKÇE; "Online Operasyonlar" başlığı ölçüldü
# (2Ç26 s.24). Eski desendeki İngilizce "Online Operations" varyantı
# hiç doğrulanmamıştı ve YANLIŞ POZİTİF veriyordu: 2Ç 2025 sunumunun
# s.17/s.19 bölüm ayraçları "Online | Operations | & | Strategy | Update"
# taşıyor (ölçüldü 2026-11-27). Sayfa bulunduğunda okunamamak artık
# yükseldiği için bu varyant kaldırıldı.


# Grafik başlığındaki tek sözcük -> seri. Anahtar sözcüklerin hepsi
# AYNI başlık bandında (ölçüldü 2Ç26 s.24: "Aktif" top=243,7, "GMV"
# top=248,2, "Sipariş" top=248,5 — en büyük fark 4,8pt); sayfanın
# üstündeki "Çeyreksel Öne Çıkanlar" şeridindeki GMV ise 97,95pt
# yukarıda (top=145,6). O yüzden "anahtarı en çok geçen bant" seçilir.
_ONLINE_BASLIK_ANAHTARLARI = {
    "GMV": "migros-one-gmv",
    "Sipariş": "migros-one-siparis-sayisi",
    "Aktif": "migros-one-aktif-kullanici",
}

_CEYREK_AYLARI = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}

_CEYREK_ETIKETI = re.compile(r"^(\d)Ç$")


def _ceyrek_gun_sayisi(yil: int, ceyrek: int) -> int:
    """Verilen çeyreğin GERÇEK gün sayısı (2Ç 2026 = 30+31+30 = 91,
    1Ç 2026 = 31+28+31 = 90). Sabit 90/91 hardcode edilmez."""
    return sum(calendar.monthrange(yil, ay)[1] for ay in _CEYREK_AYLARI[ceyrek])


def online_operasyonlarini_ayikla(
    pdf_baytlari: bytes, sunum_yili: int, sunum_ceyregi: int
) -> dict[str, float] | None:
    """'Online Operasyonlar' sayfasından Migros One'ın ÜÇ ölçütünü
    (GMV milyar TL, aktif kullanıcı milyon, sipariş milon ÇEYREKLİK
    TOPLAM) yalnızca SUNUMUN KENDİ ÇEYREĞİ için okur; sayfa yoksa
    (2Ç 2026 öncesi tüm sunumlar) None döner.

    Ayrıştırma x-konumuna dayanır: sayfadaki "NÇ YYYY" eksen
    etiketleri dört grafiği aynı sayıda sütuna böler (ölçülen: 4 grup
    × 3 sütun = 12 etiket), her grafiğin başlığı x-merkeziyle hangi
    gruba ait olduğunu belirler, değerler kendi eksen etiketine EN
    YAKIN olan sütundan ve o sütunda EN ÜSTTEKİ kutudan okunur
    (sütunda ikinci, daha küçük bir seri varsa — Migros Yemek GMV gibi —
    üstteki kutu asıl seridir: 2Ç26'da 28,5 / 5,0 ve 327k / 91k).

    Birim dönüşümü: günlük sipariş -> çeyreklik toplam (gün sayısı
    EKSEN ETİKETİNDEN türetilir); GMV ve aktif kullanıcı zaten
    çeyreklik/milyon birimindedir.

    Sayfa BULUNDUĞU halde eksen/başlık/değer kutusu okunamıyorsa ya da üç
    ölçütten biri eksik kalıyorsa yükselir (önceden her adım sessizce
    None/`continue` ile çeyreği düşürüyordu)."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        for p in pdf.pages:
            ilk_satir = (p.extract_text() or "").split("\n", 1)[0]
            if _ONLINE_SAYFA_BASLIGI.fullmatch(ilk_satir):
                kelimeler = p.extract_words()
                break
        else:
            return None

    def okunamadi(neden: str) -> RuntimeError:
        return RuntimeError(
            f"Migros {sunum_ceyregi}Ç {sunum_yili} sunumunda 'Online Operasyonlar' sayfası "
            f"var ama {neden} — şablon değişmiş olabilir"
        )

    # Eksen etiketleri sayfanın EN ALTINDA (ölçüldü 2Ç26 s.24: eksen
    # top≈418-420, değerler top≈277-338). Çeyrek etiketi ("NÇ") ayrıca
    # sağdaki dipnot şeridinde de geçiyor ("677 bin yeni müşteri 2Ç
    # 2026'da katıldı", top=262) — bu yüzden en ALTTAKİ çeyrek
    # etiketi satırı seçilir.
    eksen_topu = max((k["top"] for k in kelimeler if _CEYREK_ETIKETI.fullmatch(k["text"])), default=None)
    if eksen_topu is None:
        raise okunamadi("'NÇ' eksen etiketi bulunamadı")

    eksenler = []
    for k in kelimeler:
        ceyrek = _CEYREK_ETIKETI.fullmatch(k["text"])
        if not ceyrek or abs(k["top"] - eksen_topu) > 3:
            continue
        yil = min(
            (
                w for w in kelimeler
                if re.fullmatch(r"\d{4}", w["text"])
                and abs(w["top"] - k["top"]) < 3
                and w["x0"] > k["x1"]
            ),
            key=lambda w: w["x0"],
            default=None,
        )
        if yil is not None:
            eksenler.append(((k["x0"] + k["x1"]) / 2, int(yil["text"]), int(ceyrek.group(1))))
    eksenler.sort()
    if not eksenler:
        raise okunamadi("'NÇ YYYY' eksen etiketleri eşleştirilemedi")

    # Her grafik aynı çeyrek kümesini gösterir -> sütun sayısı eksen
    # etiketlerinin benzersiz çeyrek sayısıdır, grup sayısı bölümden
    # gelir. Sabit bir boşluk eşiği kullanılmıyor: ölçülen 2Ç26'da
    # grup-içi merkez farkı en fazla 40,0pt, grup-arası en az 85,2pt
    # olduğu için her eşik keyfi olurdu.
    periyotlar = {(y, c) for _, y, c in eksenler}
    if len(eksenler) % len(periyotlar):
        raise okunamadi(f"{len(eksenler)} eksen etiketi {len(periyotlar)} çeyreğe eşit bölünmüyor")
    sutun = len(periyotlar)
    gruplar = [eksenler[i * sutun:(i + 1) * sutun] for i in range(len(eksenler) // sutun)]

    # Başlık bandı: en çok FARKLI anahtar sözcük içeren bant; eşitlikte
    # en alttaki (grafiklere en yakın) bant. Sözcük sonundaki dipnot
    # işareti atılır: 1Ç26 s.16'da başlık "Sipariş(2)" olarak çıkıyor ve
    # üstteki öne çıkanlar şeridi de "GMV ... Sipariş(2) ... GMV" taşıyor
    # (ölçüldü 2026-11-27) — yalın uzunluk ölçütü orada şeridi seçiyordu.
    def anahtar(k):
        return re.sub(r"\(\d\)$", "", k["text"])

    adaylar = sorted(
        (k for k in kelimeler if anahtar(k) in _ONLINE_BASLIK_ANAHTARLARI), key=lambda k: k["top"]
    )
    bantlar: list[list] = []
    for k in adaylar:
        if bantlar and k["top"] - bantlar[-1][0]["top"] < 20:
            bantlar[-1].append(k)
        else:
            bantlar.append([k])
    basliklari = (
        max(bantlar, key=lambda b: (len({anahtar(k) for k in b}), b[0]["top"])) if bantlar else []
    )
    baslik_sonu = max((k["top"] for k in basliklari), default=None)
    if baslik_sonu is None:
        raise okunamadi("grafik başlıkları (GMV/Sipariş/Aktif) bulunamadı")

    sayi_deseni = re.compile(r"^\d+(?:[.,]\d+)?k?$")
    sonuc: dict[str, float] = {}
    for k in basliklari:
        metrik = _ONLINE_BASLIK_ANAHTARLARI[anahtar(k)]
        merkez = (k["x0"] + k["x1"]) / 2
        # Başlık sözcüğünün kendisi eksen etiketinin TAM ortasında
        # değildir (ölçüldü 2Ç26 s.24: grup1 başlığı "GMV" merkezi
        # 167,7; en sağdaki etiket merkezi 164,0), bu yüzden ARAYA
        # DÜŞMÜYOR — başlığı en yakın eksen etiketine bağlanır.
        grup = min(gruplar, key=lambda g: min(abs(merkez - t[0]) for t in g))
        eksen_merkezi, yil, ceyrek = grup[-1]  # sağdaki sütun = sunumun kendi çeyreği
        if (yil, ceyrek) != (sunum_yili, sunum_ceyregi):
            # Yanlış çeyreğe yazmaktansa patla.
            raise okunamadi(
                f"{metrik!r} grafiğinin son sütunu {ceyrek}Ç {yil}, sunumun kendi çeyreği değil"
            )
        kutu = min(
            (
                w for w in kelimeler
                if sayi_deseni.fullmatch(w["text"])
                and baslik_sonu + 20 < w["top"] < eksen_topu - 5
                and abs((w["x0"] + w["x1"]) / 2 - eksen_merkezi) <= 20
            ),
            key=lambda w: w["top"],
            default=None,
        )
        if kutu is None:
            raise okunamadi(f"{metrik!r} için {ceyrek}Ç {yil} sütununda değer kutusu yok")
        bin_kat = 1000 if kutu["text"].endswith("k") else 1  # "327k" -> bin adet/gün
        deger = float(kutu["text"].rstrip("k").replace(",", ".")) * bin_kat
        if metrik == "migros-one-siparis-sayisi":
            deger = deger * _ceyrek_gun_sayisi(yil, ceyrek) / 1e6  # adet/gün -> milyon/çeyrek
        sonuc[metrik] = deger
    eksik = sorted(set(_ONLINE_BASLIK_ANAHTARLARI.values()) - set(sonuc))
    if eksik:
        raise okunamadi(f"şu ölçütlerin grafik başlığı bulunamadı: {eksik}")
    return sonuc


# --- 3Ç 2026'dan itibaren "Migros Ekosistemi Öne Çıkanlar" sayfası ---
#
# 3Ç 2026 sunumu (28 sayfa) ızgarayı, "Online Operasyonlar" ve
# "Fintek Operasyonları: Moneypay" sayfalarını KALDIRDI (ölçüldü
# 2026-11-27); dijital ölçütler yalnızca s.12'deki anlatı kutularında
# geçiyor:
#   "Migros One günlük sipariş sayısında +%19 3Ç25'e göre artış, 317 bine ulaştı"
#   "kayıtlı kullanıcı sayısında yıllık artış +1,3 mn ... 5,7 milyona ulaştı"
# Çapraz kontrol: 3Ç25 çeyreklik sipariş 24,5 mn x 1,19 = 29,2 mn; 317k x
# 92 gün = 29,16 mn ✓. Moneypay 3Ç25 4,4 mn + 1,3 mn = 5,7 mn ✓.
# Sunumda MUTLAK GMV (yalnızca "+%17 reel büyüme") ve aktif/tekil
# kullanıcı sayısı HİÇ yok — bkz. `_YAYIMLANMAYAN_DIJITAL_CEYREKLER`.
_ONE_CIKANLAR_BASLIGI = re.compile(r"Migros\s+Ekosistemi\s+Öne\s+Çıkanlar")
_ONE_CIKANLAR_DESENLERI = {
    "migros-one-siparis-sayisi": re.compile(
        r"günlük\s+sipariş\s+sayısında\b.{0,200}?(\d+(?:[.,]\d+)?)\s+bine\s+ulaştı", re.S
    ),
    "moneypay-kayitli-kullanici": re.compile(
        r"kayıtlı\s+kullanıcı\s+sayısında\b.{0,200}?(\d+(?:[.,]\d+)?)\s+milyona\s+ulaştı", re.S
    ),
}


def ekosistem_one_cikanlarini_ayikla(
    pdf_baytlari: bytes, sunum_yili: int, sunum_ceyregi: int
) -> dict[str, float] | None:
    """'Migros Ekosistemi Öne Çıkanlar' sayfasından sunumun KENDİ çeyreği
    için Migros One sipariş sayısını (günlük -> çeyreklik toplam, milyon)
    ve Moneypay kayıtlı kullanıcı sayısını (milyon) okur. Sayfa yoksa
    (3Ç 2026 öncesi sunumlar) None; sayfa var ama sunumun çeyrek etiketi
    ("3Ç26") ya da iki cümleden biri okunamıyorsa yükselir."""
    with pdfplumber.open(io.BytesIO(pdf_baytlari)) as pdf:
        for p in pdf.pages:
            metin = pdf_metnini_normallestir(p.extract_text() or "")
            if _ONE_CIKANLAR_BASLIGI.search(metin):
                break
        else:
            return None
    etiket = f"{sunum_ceyregi}Ç{sunum_yili % 100:02d}"
    if etiket not in metin:
        raise RuntimeError(
            f"Migros {sunum_ceyregi}Ç {sunum_yili} sunumunun 'Ekosistemi Öne Çıkanlar' "
            f"sayfasında kendi çeyrek etiketi ({etiket!r}) yok — yanlış çeyreğe yazılmaz"
        )
    sonuc: dict[str, float] = {}
    for metrik, desen in _ONE_CIKANLAR_DESENLERI.items():
        m = desen.search(metin)
        if not m:
            raise RuntimeError(
                f"Migros {sunum_ceyregi}Ç {sunum_yili} sunumunun 'Ekosistemi Öne Çıkanlar' "
                f"sayfasında {metrik!r} cümlesi okunamadı — şablon değişmiş olabilir"
            )
        deger = float(m.group(1).replace(",", "."))
        if metrik == "migros-one-siparis-sayisi":
            # bin adet/gün -> milyon/çeyrek (bkz. "BİRİM TUZAĞI" yukarıda)
            deger = deger * 1000 * _ceyrek_gun_sayisi(sunum_yili, sunum_ceyregi) / 1e6
        sonuc[metrik] = deger
    return sonuc


# Kaynağın HİÇ yayımlamadığı (metrik, çeyrek) çiftleri — yalnızca kanıtla
# eklenir. `_dijital_bosluklarini_denetle` bunlar dışında, serinin ilk
# çeyreğinden en yeni sunumun çeyreğine kadar her çeyreği zorunlu tutar.
_YAYIMLANMAYAN_DIJITAL_CEYREKLER = {
    # 3Ç 2026 sunumu s.12 yalnızca "3Ç26'da reel GMV ... +%17 büyümesi"
    # veriyor; 28 sayfanın hiçbirinde mutlak GMV yok (ölçüldü 2026-11-27).
    ("migros-one-gmv", "2026-07-01"),
    # 3Ç 2026 sunumunda aktif/tekil kullanıcı sayısı hiç geçmiyor
    # ("tekil"/"Aktif" araması: 0 eşleşme, ölçüldü 2026-11-27).
    ("migros-one-aktif-kullanici", "2026-07-01"),
}

_CEYREK_DAMGA_AYI = {1: "01", 2: "04", 3: "07", 4: "10"}


def _dijital_bosluklarini_denetle(
    birlesik: dict[str, dict[str, float]], son_yil: int, son_ceyrek: int
) -> None:
    """Her metrik için ilk çeyreğinden en yeni listelenen sunumun
    çeyreğine kadar eksik çeyrek varsa (bilinen yayımlanmayanlar hariç)
    yükselir. En yeni sunumdan sonrası (henüz yayımlanmamış) beklenmez."""
    son_tarih = f"{son_yil}-{_CEYREK_DAMGA_AYI[son_ceyrek]}-01"
    for metrik, harita in birlesik.items():
        if not harita:
            continue
        ilk = min(harita)
        yil, ceyrek = int(ilk[:4]), {"01": 1, "04": 2, "07": 3, "10": 4}[ilk[5:7]]
        eksik = []
        while True:
            tarih = f"{yil}-{_CEYREK_DAMGA_AYI[ceyrek]}-01"
            if tarih > son_tarih:
                break
            if tarih not in harita and (metrik, tarih) not in _YAYIMLANMAYAN_DIJITAL_CEYREKLER:
                eksik.append(f"{ceyrek}Ç {yil}")
            yil, ceyrek = (yil + 1, 1) if ceyrek == 4 else (yil, ceyrek + 1)
        if eksik:
            raise RuntimeError(
                f"Migros {metrik!r}: şu çeyreklerin sunumu listelendiği halde değer "
                f"okunamadı: {', '.join(eksik)}"
            )


def _dijital_metrikleri_getir(onbellek: dict, session=None) -> dict[str, dict[str, float]]:
    """Tüm sunumları TARA (ekosistem ızgarası + Moneypay başlığı +
    2Ç 2026'dan itibaren "Online Operasyonlar" sayfası), dört metriği
    birleştirip {metrik: {tarih: değer}} döner. Çakışan
    çeyreklerde SONRAKİ (kronolojik olarak daha yeni yayımlanan) sunum
    kazanır — şirket geçmiş çeyrekleri revize edebiliyor (ölçüldü:
    4Ç2024 sunumunun kendi '4Ç23' aktif kullanıcı rakamı [2,7 milyon]
    sonraki sunumlarda [3Ç2025: 5,3 milyon] geriye dönük değişti —
    muhtemelen ölçüt tanımı genişletildi; en güncel sunumun rakamı daha
    güvenilir kabul edilir, `AGENTS.md`'deki "revizyonlar yakalanmalı"
    ilkesiyle tutarlı)."""
    if "dijital" in onbellek:
        return onbellek["dijital"]
    if "sunumlar" not in onbellek:
        onbellek["sunumlar"] = _sunum_listesi(session=session)
    birlesik: dict[str, dict[str, float]] = {m: {} for m in GECERLI_DIJITAL_METRIKLERI}
    for s in sorted(onbellek["sunumlar"], key=lambda s: (s["yil"], s["ceyrek"])):
        baytlar = _sunum_pdfsini_getir(s["url"], onbellek, session=session)
        izgara = ekosistem_izgarasini_ayikla(baytlar, s["yil"], s["ceyrek"])
        if izgara:
            for metrik in GECERLI_DIJITAL_METRIKLERI:
                if metrik in izgara:
                    birlesik[metrik].update(izgara[metrik])
        ay = {1: "01", 2: "04", 3: "07", 4: "10"}[s["ceyrek"]]
        tarih = f"{s['yil']}-{ay}-01"
        moneypay = _moneypay_kayitli_kullanici_ayikla(baytlar)
        if moneypay is not None:
            birlesik["moneypay-kayitli-kullanici"][tarih] = moneypay
        # 2Ç 2026'dan itibaren dijital sayfa değişti: Migros One'ın üç
        # ölçütü artık eski ızgaradan değil "Online Operasyonlar"
        # sayfasından geliyor (yalnızca sunumun KENDİ çeyreği için).
        # AYNI sunumda ızgara da varsa (yalnızca 1Ç26: s.16 yeni sayfa +
        # s.25 ızgara) ızgara kazanır: yeni sayfa farklı çerçevede (GMV
        # 1Ç26: sayfa 25,4, ızgara 24,9) ve seri geçmişi ızgaradan geliyor.
        # Sayfa yine de ayrıştırılır — okunamıyorsa yükselir.
        online = online_operasyonlarini_ayikla(baytlar, s["yil"], s["ceyrek"])
        if online:
            for metrik, deger in online.items():
                if izgara and tarih in izgara.get(metrik, {}):
                    continue
                birlesik[metrik][tarih] = deger
        # 3Ç 2026'dan itibaren yapılandırılmış sayfalar yok; iki ölçüt
        # yalnızca "Ekosistemi Öne Çıkanlar" anlatısında (kendi çeyreği).
        one_cikan = ekosistem_one_cikanlarini_ayikla(baytlar, s["yil"], s["ceyrek"])
        if one_cikan:
            for metrik, deger in one_cikan.items():
                birlesik[metrik].setdefault(tarih, deger)
    son = max((s["yil"], s["ceyrek"]) for s in onbellek["sunumlar"])
    _dijital_bosluklarini_denetle(birlesik, *son)
    onbellek["dijital"] = birlesik
    return birlesik


def seri_cek(seri, onbellek: dict | None = None, session=None) -> pd.DataFrame:
    """Tam pencereyi yeniden çeker (artımlı değil — revizyonlar yakalanmalı).

    Üç bağımsız metrik ailesi aynı imzayı paylaşır ama farklı belge
    kümelerini tarar: `GECERLI_METRIKLER` (toplam mağaza sayısı — Ara
    Dönem Faaliyet Raporu'nun ENVANTER cümlesi), `GECERLI_FORMAT_ACILIS_METRIKLERI`
    (aynı raporun AÇILIŞ cümlesi, format bazında), `GECERLI_DIJITAL_METRIKLERI`
    (Yatırımcı Sunumu — Migros One/MoneyPay). Üçü de `onbellek` üzerinden
    kendi belge taramasını tek seferde yapıp paylaşır."""
    onbellek = onbellek if onbellek is not None else {}
    metrik = seri.migros_metrik

    if metrik in GECERLI_METRIKLER:
        if "raporlar" not in onbellek:
            onbellek["raporlar"] = _rapor_listesi(session=session)
        raporlar = _kapsamdaki_raporlar(onbellek["raporlar"], MAGAZA_ILK_DONEM, metrik)

        noktalar: list[tuple[str, float]] = []
        for r in raporlar:
            metin = _belge_metnini_getir(r["url"], onbellek, session=session)
            deger = magaza_sayisini_ayikla(metin)
            if deger is None:
                # Belge VAR ama cümle okunamadı: önceden sessizce
                # atlanıyordu (2021-2025 arası 15 dönem böyle kayboldu).
                raise RuntimeError(
                    f"Migros {r['tarih'][:7]} Ara Dönem Faaliyet Raporu'nda toplam mağaza "
                    f"sayısı cümlesi okunamadı ({r['url']}) — şablon değişmiş olabilir"
                )
            noktalar.append((r["tarih"], deger))

        if not noktalar:
            raise RuntimeError(
                f"Migros {metrik!r} için taranan {len(raporlar)} raporun "
                "hiçbirinde mağaza sayısı bulunamadı — şablon değişmiş olabilir"
            )
    elif metrik in GECERLI_FORMAT_ACILIS_METRIKLERI:
        harita = _format_acilislarini_getir(onbellek, session=session).get(metrik, {})
        if not harita:
            raise RuntimeError(f"Migros {metrik!r} için hiçbir raporda açılış cümlesi bulunamadı")
        noktalar = list(harita.items())
    elif metrik in GECERLI_DIJITAL_METRIKLERI:
        harita = _dijital_metrikleri_getir(onbellek, session=session).get(metrik, {})
        if not harita:
            raise RuntimeError(f"Migros {metrik!r} için hiçbir Yatırımcı Sunumu'nda değer bulunamadı")
        noktalar = list(harita.items())
    else:
        raise RuntimeError(f"Bilinmeyen migros_metrik: {metrik!r}")

    df = (
        pd.DataFrame(noktalar, columns=["date", "value"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return df
