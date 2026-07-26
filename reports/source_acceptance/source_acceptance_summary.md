# Tek Fiyat Kaynağı Kabul Testi Özeti

**Çalıştırma tarihi:** 2026-07-26

**Üretim zamanı:** 2026-07-26T03:09:35+03:00

**Kaynak kabul sonucu:** `FAIL`

**Sonuç gerekçesi:** Kaynak koşusu 5 sağlayıcı hatasıyla eksik kaldı; gerekli tüm hisse ve dönemler alınamadı.

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

## Nominal OHLC iç tutarlılığı ve eksikler

Ana kontrol yalnız tek kaynaklı nominal alanlarla yapılır:

```text
yf_nominal_low <= yf_nominal_open <= yf_nominal_high
yf_nominal_low <= yf_nominal_close <= yf_nominal_high
```

| period | expected_isyatirim_days | yfinance_matching_days | yfinance_date_match_rate | missing_nominal_open_count | missing_nominal_high_low_close_count | invalid_nominal_ohlc_count | nominal_ohlc_validity_rate | split_factor_unavailable_count | corporate_action_window_count | cross_source_price_warning_count | open_present_both_volumes_missing_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| start_boundary | 120 | 120 | 1 | 0 | 0 | 0 | 1 | 0 | 3 | 120 | 0 |
| price_step_change | 110 | 110 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 98 | 0 |
| recent_90_calendar_days | 290 | 290 | 1 | 0 | 0 | 0 | 1 | 0 | 9 | 208 | 0 |
| full_period | 4767 | 4765 | 0.99958 | 2 | 2 | 0 | 1 | 0 | 96 | 3998 | 0 |

Tekil eksik veya geçersiz satırlar `NO_OPEN`/`INVALID_OHLC` durumlarıyla `NA` bırakılabilir ve tek başına kabulü başarısız yapmaz. Hisse bazındaki ayrıntılar `source_acceptance_metrics.csv` dosyasındadır.

## Hacim sonuçları

Açılış mevcutken iki hacmin de eksik olduğu benzersiz takvim kaydı: **0**. İş Yatırım TL hacmi ve yFinance pay adedi birlikte sıfırsa `NO_TRADE`; tek kaynak eksik/sıfırsa `SOURCE_VOLUME_CONFLICT` kalite uyarısı üretilir. İki hacim de eksikken open mevcutsa D022 uyarınca yeni bir kesin karar verilmez.

## D022 ve D023 uygulanabilirliği

- **D022: UYGULANABİLİR.** Giriş fiyatı `yf_nominal_open` üzerinden değerlendirilir. `NO_OPEN`, `NO_TRADE` ve `INVALID_OHLC` kodları üretilebilir.
- **D023: UYGULANABİLİR (tespit sinyallerinin bilinen sınırlamalarıyla).** `T+1–T+3` içinde kurumsal işlem sinyali bulunan **126** tahmin satırı `CORPORATE_ACTION_WINDOW` ile `NA` yapılabilir.
- Kapsama giren benzersiz action satırı: **33**; yFinance action günü: **41**; İş Yatırım düzeltme faktörü değişim günü: **41**.

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
| KCHOL | 2020-04-06 00:00:00 | 0.2095 | 0 | 1 | both |
| SISE | 2020-05-29 00:00:00 | 0.142222 | 0 | 1 | both |
| SISE | 2021-05-31 00:00:00 | 0.163227 | 0 | 1 | both |
| SISE | 2022-05-31 00:00:00 | 0.408068 | 0 | 1 | both |
| SISE | 2023-05-31 00:00:00 | 0.685554 | 0 | 1 | both |
| SISE | 2024-05-31 00:00:00 | 0.7182 | 0 | 1 | both |
| SISE | 2025-05-30 00:00:00 | 0.652909 | 0 | 1 | both |
| SISE | 2026-06-01 00:00:00 | 0.587618 | 0 | 1 | both |
| TUPRS | 2023-03-10 00:00:00 | 6.48745 | 0 | 7 | both |
| TUPRS | 2023-04-04 00:00:00 | 0 | 7 | 1 | both |
| TUPRS | 2023-09-29 00:00:00 | 15.0509 | 0 | 1 | both |
| TUPRS | 2024-04-03 00:00:00 | 10.3799 | 0 | 1 | both |
| TUPRS | 2024-09-27 00:00:00 | 11.9369 | 0 | 1 | both |

## Çapraz kaynak fiyat kalite uyarıları

İş Yatırım ham fiyatları yFinance nominal fiyatlarıyla yalnız kalite kontrolü için karşılaştırıldı. Farklar `cross_source_price_warning` üretir; satırı otomatik dışlamaz ve `PASS/PARTIAL/FAIL` sonucunu etkilemez. Sabit bir yüzdesel veya fiyat-adımı eşiği eklenmedi.

En büyük normal-gün nominal-open/İş Yatırım aralık farklarından örnekler:

| ticker | date | yf_nominal_open | is_raw_low | is_raw_high | nominal_open_range_gap | nominal_open_range_gap_pct |
| --- | --- | --- | --- | --- | --- | --- |
| BIMAS | 2026-05-21 00:00:00 | 392.75 | 376.5 | 376.5 | 16.25 | 4.31607 |
| TUPRS | 2026-05-21 00:00:00 | 249.1 | 241.7 | 241.7 | 7.40001 | 3.06165 |
| SISE | 2026-05-21 00:00:00 | 46.3 | 42.9 | 42.9 | 3.4 | 7.92541 |
| SISE | 2026-03-23 00:00:00 | 43.7 | 46.74 | 48.68 | 3.04 | 6.24486 |
| TUPRS | 2023-01-23 00:00:00 | 601 | 601 | 628 | 2.28882e-05 | 3.75524e-06 |
| TUPRS | 2022-12-06 00:00:00 | 478.9 | 478.9 | 487.7 | 1.37329e-05 | 2.84679e-06 |
| TUPRS | 2021-10-04 00:00:00 | 113.8 | 113.8 | 116.5 | 1.2207e-05 | 1.05233e-05 |
| TUPRS | 2022-06-06 00:00:00 | 276 | 276 | 284.5 | 1.14441e-05 | 4.0654e-06 |
| TUPRS | 2022-12-19 00:00:00 | 454.6 | 454.6 | 470.3 | 9.15527e-06 | 1.95208e-06 |
| TUPRS | 2022-03-17 00:00:00 | 192.8 | 192.8 | 200.5 | 6.48499e-06 | 3.27029e-06 |
| BIMAS | 2023-01-30 00:00:00 | 134.1 | 128.2 | 134.1 | 6.10352e-06 | 4.75722e-06 |
| TUPRS | 2024-01-04 00:00:00 | 140.9 | 140.9 | 143.9 | 6.10352e-06 | 4.2474e-06 |
| TUPRS | 2024-01-16 00:00:00 | 141.4 | 141.4 | 143.9 | 6.10352e-06 | 4.26223e-06 |
| TUPRS | 2024-02-01 00:00:00 | 150.4 | 150.4 | 155.7 | 6.10352e-06 | 3.94539e-06 |
| TUPRS | 2024-07-03 00:00:00 | 164.9 | 164.9 | 168.8 | 6.10352e-06 | 3.62657e-06 |
| TUPRS | 2025-11-19 00:00:00 | 203.9 | 203.9 | 208.5 | 6.10352e-06 | 2.9557e-06 |
| TUPRS | 2026-06-22 00:00:00 | 226.1 | 220.7 | 226.1 | 6.10352e-06 | 2.76553e-06 |
| BIMAS | 2023-11-02 00:00:00 | 277.4 | 277.4 | 290.5 | 6.10352e-06 | 2.1083e-06 |
| TUPRS | 2023-02-07 00:00:00 | 576.6 | 521.1 | 576.6 | 6.10352e-06 | 1.16769e-06 |
| TUPRS | 2023-02-15 00:00:00 | 574.9 | 574.9 | 574.9 | 6.10352e-06 | 1.06167e-06 |

Ayrıntılı karşılaştırmalar `source_scale_normalization.csv` dosyasındadır. Bunlar ana OHLC başarı metriği değildir.

## Veri sızıntısı kontrolü

- `yf_future_split_factor` ve action alanları `MODEL_FEATURE_COLUMNS` içinde değildir; LightGBM'e ve tahmin sinyaline verilmez.
- Gelecekteki split bilgisi yalnız geçmiş fiyat birimini dönemin nominal ölçeğine geri kurar.
- Aynı split faktörü open, high, low ve close'a birlikte uygulanır; dönüşüm oran ilişkilerini değiştirmez.
- `T+1–T+3` kurumsal işlem penceresi yalnız label/backtest uygunluğunda `NA` üretir, tahmin feature'ı değildir.
- İş Yatırım düzeltilmiş/ham faktörü ve çapraz fiyat farkı yalnız kalite alanıdır.
- Bu görev model feature'ı, label veya backtest sonucu üretmez.

## Tekrarlanabilirlik ve bilinen sınırlamalar

- yFinance geçmiş action ve fiyat değerlerini sonradan revize edebilir.
- Ham yFinance yanıtları ve split kayıtları değişmez veri sürümleriyle saklanmadan eski koşular birebir yeniden üretilemez.
- Bu kabul çalıştırıcısı ham kaynakları sürümlemediği için yeniden indirme farkı henüz otomatik tespit edilmez.
- İş Yatırım düzeltme faktörü olay türünü tek başına kanıtlamaz; KAP ilk sürümün zorunlu kaynağı değildir.

## Başarısız veya eksik kalan kontroller

- İş Yatırım failed for THYAO 2022-01-01..2022-12-31 after 5 attempts: No data was fetched for any symbol. Please check the symbols and date ranges.
- İş Yatırım failed for GARAN 2020-03-01..2020-12-31 after 5 attempts: No data was fetched for any symbol. Please check the symbols and date ranges.
- İş Yatırım failed for ASELS 2021-01-01..2021-12-31 after 5 attempts: No data was fetched for any symbol. Please check the symbols and date ranges.
- İş Yatırım failed for EREGL 2020-03-01..2020-12-31 after 5 attempts: No data was fetched for any symbol. Please check the symbols and date ranges.
- İş Yatırım failed for SASA 2020-03-01..2020-12-31 after 5 attempts: No data was fetched for any symbol. Please check the symbols and date ranges.

## Açık sorular

- Açılış mevcutken iki hacim alanının da eksik olduğu kayıtların nihai davranışı ayrı karara ihtiyaç duyar.
- İş Yatırım faktör değişim sinyalinin olay tarihi ve türü için ek doğrulama yöntemi gerekebilir.
- Ham veri sürümleme ve sağlayıcı revizyon farkı tespiti veri toplama altyapısında henüz uygulanmadı.

## Önerilen sıradaki görev

Sağlayıcı erişimi kararlı olduğunda eksiksiz gerçek veri kabul koşusunu yeniden çalıştırmak; kabul verilmeden genel veri/label akışına geçmemek.
