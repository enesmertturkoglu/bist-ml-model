# Tek Fiyat Kaynağı Kabul Testi Özeti

**Çalıştırma tarihi:** 2026-07-26

**Üretim zamanı:** 2026-07-26T23:05:31+03:00

**Kaynak kabul sonucu:** `PASS`

**Sonuç gerekçesi:** yFinance nominal OHLC üretimi ve iç tutarlılığı doğrulandı; 7 eksik ve 0 geçersiz satır açık durum kodlarıyla dışlanabilir. 14386 çapraz kaynak fiyat farkı yalnız kalite uyarısıdır ve kabul sonucunu etkilemez.

## Ana fiyat kaynağı

İlk sürümde giriş, label, çıkış, OHLC geçerlilik ve tavan hesabı için tek fiyat kaynağı **yFinance nominal OHLC** serisidir. İş Yatırım fiyatları ana işlem hesabına katılmaz; yalnız `cross_source_price_warning` kalite uyarısı, kurumsal işlem sinyali ve denetim amacıyla kullanılır.

Orijinal yFinance değerleri `yf_provider_open/high/low/close` alanlarında değiştirilmeden tutulur. Nominal dönüşüm:

```text
yf_future_split_factor[t] = t tarihinden kesinlikle sonra gerçekleşen geçerli split oranlarının çarpımı
yf_nominal_price[t] = yf_provider_price[t] × yf_future_split_factor[t]
```

Split gününün kendi oranı aynı günün fiyatına uygulanmaz. Aynı faktör open, high, low ve close alanlarının tamamına uygulanır.

## Kullanılan ortam ve kütüphane sürümleri

- Python: `3.13.2`
- İşletim sistemi: `Windows-10-10.0.19045-SP0`
- pandas: `2.3.3`
- numpy: `2.3.5`
- isyatirimhisse: `5.0.1`
- yfinance: `1.5.2`
- requests: `2.32.5`
- pytest: `9.1.1`

## Test edilen hisseler ve dönemler

- `start_boundary`: 2020-03-13 – 2020-04-15; THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL, HEKTS
- `price_step_change`: 2023-10-20 – 2023-11-20; THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL, HEKTS
- `recent_90_calendar_days`: 2026-04-28 – 2026-07-26; THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL, HEKTS
- `full_period`: 2020-03-13 – 2026-07-26; THYAO, BIMAS, TUPRS, SISE, SASA

Ana BİST işlem takvimi İş Yatırım'dan kuruldu. yFinance `end` sınırının hariç olması ve Europe/Istanbul yerel tarihleri açıkça ele alındı.

## Kaynak alanları

- İş Yatırım zorunlu alanları mevcut: **evet**
- yFinance zorunlu alanları mevcut: **evet**
- İş Yatırım sütunları: `DD_DEGER, DD_DOVIZ_KODU, DD_DT_KODU, DD_TARIH, DOLAR_BAZLI_AOF, DOLAR_BAZLI_FIYAT, DOLAR_BAZLI_MAX, DOLAR_BAZLI_MIN, DOLAR_HACIM, ENDEKS_BAZLI_FIYAT, END_DEGER, END_ENDEKS_KODU, END_SEANS, END_TARIH, HAO_PD, HAO_PD_USD, HGDG_AOF, HGDG_HACIM, HGDG_HS_KODU, HGDG_KAPANIS, HGDG_MAX, HGDG_MIN, HGDG_TARIH, HG_AOF, HG_HACIM, HG_KAPANIS, HG_MAX, HG_MIN, PD, PD_USD, SERMAYE`
- yFinance sütunları: `Adj Close, Close, Dividends, High, Low, Open, Stock Splits, Volume`

Bu kabul çalıştırıcısı ham yanıtları repoya yazmaz. D024'ün gerektirdiği değişmez ham yanıt/split sürümleme ve yeniden indirme farkı tespiti, veri toplama altyapısında uygulanması gereken açık tekrarlanabilirlik işidir.

## Dayanıklı İş Yatırım istemcisi

- Read timeout: **60 saniye** (`connect=10` saniye)
- Yapılandırılan maksimum deneme sayısı: **5**
- Gerçek retry sayısı: **0**
- Minimum parça: **3 ay**
- İstekler arası temel gecikme: **1 saniye + jitter**
- Yıllık çağrı sayısı: **0**
- Altı aylık çağrı sayısı: **0**
- Üç aylık çağrı sayısı: **0**
- Altı aylığa bölünen parça sayısı: **0**
- Üç aylığa bölünen parça sayısı: **0**
- Cache hit sayısı: **70**
- Gerçek ağ isteği sayısı: **0**
- Timeout sayısı: **0**
- Timeout sonrasında başarıya ulaşan parça sayısı: **0**
- Tamamen başarısız kalan minimum parça sayısı: **0**
- Bozuk/okunamayan cache kaydı sayısı: **0**

İstekler paralel gönderilmedi. Operasyonel cache yalnız kabul koşusuna devam etmek içindir; D024'ün kalıcı ve sürümlenmiş ham veri arşivi değildir.

### Cache okuma sorunları

_Bozuk veya okunamayan cache kaydı gözlenmedi._

## Nominal OHLC iç tutarlılığı ve eksikler

Ana kontrol yalnız tek kaynaklı nominal alanlarla yapılır:

```text
yf_nominal_low <= yf_nominal_open <= yf_nominal_high
yf_nominal_low <= yf_nominal_close <= yf_nominal_high
```

| period | expected_isyatirim_days | yfinance_matching_days | yfinance_date_match_rate | missing_nominal_open_count | missing_nominal_high_low_close_count | invalid_nominal_ohlc_count | nominal_ohlc_validity_rate | split_factor_unavailable_count | corporate_action_window_count | cross_source_price_warning_count | open_present_both_volumes_missing_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| start_boundary | 240 | 240 | 1 | 0 | 0 | 0 | 1 | 0 | 3 | 240 | 0 |
| price_step_change | 220 | 220 | 1 | 0 | 0 | 0 | 1 | 0 | 2 | 207 | 0 |
| recent_90_calendar_days | 580 | 580 | 1 | 0 | 0 | 0 | 1 | 0 | 12 | 385 | 0 |
| full_period | 7945 | 7942 | 0.999622 | 3 | 3 | 0 | 1 | 0 | 114 | 6538 | 0 |

Tekil eksik veya geçersiz satırlar `NO_OPEN`/`INVALID_OHLC` durumlarıyla `NA` bırakılabilir ve tek başına kabulü başarısız yapmaz. Hisse bazındaki ayrıntılar `source_acceptance_metrics.csv` dosyasındadır.

## Hacim sonuçları

Açılış mevcutken iki hacmin de eksik olduğu benzersiz takvim kaydı: **0**. İş Yatırım TL hacmi ve yFinance pay adedi birlikte sıfırsa `NO_TRADE`; tek kaynak eksik/sıfırsa `SOURCE_VOLUME_CONFLICT` kalite uyarısı üretilir. İki hacim de eksikken open mevcutsa D022 uyarınca yeni bir kesin karar verilmez.

## D022 ve D023 uygulanabilirliği

- **D022: UYGULANABİLİR.** Giriş fiyatı `yf_nominal_open` üzerinden değerlendirilir. `NO_OPEN`, `NO_TRADE` ve `INVALID_OHLC` kodları üretilebilir.
- **D023: UYGULANABİLİR (tespit sinyallerinin bilinen sınırlamalarıyla).** `T+1–T+3` içinde kurumsal işlem sinyali bulunan **213** tahmin satırı `CORPORATE_ACTION_WINDOW` ile `NA` yapılabilir.
- Kapsama giren benzersiz action satırı: **40**; yFinance action günü: **70**; İş Yatırım düzeltme faktörü değişim günü: **70**.

| ticker | date | yf_dividends | yf_stock_splits | yf_future_split_factor | corporate_action_source |
| --- | --- | --- | --- | --- | --- |
| BIMAS | 2020-05-13 00:00:00 | 0.25 | 0 | 2 | both |
| BIMAS | 2020-10-14 00:00:00 | 0.4 | 0 | 2 | yfinance_only |
| BIMAS | 2021-01-08 00:00:00 | 1 | 0 | 2 | both |
| BIMAS | 2021-05-20 00:00:00 | 1 | 0 | 2 | both |
| BIMAS | 2021-11-17 00:00:00 | 1 | 0 | 2 | both |
| BIMAS | 2022-06-15 00:00:00 | 0.75 | 0 | 2 | both |
| BIMAS | 2022-12-14 00:00:00 | 0.75 | 0 | 2 | both |
| BIMAS | 2023-06-14 00:00:00 | 1 | 0 | 2 | both |
| BIMAS | 2023-12-20 00:00:00 | 1.5 | 0 | 2 | both |
| BIMAS | 2024-07-17 00:00:00 | 1 | 0 | 2 | both |
| BIMAS | 2024-10-02 00:00:00 | 2 | 0 | 2 | both |
| BIMAS | 2024-12-18 00:00:00 | 2 | 0 | 2 | both |
| BIMAS | 2025-06-18 00:00:00 | 2 | 0 | 2 | both |
| BIMAS | 2025-09-17 00:00:00 | 2 | 0 | 2 | both |
| BIMAS | 2025-12-17 00:00:00 | 2.5 | 0 | 2 | both |
| BIMAS | 2026-05-14 00:00:00 | 0 | 2 | 1 | both |
| BIMAS | 2026-06-17 00:00:00 | 2 | 0 | 1 | both |
| EREGL | 2026-06-03 00:00:00 | 0.55 | 0 | 1 | both |
| KCHOL | 2020-04-06 00:00:00 | 0.2095 | 0 | 1 | both |
| SASA | 2021-04-27 00:00:00 | 0 | 1.3494 | 37.2668 | both |
| SASA | 2022-05-05 00:00:00 | 0 | 2 | 18.6334 | both |
| SASA | 2023-05-23 00:00:00 | 0 | 2.32918 | 8 | both |
| SASA | 2024-08-12 00:00:00 | 0 | 8 | 1 | both |
| SISE | 2020-05-29 00:00:00 | 0.142222 | 0 | 1 | both |
| SISE | 2021-05-31 00:00:00 | 0.163227 | 0 | 1 | both |
| SISE | 2022-05-31 00:00:00 | 0.408068 | 0 | 1 | both |
| SISE | 2023-05-31 00:00:00 | 0.685554 | 0 | 1 | both |
| SISE | 2024-05-31 00:00:00 | 0.7182 | 0 | 1 | both |
| SISE | 2025-05-30 00:00:00 | 0.652909 | 0 | 1 | both |
| SISE | 2026-06-01 00:00:00 | 0.587618 | 0 | 1 | both |

## Çapraz kaynak fiyat kalite uyarıları

İş Yatırım ham fiyatları yFinance nominal fiyatlarıyla yalnız kalite kontrolü için karşılaştırıldı. Farklar `cross_source_price_warning` üretir; satırı otomatik dışlamaz ve `PASS/PARTIAL/FAIL` sonucunu etkilemez. Sabit bir yüzdesel veya fiyat-adımı eşiği eklenmedi.

En büyük normal-gün nominal-open/İş Yatırım aralık farklarından örnekler:

| ticker | date | yf_nominal_open | is_raw_low | is_raw_high | nominal_open_range_gap | nominal_open_range_gap_pct |
| --- | --- | --- | --- | --- | --- | --- |
| THYAO | 2026-05-21 00:00:00 | 295 | 274 | 274 | 21 | 7.66423 |
| BIMAS | 2026-05-21 00:00:00 | 392.75 | 376.5 | 376.5 | 16.25 | 4.31607 |
| TUPRS | 2026-05-21 00:00:00 | 249.1 | 241.7 | 241.7 | 7.40001 | 3.06165 |
| THYAO | 2026-04-22 00:00:00 | 329.5 | 323 | 324 | 5.5 | 1.70015 |
| THYAO | 2026-03-23 00:00:00 | 281.25 | 285.75 | 295.5 | 4.5 | 1.52284 |
| SISE | 2026-05-21 00:00:00 | 46.3 | 42.9 | 42.9 | 3.4 | 7.92541 |
| SISE | 2026-03-23 00:00:00 | 43.7 | 46.74 | 48.68 | 3.04 | 6.24486 |
| SASA | 2026-05-21 00:00:00 | 2.82 | 2.53 | 2.53 | 0.29 | 11.4624 |
| SASA | 2024-04-09 00:00:00 | 40.38 | 40.42 | 41.88 | 0.0399989 | 0.0966158 |
| SASA | 2020-03-31 00:00:00 | 8.24995 | 8.25 | 8.77 | 4.69737e-05 | 0.000535618 |
| SASA | 2021-02-03 00:00:00 | 26 | 26 | 27.74 | 4.00417e-05 | 0.00014678 |
| SASA | 2020-12-18 00:00:00 | 18.93 | 18.93 | 19.57 | 3.99198e-05 | 0.000206838 |
| SASA | 2020-11-04 00:00:00 | 15.4 | 15.4 | 15.75 | 3.72283e-05 | 0.000238032 |
| SASA | 2020-03-23 00:00:00 | 4.86996 | 4.87 | 5.17 | 3.61781e-05 | 0.00072793 |
| SASA | 2021-11-29 00:00:00 | 39.82 | 39.82 | 43.36 | 3.57852e-05 | 8.32989e-05 |
| SASA | 2022-03-18 00:00:00 | 53.15 | 53.15 | 54.75 | 3.4843e-05 | 6.39908e-05 |
| SASA | 2020-12-22 00:00:00 | 18.94 | 18.94 | 19.46 | 3.316e-05 | 0.000172708 |
| SASA | 2020-07-13 00:00:00 | 11.25 | 11.25 | 12.02 | 3.25144e-05 | 0.000273921 |
| SASA | 2021-12-13 00:00:00 | 47.18 | 47.18 | 49.34 | 2.71997e-05 | 5.59895e-05 |
| SASA | 2020-11-18 00:00:00 | 16.87 | 16.87 | 17.21 | 2.66738e-05 | 0.000155714 |

Ayrıntılı karşılaştırmalar `source_scale_normalization.csv` dosyasındadır. Bunlar ana OHLC başarı metriği değildir.

## Veri sızıntısı kontrolü

- `yf_future_split_factor` ve action alanları `MODEL_FEATURE_COLUMNS` içinde değildir; LightGBM'e ve tahmin sinyaline verilmez.
- Gelecekteki split bilgisi yalnız geçmiş fiyat birimini dönemin nominal ölçeğine geri kurar.
- Aynı split faktörü open, high, low ve close'a birlikte uygulanır; dönüşüm oran ilişkilerini değiştirmez.
- `T+1–T+3` kurumsal işlem penceresi yalnız label/backtest uygunluğunda `NA` üretir, tahmin feature'ı değildir.
- İş Yatırım düzeltilmiş/ham faktörü ve çapraz fiyat farkı yalnız kalite alanıdır.
- İş Yatırım cache'i yalnız veri erişimini hızlandırır; tahmin bilgisi üretmez. Cache ve doğrudan sağlayıcı verisi aynı normalizasyon yolundan geçer.
- Bu görev model feature'ı, label veya backtest sonucu üretmez.

## Tekrarlanabilirlik ve bilinen sınırlamalar

- yFinance geçmiş action ve fiyat değerlerini sonradan revize edebilir.
- Ham yFinance yanıtları ve split kayıtları değişmez veri sürümleriyle saklanmadan eski koşular birebir yeniden üretilemez.
- Bu kabul çalıştırıcısı ham kaynakları sürümlemediği için yeniden indirme farkı henüz otomatik tespit edilmez.
- İş Yatırım düzeltme faktörü olay türünü tek başına kanıtlamaz; KAP ilk sürümün zorunlu kaynağı değildir.

## Başarısız veya eksik kalan kontroller

_Sağlayıcı hatası veya tamamlanmamış ana kontrol bulunmuyor._

## Açık sorular

- Açılış mevcutken iki hacim alanının da eksik olduğu kayıtların nihai davranışı ayrı karara ihtiyaç duyar.
- İş Yatırım faktör değişim sinyalinin olay tarihi ve türü için ek doğrulama yöntemi gerekebilir.
- Ham veri sürümleme ve sağlayıcı revizyon farkı tespiti veri toplama altyapısında henüz uygulanmadı.

## Önerilen sıradaki görev

Veri toplama, değişmez ham veri sürümleme ve sağlayıcı revizyon tespiti altyapısını kurmak; ardından D022 ve D023 durum kodlarını modüler veri temizleme akışına taşımak.
