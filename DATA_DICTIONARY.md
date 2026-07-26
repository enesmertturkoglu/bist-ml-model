# DATA DICTIONARY

**Son doğrulama:** 2026-07-26

**Doğrulama kapsamı:** `scripts/source_acceptance_test.py` ile THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL ve HEKTS gerçek yanıtları

**Kaynaklar:** İş Yatırım (`isyatirimhisse 5.0.1`) ve yFinance (`yfinance 1.5.2`)

Bu sözlük yalnız kaynak kabul testinde gerçekten gözlenen sütunları ve kaynak ölçeği testinde bunlardan üretilen açık kalite alanlarını içerir. `T+1–T+3` işlem yapılabilirlik, kurumsal işlem ve gelecekteki split faktörü model feature'ı değildir. Tarihsel düzeltilmiş değerler ve yFinance action geçmişi bugünkü sorguda gelecekteki düzeltmeleri içerebildiği için point-in-time feature olarak kullanılamaz.

## İş Yatırım / `isyatirimhisse`

| Alan adı | Kaynak sütun adı | Veri tipi | Ham/düzeltilmiş | Anlamı | Tahmin anında kullanılabilirlik | Label/backtest kullanım amacı | Eksik değer davranışı | Veri kalite kontrolü |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `symbol` | `HGDG_HS_KODU` | `object` | Kimlik | BİST işlem kodu | T ve öncesinde mevcut | Hisse/tarih anahtarı | Eksikse kayıt kullanılamaz | İstenen sembol ve yFinance `.IS` koduyla eşleştir |
| `date` | `HGDG_TARIH` | `datetime64[ns]` | Kimlik | İş Yatırım işlem tarihi | T kapanışı sonrasında mevcut | Ana BİST işlem takvimi ve birleştirme anahtarı | Eksikse kayıt kullanılamaz | Tekil `symbol/date`, sıralama ve yFinance yerel tarihiyle eşleşme |
| `adjusted_close` | `HGDG_KAPANIS` | `float64` | Düzeltilmiş | Bugünkü sorguya göre geçmişe dönük düzeltilmiş kapanış | T tarihinde sorgulanabilir; gelecekteki işlemlerle tarihsel değer değişebilir | D023 düzeltme katsayısı ve kalite kontrolü | Faktör üretilemez; olay sinyali belirsiz kalır | Pozitiflik ve `adjusted_close/raw_close` sürekliliği |
| `adjusted_weighted_average` | `HGDG_AOF` | `float64` | Düzeltilmiş | Düzeltilmiş ağırlıklı ortalama fiyat | T tarihinde sorgulanabilir; point-in-time güvenli feature olduğu doğrulanmadı | Kaynak doğrulama; ilk sürüm labelında kullanılmıyor | Eksik olarak korunur | Pozitiflik ve ham karşılığıyla katsayı tutarlılığı |
| `adjusted_low` | `HGDG_MIN` | `float64` | Düzeltilmiş | Düzeltilmiş günlük en düşük fiyat | T tarihinde sorgulanabilir; gelecekteki düzeltmelerden etkilenebilir | Kaynak doğrulama; tavan ve ham label hesabında kullanılmaz | Eksik olarak korunur | Pozitiflik, düzeltilmiş OHLC sınırları ve katsayı tutarlılığı |
| `adjusted_high` | `HGDG_MAX` | `float64` | Düzeltilmiş | Düzeltilmiş günlük en yüksek fiyat | T tarihinde sorgulanabilir; gelecekteki düzeltmelerden etkilenebilir | Kaynak doğrulama; tavan ve ham label hesabında kullanılmaz | Eksik olarak korunur | Pozitiflik, düzeltilmiş OHLC sınırları ve katsayı tutarlılığı |
| `is_tl_volume` | `HGDG_HACIM` | `float64` | Hacim; fiyat düzeltmesi uygulanmıyor | Günlük TL işlem hacmi; kabul örneğinde `HG_HACIM` ile aynı değer | İlgili günün kapanışı sonrasında mevcut | D022 işlem gerçekleşme ve veri kalite kontrolü | yFinance hacmiyle birlikte değerlendirilir; iki kaynak da eksikse açık durum | Negatif olmama, sıfır/eksik ve kaynaklar arası hacim bayrakları |
| `index_code` | `END_ENDEKS_KODU` | `object` | Referans | Yanıtta eşlik eden endeks kodu | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Kod sürekliliği ve tarih eşleşmesi |
| `index_timestamp` | `END_TARIH` | `int64` | Referans | Endeks kaydının milisaniye epoch zaman damgası | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksikse endeks referansı kurulmaz | `date` ile yerel takvim uyumu |
| `index_session` | `END_SEANS` | `int64` | Referans | Endeks seans kodu | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Beklenen kod kümesi ve tarih tutarlılığı |
| `index_value` | `END_DEGER` | `float64` | Referans | Eşlik eden endeks değeri | İlgili gün sonrasında mevcut; feature kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Pozitiflik ve endeks tarihiyle uyum |
| `fx_currency_code` | `DD_DOVIZ_KODU` | `object` | Referans | Döviz kodu; gözlenen yanıtta `USD` | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Beklenen para birimi kodu |
| `fx_rate_type_code` | `DD_DT_KODU` | `object` | Referans | Döviz kuru tür kodu | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Kod sürekliliği |
| `fx_timestamp` | `DD_TARIH` | `int64` | Referans | Döviz kaydının milisaniye epoch zaman damgası | İlgili gün sonrasında mevcut; kullanım kararı verilmedi | Kabul testinde kullanılmıyor | Eksikse döviz referansı kurulmaz | `date` ile yerel takvim uyumu |
| `fx_rate` | `DD_DEGER` | `float64` | Referans | TL karşılığı döviz kuru | İlgili gün sonrasında mevcut; feature kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Pozitiflik ve döviz koduyla uyum |
| `usd_based_price` | `DOLAR_BAZLI_FIYAT` | `float64` | Türetilmiş | Kaynak tarafından dolar bazına çevrilmiş fiyat | İlgili gün sonrasında mevcut; formül ve feature kararı doğrulanmadı | Kabul testinde kullanılmıyor | Eksik olarak korunur | `fx_rate` ve fiyat yönüyle tutarlılık |
| `index_based_price` | `ENDEKS_BAZLI_FIYAT` | `float64` | Türetilmiş | Kaynak tarafından endeks bazına çevrilmiş fiyat | İlgili gün sonrasında mevcut; formül ve feature kararı doğrulanmadı | Kabul testinde kullanılmıyor | Eksik olarak korunur | Endeks değeri ve fiyat yönüyle tutarlılık |
| `usd_volume` | `DOLAR_HACIM` | `float64` | Türetilmiş | TL hacmin dolar karşılığı | İlgili günün kapanışı sonrasında mevcut | Kabul testinde kullanılmıyor | Eksik olarak korunur | Negatif olmama ve `tl_volume/fx_rate` ölçeği |
| `paid_in_capital` | `SERMAYE` | `float64` | Ham referans | Kaynağın raporladığı sermaye | T tarihinde sorgulanabilir; tarihsel point-in-time niteliği doğrulanmadı | Kabul testinde kullanılmıyor | Eksik olarak korunur | Pozitiflik ve ani değişim kontrolü |
| `raw_close` | `HG_KAPANIS` | `float64` | Ham | Tarihindeki nominal kapanış fiyatı | T kapanışı sonrasında mevcut | D021 önceki kapanış, label ve backtest ham fiyatı | Eksik/geçersizse `NO_PREVIOUS_CLOSE` veya `INVALID_OHLC` adayı | Pozitiflik, ham OHLC sınırları ve yFinance fark dağılımı |
| `raw_weighted_average` | `HG_AOF` | `float64` | Ham | Tarihindeki nominal ağırlıklı ortalama fiyat | T kapanışı sonrasında mevcut | Veri kalite/likidite analizi; ilk label formülünde kullanılmıyor | Eksik olarak korunur | Pozitiflik ve ham günlük aralık içinde olma |
| `raw_low` | `HG_MIN` | `float64` | Ham | Tarihindeki nominal günlük en düşük fiyat | T kapanışı sonrasında mevcut; T+1–T+3 değerleri T anında mevcut değildir | Label/backtest OHLC kontrolü | Eksik/geçersizse `INVALID_OHLC` adayı | `low <= close <= high`; yFinance ham fark dağılımı |
| `raw_high` | `HG_MAX` | `float64` | Ham | Tarihindeki nominal günlük en yüksek fiyat | T kapanışı sonrasında mevcut; T+1–T+3 değerleri yalnız label/backtestte | `%5` hedef kontrolü ve özel marj şüphesi | Eksik/geçersizse `INVALID_OHLC` adayı | `low <= close <= high`; üst limit ve yFinance fark dağılımı |
| `market_cap_try` | `PD` | `float64` | Türetilmiş | TL piyasa değeri | İlgili gün sonrasında sorgulanabilir; feature kararı verilmedi | Kabul testinde yalnız sütun varlığı doğrulandı | Eksik olarak korunur | Negatif olmama ve sermaye/fiyat ölçeği |
| `market_cap_usd` | `PD_USD` | `float64` | Türetilmiş | USD piyasa değeri | İlgili gün sonrasında sorgulanabilir; feature kararı verilmedi | Kabul testinde yalnız sütun varlığı doğrulandı | Eksik olarak korunur | Negatif olmama ve `PD/fx_rate` ölçeği |
| `free_float_market_cap_try` | `HAO_PD` | `float64` | Türetilmiş | Halka açık kısmın TL piyasa değeri | İlgili gün sonrasında sorgulanabilir; feature kararı verilmedi | Kabul testinde yalnız sütun varlığı doğrulandı | Eksik olarak korunur | Negatif olmama ve `HAO_PD <= PD` kontrolü |
| `free_float_market_cap_usd` | `HAO_PD_USD` | `float64` | Türetilmiş | Halka açık kısmın USD piyasa değeri | İlgili gün sonrasında sorgulanabilir; feature kararı verilmedi | Kabul testinde yalnız sütun varlığı doğrulandı | Eksik olarak korunur | Negatif olmama ve TRY/USD ölçek tutarlılığı |
| `raw_tl_volume` | `HG_HACIM` | `float64` | Ham hacim | Günlük TL işlem hacmi | İlgili günün kapanışı sonrasında mevcut | D022 işlem gerçekleşme ve veri kalite kontrolü | yFinance hacmiyle birlikte değerlendirilir | `HGDG_HACIM` eşitliği, negatif olmama, sıfır/eksik bayrakları |
| `usd_based_low` | `DOLAR_BAZLI_MIN` | `float64` | Türetilmiş | Kaynak tarafından dolar bazına çevrilmiş en düşük fiyat | İlgili gün sonrasında mevcut; feature kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Ham düşük ve kurla ölçek tutarlılığı |
| `usd_based_high` | `DOLAR_BAZLI_MAX` | `float64` | Türetilmiş | Kaynak tarafından dolar bazına çevrilmiş en yüksek fiyat | İlgili gün sonrasında mevcut; feature kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Ham yüksek ve kurla ölçek tutarlılığı |
| `usd_based_weighted_average` | `DOLAR_BAZLI_AOF` | `float64` | Türetilmiş | Kaynak tarafından dolar bazına çevrilmiş ağırlıklı ortalama fiyat | İlgili gün sonrasında mevcut; feature kararı verilmedi | Kabul testinde kullanılmıyor | Eksik olarak korunur | Ham AOF ve kurla ölçek tutarlılığı |

## D024 Tek Fiyat Kaynağı Alanları

yFinance çağrıları `.IS` uzantılı semboller, `auto_adjust=False` ve `actions=True` ile yapılır. `end` parametresi hariçtir; gözlenen indeks zaman dilimi `Europe/Istanbul` olarak korunur. Sağlayıcının geçmiş OHLC değerlerini splitler için güncel ölçeğe taşıyabildiği gerçek veride gözlendiğinden provider ve nominal alanlar ayrı saklanır.

| Alan adı | Kaynak | Ham/türetilmiş | Formül veya kaynak eşleme | Veri tipi | Kullanım amacı | Tahmin anında kullanılabilirlik | Label/backtest kullanımı | Eksik değer davranışı | Veri kalite kontrolü |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `yf_provider_open` | yFinance `Open` | Ham sağlayıcı | Değiştirilmeden kopyalanır | `float64` | Nominal open girdisi ve ham veri denetimi | Günün açılışından sonra; `T+1` değeri T kapanışında bilinmez | Doğrudan kullanılmaz | Eksik/pozitif değilse nominal open eksik ve `NO_OPEN` | Kaynak tarihi, pozitiflik, provider OHLC sınırı |
| `yf_provider_high` | yFinance `High` | Ham sağlayıcı | Değiştirilmeden kopyalanır | `float64` | Nominal high girdisi | Gün kapanışından sonra | Doğrudan kullanılmaz | Eksikse nominal high eksik kalır | Provider OHLC sınırı ve kaynak tarihi |
| `yf_provider_low` | yFinance `Low` | Ham sağlayıcı | Değiştirilmeden kopyalanır | `float64` | Nominal low girdisi | Gün kapanışından sonra | Doğrudan kullanılmaz | Eksikse nominal low eksik kalır | Provider OHLC sınırı ve kaynak tarihi |
| `yf_provider_close` | yFinance `Close` | Ham sağlayıcı | Değiştirilmeden kopyalanır | `float64` | Nominal close girdisi | Gün kapanışından sonra | Doğrudan kullanılmaz | Eksikse nominal close eksik kalır | Provider OHLC sınırı ve kaynak tarihi |
| `yf_provider_adjusted_close` | yFinance `Adj Close` | Sağlayıcı düzeltilmiş | Değiştirilmeden kopyalanır | `float64` | Sağlayıcı denetimi; ana fiyat değildir | Tarihsel sorguda görülür, point-in-time güvenli feature değildir | Kullanılmaz | Eksik olarak korunur | `Close` oranı ve action tarihleriyle tutarlılık |
| `yf_share_volume` | yFinance `Volume` | Ham adet hacmi | Değiştirilmeden kopyalanır | `float64`/`int64` | D022 işlem ve hacim kalite kontrolü | Gün kapanışından sonra | Giriş yapılabilirlik kontrolü; feature kararı değildir | `is_tl_volume` ile birlikte değerlendirilir | Negatiflik, sıfır/eksik, kaynaklar arası hacim bayrağı |
| `yf_dividends` | yFinance `Dividends` | Ham action | Değiştirilmeden kopyalanır | `float64` | D023 kurumsal işlem sinyali | Tarihsel sorguda görülür; feature değildir | `T+1–T+3` penceresinde `CORPORATE_ACTION_WINDOW` ile `NA` | Kaynak satırı yoksa olay durumu bilinmiyor | Sıfır dışı olay ve İş Yatırım faktör değişimi karşılaştırması |
| `yf_stock_splits` | yFinance `Stock Splits` | Ham action | Değiştirilmeden kopyalanır | `float64` | Split normalizasyonu ve D023 sinyali | Gelecek olay bilgisi tahmin sinyali değildir | Fiyat birimi dönüşümü; olay penceresi `NA` | Eksik/0 olay yok, geçersiz pozitif olmayan oran nötrlenir | Oran pozitifliği, ticker/tarih ve faktör testi |
| `yf_future_split_factor` | `yf_stock_splits` | Türetilmiş normalizasyon | `t` tarihinden kesinlikle sonraki geçerli split oranlarının kümülatif çarpımı | `float64` | Tarihsel fiyat birimini döneminin nominal ölçeğine geri kurmak | Gelecek olay içerdiği için feature değildir ve LightGBM'e verilmez | Yalnız OHLC normalizasyonu | Geçerli gelecek split yoksa `1`; üretilemezse açık kalite hatası | Split günü hariç, ticker izolasyonu, sonlu/pozitif değer, aynı OHLC faktörü |
| `yf_nominal_open` | yFinance + split faktörü | Türetilmiş fiyat | `yf_provider_open × yf_future_split_factor` | `float64` | Tek giriş ve tavan-açılış fiyatı | `T+1` değeri T kapanışında bilinmez; faktör sinyal değildir | `T+1` giriş fiyatı ve tavan açılış kontrolü | Eksik/geçersizse `NO_OPEN`, label/backtest `NA` | `low <= open <= high`, dönüşüm eşitliği, çapraz kalite uyarısı |
| `yf_nominal_high` | yFinance + split faktörü | Türetilmiş fiyat | `yf_provider_high × yf_future_split_factor` | `float64` | Tek günlük high fiyatı | İlgili gün kapanışından sonra | `T+1–T+3` maksimum high ile `%5` hedef kontrolü | Eksik/geçersizse `INVALID_OHLC`, `NA` | `low <= high`, dönüşüm eşitliği, çapraz kalite uyarısı |
| `yf_nominal_low` | yFinance + split faktörü | Türetilmiş fiyat | `yf_provider_low × yf_future_split_factor` | `float64` | Tek günlük low fiyatı | İlgili gün kapanışından sonra | OHLC geçerlilik kontrolü | Eksik/geçersizse `INVALID_OHLC`, `NA` | `low <= open/close <= high`, dönüşüm eşitliği |
| `yf_nominal_close` | yFinance + split faktörü | Türetilmiş fiyat | `yf_provider_close × yf_future_split_factor` | `float64` | Tek kapanış ve tavan baz fiyatı | Gün kapanışından sonra | `T+3` çıkışı ve önceki geçerli kapanıştan tavan hesabı | Eksik/geçersizse `INVALID_OHLC` veya `NO_PREVIOUS_CLOSE`, `NA` | `low <= close <= high`, dönüşüm eşitliği, çapraz kalite uyarısı |
| `is_tl_volume` | İş Yatırım `HGDG_HACIM` | Ham/sağlayıcı hacmi | Kaynak değeri | `float64` | D022 TL işlem hacmi ve kalite kontrolü | Gün kapanışından sonra | `yf_share_volume` ile işlem gerçekleşme kontrolü | İki hacim eksikse açık soru; ikisi sıfırsa `NO_TRADE` | Negatiflik, sıfır/eksik ve `SOURCE_VOLUME_CONFLICT` |
| `cross_source_price_warning` | yFinance nominal + İş Yatırım `HG_*` | Türetilmiş kalite bayrağı | Karşılaştırılabilir nominal/İş Yatırım high-low-close alanlarından en az biri yalnız sayısal toleransı aşarsa `true` | `boolean` | Fiyat kaynakları çapraz veri kalite raporu | İlgili gün sonrasında; model feature'ı değildir | Satırı otomatik dışlamaz, kabul sonucunu etkilemez | Karşılaştırma yapılamıyorsa `NA` | Fark alanları ve sayısal tolerans raporlanır; sabit yüzde kabul eşiği yoktur |

## Kabul Testinde Üretilen Türetilmiş Alanlar

Aşağıdaki alanlar kaynak sütunu değil, kabul testi kalite çıktılarıdır:

```text
is_isyatirim_date
has_yfinance_row
has_open
missing_nominal_open
missing_nominal_high
missing_nominal_low
missing_nominal_close
missing_nominal_high_low_close
has_isyatirim_tl_volume
has_yfinance_share_volume
both_volumes_zero
both_volumes_missing
one_volume_missing
one_volume_zero_other_positive
valid_nominal_ohlc
split_factor_unavailable
nominal_conversion_consistent
cross_source_price_warning
adjustment_factor
adjustment_factor_changed
yf_future_split_factor
yf_nominal_open
yf_nominal_high
yf_nominal_low
yf_nominal_close
provider_open_within_is_range
nominal_open_within_is_range
provider_open_range_gap
nominal_open_range_gap
has_yfinance_dividend
has_yfinance_split
has_yfinance_other_action
has_any_corporate_action_signal
corporate_action_window
entry_eligible
entry_exclusion_reason
volume_quality_flag
label_eligible
label_exclusion_reason
```

`adjustment_factor = HGDG_KAPANIS / HG_KAPANIS` olarak hesaplanır. Değişim kontrolünde yalnız kayan nokta ve kaynak yuvarlama gürültüsünü bastırmak için `rtol=0.0001`, `atol=0.00005` kullanılır. Kesin fiyat uyuşmazlığı eşiği veya BİST fiyat adımı toleransı bu görevde belirlenmemiştir.
