# Kaynak Kabul Testi Özeti

**Çalıştırma tarihi:** 2026-07-26

**Üretim zamanı:** 2026-07-26T02:15:09+03:00

**Kaynak kabul sonucu:** `PARTIAL`

**Sonuç gerekçesi:** Split ölçeği sistematik olarak düzeldi ancak normal günlerde 188 tutarsızlık kaldı; kabul toleransı henüz kesinleştirilmedi.

## Amaç

İş Yatırım/`isyatirimhisse` ana fiyat-takvim kaynağı ile yFinance tamamlayıcı açılış, adet hacmi ve kurumsal işlem kaynağının D022 ve D023 kurallarını destekleyip desteklemediğini gerçek veride ölçmek; yFinance geçmiş OHLC değerlerini gelecekteki split oranlarıyla dönemin nominal fiyat ölçeğine geri taşıma yaklaşımını sınamak.

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

İş Yatırım ve yFinance verileri, dönem sınırı hesaplarını güvenli yapmak için `2020-03-01` tarihinden `2026-07-26` tarihine kadar çekildi; metrikler yalnızca yukarıdaki kapsamlarda hesaplandı. yFinance `end` parametresi hariç olduğundan kapsayıcı bitiş tarihine bir gün eklendi. Zaman dilimli yFinance indeksleri, saat dilimi dönüştürülmeden yerel takvim tarihine indirildi.

## Gerçek veri sütunları

### İş Yatırım / isyatirimhisse

`DD_DEGER, DD_DOVIZ_KODU, DD_DT_KODU, DD_TARIH, DOLAR_BAZLI_AOF, DOLAR_BAZLI_FIYAT, DOLAR_BAZLI_MAX, DOLAR_BAZLI_MIN, DOLAR_HACIM, ENDEKS_BAZLI_FIYAT, END_DEGER, END_ENDEKS_KODU, END_SEANS, END_TARIH, HAO_PD, HAO_PD_USD, HGDG_AOF, HGDG_HACIM, HGDG_HS_KODU, HGDG_KAPANIS, HGDG_MAX, HGDG_MIN, HGDG_TARIH, HG_AOF, HG_HACIM, HG_KAPANIS, HG_MAX, HG_MIN, PD, PD_USD, SERMAYE`

### yFinance

`Adj Close, Close, Dividends, High, Low, Open, Stock Splits, Volume`

Ham yanıtların tamamı repoya kaydedilmedi. İş Yatırım `HG_*` alanları ham; `HGDG_*` alanları düzeltilmiş seri olarak eşlendi. Ana işlem takvimi `HGDG_TARIH` alanından kuruldu. yFinance çağrılarında açıkça `auto_adjust=False` ve `actions=True` kullanıldı. Orijinal yFinance OHLC değerleri `yf_provider_*`, dönemin nominal ölçeğine geri taşınan karşılıkları `yf_nominal_*` alanlarında ayrı tutuldu.

## İş Yatırım sonuçları

Gözlenen zorunlu sütunların tamamı mevcut: **evet**. Ham `high`, `low`, `close`, ağırlıklı ortalama fiyat ve TL hacmi sırasıyla `HG_MAX`, `HG_MIN`, `HG_KAPANIS`, `HG_AOF`, `HG_HACIM/HGDG_HACIM`; düzeltilmiş karşılıkları `HGDG_MAX`, `HGDG_MIN`, `HGDG_KAPANIS`, `HGDG_AOF` alanlarından alındı. `PD`, `PD_USD`, `HAO_PD`, `HAO_PD_USD` piyasa değeri alanları da gözlendi.

## yFinance sonuçları

Gözlenen zorunlu sütunların tamamı mevcut: **evet**. Sağlayıcı açılışı ve adet hacmi `Open` ve `Volume` alanlarından, kurumsal işlem kayıtları `Dividends` ve `Stock Splits` alanlarından alındı. `Adj Close` ayrı alan olarak korundu. Nominal fiyat dönüşümü `yf_nominal_price[t] = yf_provider_price[t] × t tarihinden sonra gerçekleşen geçerli split oranlarının çarpımı` formülünü kullanır; split gününün kendi oranı o günün fiyatına uygulanmaz.

## Tarih eşleşme sonuçları

| period | expected_isyatirim_days | yfinance_matching_days | yfinance_date_match_rate | missing_open_count | isyatirim_tl_volume_zero_count | yfinance_share_volume_missing_count | yfinance_share_volume_zero_count | both_volumes_missing_count | open_present_both_volumes_missing_count | ohlc_inconsistency_count | hybrid_ohlc_validity_rate | nominal_open_inconsistency_count | nominal_open_validity_rate | source_price_conflict_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| start_boundary | 240 | 240 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 149 | 0.379167 | 35 | 0.854167 | 240 |
| price_step_change | 220 | 220 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 68 | 0.690909 | 3 | 0.986364 | 219 |
| recent_90_calendar_days | 580 | 580 | 1 | 0 | 0 | 0 | 48 | 0 | 0 | 37 | 0.936207 | 26 | 0.955172 | 396 |
| full_period | 7945 | 7942 | 0.999622 | 3 | 0 | 3 | 116 | 0 | 0 | 3542 | 0.554017 | 284 | 0.964241 | 7186 |

Oranların paydası İş Yatırım işlem günü sayısıdır. Hisse bazındaki ayrıntılar `source_acceptance_metrics.csv` dosyasındadır.

## Açılış ve hacim eksiklikleri

Açılış mevcutken iki hacmin de eksik olduğu benzersiz İş Yatırım takvim kaydı: **0**. Eksik, sıfır, tek kaynak eksik ve tek kaynak sıfır/diğeri pozitif sayıları hisse ve dönem bazında metrik CSV'sinde tutuldu.

## Hibrit OHLC ölçek kontrolü

Kontrol `İş Yatırım HG_MIN <= yFinance open <= İş Yatırım HG_MAX` biçimindedir. Beş hisselik tam dönemde sağlayıcı fiyatıyla değerlendirilebilen **7942** satırın **3542** tanesi tutarsızdı. Split faktörüyle nominal ölçeğe dönüşümden sonra değerlendirilebilen **7942** satırın **284** tanesi tutarsız kaldı.

### Beş hisse bazında dönüşüm öncesi/sonrası

| ticker | ticker_has_split | provider_evaluable_count | provider_inconsistency_count | provider_validity_rate | nominal_inconsistency_count | nominal_validity_rate | validity_rate_change |
| --- | --- | --- | --- | --- | --- | --- | --- |
| THYAO | False | 1588 | 25 | 0.984257 | 25 | 0.984257 | 0 |
| BIMAS | True | 1589 | 1543 | 0.028949 | 44 | 0.97231 | 0.943361 |
| TUPRS | True | 1588 | 779 | 0.509446 | 47 | 0.970403 | 0.460957 |
| SISE | False | 1588 | 71 | 0.95529 | 71 | 0.95529 | 0 |
| SASA | True | 1589 | 1124 | 0.292637 | 97 | 0.938955 | 0.646318 |

### Normal günler ve kurumsal işlem günleri

Gruplar örtüşebilir: bir split veya temettü günü aynı zamanda `adjustment_factor_change_day` olabilir. Kaynak ölçeği kabulü esas olarak `normal_day` üzerinden değerlendirilir.

| day_group | row_count | provider_inconsistency_count | provider_validity_rate | nominal_inconsistency_count | nominal_validity_rate | provider_to_nominal_improved_count | provider_to_nominal_worsened_count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all_days | 7945 | 3542 | 0.554017 | 284 | 0.964241 | 3258 | 0 |
| normal_day | 7907 | 3523 | 0.554276 | 284 | 0.964069 | 3239 | 0 |
| dividend_day | 32 | 16 | 0.5 | 0 | 1 | 16 | 0 |
| split_day | 6 | 3 | 0.5 | 0 | 1 | 3 | 0 |
| adjustment_factor_change_day | 37 | 18 | 0.513514 | 0 | 1 | 18 | 0 |

### En büyük kalan normal-gün uyuşmazlıkları

| ticker | date | yf_provider_open | yf_future_split_factor | yf_nominal_open | is_raw_low | is_raw_high | nominal_open_range_gap | nominal_open_range_gap_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| THYAO | 2026-05-21 00:00:00 | 295 | 1 | 295 | 274 | 274 | 21 | 7.66423 |
| BIMAS | 2026-05-21 00:00:00 | 392.75 | 1 | 392.75 | 376.5 | 376.5 | 16.25 | 4.31607 |
| TUPRS | 2026-05-21 00:00:00 | 249.1 | 1 | 249.1 | 241.7 | 241.7 | 7.40001 | 3.06165 |
| THYAO | 2026-04-22 00:00:00 | 329.5 | 1 | 329.5 | 323 | 324 | 5.5 | 1.70015 |
| THYAO | 2026-03-23 00:00:00 | 281.25 | 1 | 281.25 | 285.75 | 295.5 | 4.5 | 1.52284 |
| SISE | 2026-05-21 00:00:00 | 46.3 | 1 | 46.3 | 42.9 | 42.9 | 3.4 | 7.92541 |
| SISE | 2026-03-23 00:00:00 | 43.7 | 1 | 43.7 | 46.74 | 48.68 | 3.04 | 6.24486 |
| SASA | 2026-05-21 00:00:00 | 2.82 | 1 | 2.82 | 2.53 | 2.53 | 0.29 | 11.4624 |
| SASA | 2024-04-09 00:00:00 | 5.0475 | 8 | 40.38 | 40.42 | 41.88 | 0.0399989 | 0.0966158 |
| SASA | 2020-03-31 00:00:00 | 0.164055 | 50.2877 | 8.24995 | 8.25 | 8.77 | 4.69737e-05 | 0.000535618 |
| SASA | 2021-02-03 00:00:00 | 0.517024 | 50.2877 | 26 | 26 | 27.74 | 4.00417e-05 | 0.00014678 |
| SASA | 2020-12-18 00:00:00 | 0.376433 | 50.2877 | 18.93 | 18.93 | 19.57 | 3.99198e-05 | 0.000206838 |
| SASA | 2020-11-04 00:00:00 | 0.306237 | 50.2877 | 15.4 | 15.4 | 15.75 | 3.72283e-05 | 0.000238032 |
| SASA | 2020-03-23 00:00:00 | 0.096842 | 50.2877 | 4.86996 | 4.87 | 5.17 | 3.61781e-05 | 0.00072793 |
| SASA | 2021-11-29 00:00:00 | 1.06851 | 37.2668 | 39.82 | 39.82 | 43.36 | 3.57852e-05 | 8.32989e-05 |
| SASA | 2022-03-18 00:00:00 | 1.4262 | 37.2668 | 53.15 | 53.15 | 54.75 | 3.4843e-05 | 6.39908e-05 |
| SASA | 2020-12-22 00:00:00 | 0.376632 | 50.2877 | 18.94 | 18.94 | 19.46 | 3.316e-05 | 0.000172708 |
| SASA | 2020-07-13 00:00:00 | 0.223712 | 50.2877 | 11.25 | 11.25 | 12.02 | 3.25144e-05 | 0.000273921 |
| SASA | 2021-12-13 00:00:00 | 1.26601 | 37.2668 | 47.18 | 47.18 | 49.34 | 2.71997e-05 | 5.59895e-05 |
| SASA | 2020-11-18 00:00:00 | 0.335469 | 50.2877 | 16.87 | 16.87 | 17.21 | 2.66738e-05 | 0.000155714 |

Ayrıntılı hisse, dönem ve gün grubu karşılaştırmaları `source_scale_normalization.csv` dosyasındadır. Sabit bir fiyat veya oran kabul eşiği uygulanmadı.

## Kurumsal işlem tespiti sonuçları

- İndirilen 10 hisselik çalışma verisindeki benzersiz yFinance temettü/split/diğer action günü: **70**
- İndirilen 10 hisselik çalışma verisindeki İş Yatırım düzeltilmiş/ham kapanış faktörü değişim günü: **70**
- Tanımlı dört test kapsamına giren benzersiz olay satırı: **40** (`both=39`, `isyatirim_only=0`, `yfinance_only=1`)
- Faktör değişimi toleransı: `rtol=0.0001`, `atol=5e-05`. Bu yalnızca kayan nokta/yuvarlama gürültüsü toleransıdır; kabul koşusundaki kaynak yuvarlama gürültüsü gerçek olaylardan ayrı tutulacak şekilde seçildi.

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

Olay raporu her `ticker/date` için tek satır tutar ve satırın ait olduğu test dönemlerini ayrıca gösterir. İki kaynak aynı gün sinyal verirse `both`, yalnız biri verirse `isyatirim_only` veya `yfinance_only` olarak işaretlenir.

## Kaynak uyuşmazlıkları

İş Yatırım ham `high`, `low`, `close` ile hem orijinal yFinance sağlayıcı fiyatları hem de nominal ölçeğe dönüştürülmüş fiyatlar için mutlak ve yüzdesel farklar ayrı kaydedildi. `source_price_conflict` ve `nominal_source_price_conflict` yalnızca `atol=1e-08` sayısal eşitlik toleransını aşan farkları belirtir; BİST fiyat adımı veya kesin kabul toleransı uygulanmadı. Nominal açılışın İş Yatırım günlük aralığı dışında kalan mesafesi de ayrıca ölçüldü.

## D022 ve D023 kurallarının uygulanabilirliği

- **D022: DURUM KONTROLLERİ UYGULANABİLİR; FİYAT ÖLÇEĞİ KABULÜ KISMİ.** Gerekli açılış ve iki hacim alanı gözlendi. Split faktörü sistematik tarihsel ölçek farkını azalttı; ancak kalan normal-gün uyuşmazlıkları için kabul toleransı kesinleşmeden genel veri toplama veya label akışına geçilmedi. İki hacim de eksikken açılışın mevcut olduğu durumlar otomatik karara bağlanmadı.
- **D023: UYGULANABİLİR (tespit sinyallerinin bilinen sınırlamalarıyla).** yFinance action alanları ile İş Yatırım `adjusted_close/raw_close` faktör değişimleri ayrı ve ortak sinyal olarak üretilebiliyor. Bu sinyaller tahmin anı feature'ı değildir; yalnız label uygunluğu, giriş geçerliliği ve backtest kontrolü içindir.

## Bilinen sınırlamalar

- İş Yatırım ve yFinance ham fiyatları birebir aynı olmayabilir; kesin fiyat toleransı bu görevde kararlaştırılmadı.
- Nominal dönüşüm yalnız yFinance'ın raporladığı geçerli split oranlarını kullanır; eksik veya sonradan revize edilen action geçmişi eski nominal fiyatları değiştirebilir.
- Kalan küçük veya büyük normal-gün uyuşmazlıkları için kabul eşiği bu görevde belirlenmedi.
- Faktör değişimi, kurumsal işlemin türünü tek başına kanıtlamaz ve yuvarlama hassasiyetinden etkilenebilir.
- yFinance action geçmişinin sağlayıcı revizyonları, bugünkü sorguda geçmiş olay bilgisini gösterebilir; bu bilgi geçmiş tahmin anında biliniyormuş gibi feature'a taşınamaz.
- KAP veya başka bir yeni veri kaynağı kullanılmadı; tespit edilemeyen serbest marj durumları bilinen sınırlamadır.
- Çalıştırma gününün henüz kapanmamış veya işlem dışı olması halinde güncel dönemin son gözlemi son tamamlanmış işlem günüdür.

## Veri sızıntısı kontrolü

- `T+1–T+3` işlem yapılabilirlik ve kurumsal işlem sinyalleri model feature'ı üretilmeden yalnız kabul/label/backtest uygunluğu bağlamında analiz edildi.
- Tavan fiyatı hesaplanmadı; düzeltilmiş fiyatlar tavan hesabında kullanılmadı.
- Ham/düzeltilmiş faktör yalnız veri kalite ve kurumsal işlem sinyali olarak incelendi.
- Gelecekteki split bilgisi yalnız tarihsel fiyat birimini geri kurmak için kullanıldı; `yf_future_split_factor` model feature'ı değildir ve tahmin olasılığını etkilemeyecektir.
- Kurumsal işlem penceresi yalnız label ve backtest uygunluğu içindir; gelecekte oluşan action kayıtları tahmin anında mevcut bilgi olarak yorumlanmadı.
- Canlı tahminde geçmiş fiyatların sonradan değişmemesi için ham kaynak yanıtlarının veya normalize edilmiş değerlerin veri sürümüyle saklanması gerekir.
- Bu görev model, feature, label veya backtest kodu üretmedi.

## Başarısız veya eksik kalan kontroller

- Split ölçeği sistematik olarak düzeldi ancak normal günlerde 188 tutarsızlık kaldı; kabul toleransı henüz kesinleştirilmedi.

## Açık sorular

- Açılış mevcutken iki hacim alanının da eksik olduğu kayıtların nihai davranışı ayrı karara ihtiyaç duyar.
- Kaynak ham fiyat uyuşmazlıkları için fiyat seviyesi/tarih etkili tolerans henüz kesinleştirilmedi.
- Raporlanan dönüşüm sonrası normal-gün geçerlilik oranı hangi toleransla nihai kabul edilecek?
- `yf_future_split_factor` yaklaşımı veri sürümleme şartıyla kalıcı normalizasyon yöntemi olarak kabul edilecek mi?
- İş Yatırım faktör değişim sinyalinin olay tarihi ve türü için ek doğrulama yöntemi gerekebilir.

## Önerilen sıradaki görev

Kullanıcı ve ChatGPT'nin dönüşüm sonrası oranları ve kalan örnekleri değerlendirerek fiyat ölçeği normalizasyonu için nihai kabul ölçütünü kesinleştirmesi. Kaynak kabul sonucu `PASS` olmadan genel veri toplama veya label altyapısına geçilmemelidir.
