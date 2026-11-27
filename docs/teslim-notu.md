# BV Market Dashboard — Teslim Notu

Tarih: 2026-11-13 · Durum: **teslim koşulu bekleniyor** (aşağıda)

## Ne teslim ediliyor

Türkiye makro, sektör ve emtia verilerini her gün kaynağından çekip grafik
sayfaları olarak sunan, BV Portföy iç kullanımına yönelik bir pano.

| | |
|---|---|
| Veri serisi | 4.226 |
| Kategori sayfası | 51 (6 grup) |
| Hisse sayfası | 8 |
| Sabit sayfa | 6 (Genel Bakış, Ara, Favoriler, Raporlar, Fonlar, Veri Takvimi) |
| Kaynak adaptörü | 57 |
| Otomatik test | 1.421 |

Kapsam donduruldu. Referans siteye (`marketvisuals.net`) göre karşılama
%92,1; kalan boşlukların dökümü `docs/kapsam-bosluklari.md` dosyasında.

## Teslim koşulu

Teslim, **2026-11-16 Pazartesi tam veri koşusunun yeşil dönmesiyle**
tamamlanır. 13 Kasım'da yapılan adaptör düzeltmeleri yerelde canlı kaynaklara
karşı doğrulandı, ancak GitHub koşusunda ilk kez o gün çalışacak.

Koşu kırmızı dönerse: Actions özetindeki "✗" satırlarına bakın. Kırmızı,
tanım gereği bizim kodumuzdaki bir hatadır; kaynağa erişilememesi koşuyu
kırmızı yapmaz.

## 13 Kasım 2026 kabul kontrolü

| Kontrol | Sonuç |
|---|---|
| Test paketi | 1.421 geçti |
| Sayfa taraması (65 sayfa, başsız) | İstisna, hata ve uyarı yok |
| Bayat seri raporu | 20 seri gecikmiş, tamamı açıklama notlu; notsuz 0 |
| Gözle (tarayıcıda) kontrol | **Yapılmadı** |

## Bilinen sınırlar

- **74 seri açıklama notu taşıyor** (`yayin_notu`): kaynağı geride, seyrek ya
  da erişime kapalı. Not, serinin kartında görünür. En büyük gruplar: EVDS
  turizm ve benzeri (20), Fintables THYAO finansalları (17, kaynak 403
  dönüyor, son veri 2026 2. çeyrek).
- **Aylık, çeyreklik ve yıllık seriler haftada iki kez güncellenir**
  (Pazartesi, Perşembe); günlük ve haftalık seriler her gün.
- **Kaynak şablonu değişince adaptör kırılır.** Bu beklenen bir bakım
  yüküdür: 13 Kasım'da beş kaynakta (UAB, OSD, THY trafik, THY sunum, AYD)
  şablon kayması düzeltildi.
- **Kısmi veri dönüşü kısmen engelleniyor.** Bir kaynak mevcut CSV'nin
  yarısından kısa veri döndürürse yazılmaz, eski veri kalır ve koşu özetinde
  uyarı çıkar (Yahoo TTF doğal gazda Kasım 2026'da üç kez tek satıra
  düşmüştü). Tek bir ayın ya da çeyreğin sessizce eksik gelmesi hâlâ
  yakalanmıyor; taramada 11 adaptörde bu risk görüldü.
- **Uygulama uykuya dalar**; günün ilk kullanıcısı ~30 saniye bekler.

## Bakım

| İş | Nasıl |
|---|---|
| Günlük sağlık | GitHub Actions → "Veri güncelle" koşusu ve özetindeki bayat seri raporu |
| Yeni seri | `catalog/series.yaml`'a kayıt + `python -m ingest.run --only <id>` |
| Yeni hisse sayfası | `catalog/hisseler.yaml`'a kayıt |
| Bayat seri | Düzelt, katalogdan çıkar ya da `yayin_notu` ekle; notsuz bayat seri bırakma |
| Zamanlama | cron-job.org her gün 09:00 TSİ'de workflow'u tetikler |
| Kimlik bilgileri | GitHub repo secret'ları: `EVDS_API_KEY`, `EPIAS_USERNAME`, `EPIAS_PASSWORD` |

Geliştirici rehberi: `AGENTS.md`. Kullanıcıya dönük özet: `README.md`.

## Teslim sonrası ilk bakım işi — TAMAMLANDI (2026-11-27)

Sessiz eksik dönem: 13 Kasım taramasında 11 adaptör tek bir ayı ya da
çeyreği okuyamadığında hata vermeden atlıyordu. 27 Kasım'da hepsinde
"henüz yayımlanmadı" (en yeni dönem, belgelenmiş kalıcı boşluk, OSD "-"
hücresi) ile "okunamadı" (belge var ama ayrıştırılamadı) ayrıldı; okunamama
artık hatayla durur. Bilinen kalıcı boşluklar kanıtlı adlandırılmış
sabitlerde (ör. `tim.PM_METINSIZ_BULTENLER`, `ayd.BILINEN_BOSLUKLAR`). Her
adaptör canlı kaynağa karşı bağımsız olarak doğrulandı: bugünkü kaynakta
hiçbiri hata vermiyor.

| Adaptör | Sessizce düşen ve geri gelen |
|---|---|
| TİM pazar monitörü | 2024-02 bülteni (47 seri) |
| TAB Gıda | 2026 3Ç |
| KTB sınır bülteni | 2 seri 2 yıl geri sarılmıştı (2026-11-23): Ekim bülteni `.XLS` uzantılıydı |
| OSD, ebebek, Migros, BigChefs, Orge, EİB, BDDK (aylık + BDMK + haftalık), AYD, TÇÜD | Bugün eksik dönem yok; atlama yolları kapatıldı |

Ek koruma: `seriyi_yaz`, yeni verinin son tarihi mevcut CSV'ninkinden
`GERI_SARMA_ESIGI_GUN` (100) günden eskiyse yazmaz ve koşuyu kırmızı yapar
(KTB vakası satır sayısı değişmediği için kısalma korumasından geçmişti).

## Verilen kararlar

- Kapsam 4.226 seride donduruldu; teslimden önce yeni seri ya da kaynak
  eklenmez.
- Teslim iki koşulla tamamlanır: Pazartesi tam koşusunun yeşil dönmesi ve
  proje sahibinin tarayıcıda gözle kontrolü.

- GitHub deposu bilinçli olarak herkese açık (public): kod ve tüm veri
  dışarıdan okunabilir, Actions dakikaları ücretsizdir. Depoya gizli kalması
  gereken hiçbir şey commit edilmemeli.
