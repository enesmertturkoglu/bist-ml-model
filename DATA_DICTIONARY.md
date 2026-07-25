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
| `tl_volume` | `HGDG_HACIM` | `float64` | Hacim; fiyat düzeltmesi uygulanmıyor | Günlük TL işlem hacmi; kabul örneğinde `HG_HACIM` ile aynı değer | İlgili günün kapanışı sonrasında mevcut | D022 işlem gerçekleşme ve veri kalite kontrolü | yFinance hacmiyle birlikte değerlendirilir; iki kaynak da eksikse açık durum | Negatif olmama, sıfır/eksik ve kaynaklar arası hacim bayrakları |
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

## yFinance

Çağrı kodu `.IS` uzantılı sembollerle, `auto_adjust=False` ve `actions=True` parametreleriyle çalıştırıldı. Kaynak indeksinin gözlenen zaman dilimi `Europe/Istanbul`; `end` parametresi hariçtir. `auto_adjust=False` olmasına rağmen geçmiş OHLC ölçeğinin splitler için geriye taşındığı gerçek veri karşılaştırmasında gözlendi.

| Alan adı | Kaynak sütun adı | Veri tipi | Ham/düzeltilmiş | Anlamı | Tahmin anında kullanılabilirlik | Label/backtest kullanım amacı | Eksik değer davranışı | Veri kalite kontrolü |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `provider_open` | `Open` | `float64` | Yahoo sağlayıcı; geçmiş split ölçeğine taşınmış | yFinance'ın değiştirilmeden korunan günlük açılış fiyatı | T günü açılıştan sonra mevcut; `T+1` değeri T kapanışında mevcut değildir | Nominal dönüşüm girdisi ve dönüşüm öncesi D022 kalite karşılaştırması | Eksik veya pozitif değilse `NO_OPEN` ve label `NA` | Pozitiflik, yerel tarih eşleşmesi ve dönüşüm öncesi `low <= open <= high` kontrolü |
| `provider_high` | `High` | `float64` | Yahoo sağlayıcı; geçmiş split ölçeğine taşınmış | yFinance'ın değiştirilmeden korunan günlük en yüksek fiyatı | İlgili gün kapanışı sonrasında mevcut | Nominal dönüşüm girdisi ve İş Yatırım ham yüksek farkı | Eksik olarak korunur | yFinance OHLC sınırları ve İş Yatırım dönüşüm öncesi farkı |
| `provider_low` | `Low` | `float64` | Yahoo sağlayıcı; geçmiş split ölçeğine taşınmış | yFinance'ın değiştirilmeden korunan günlük en düşük fiyatı | İlgili gün kapanışı sonrasında mevcut | Nominal dönüşüm girdisi ve İş Yatırım ham düşük farkı | Eksik olarak korunur | yFinance OHLC sınırları ve İş Yatırım dönüşüm öncesi farkı |
| `provider_close` | `Close` | `float64` | Yahoo sağlayıcı; geçmiş split ölçeğine taşınmış | yFinance'ın değiştirilmeden korunan günlük kapanış fiyatı | İlgili gün kapanışı sonrasında mevcut | Nominal dönüşüm girdisi ve İş Yatırım ham kapanış farkı | Eksik olarak korunur | yFinance OHLC sınırları ve İş Yatırım dönüşüm öncesi farkı |
| `adjusted_close` | `Adj Close` | `float64` | Düzeltilmiş | Yahoo'nun temettü/split etkileriyle düzeltilmiş kapanışı | Bugünkü sorguda geçmişe uygulanır; point-in-time feature değildir | Kaynak kabul ve kalite karşılaştırması; ham tavan hesabında kullanılmaz | Eksik olarak korunur | `Close` oranı, pozitiflik ve action tarihleriyle tutarlılık |
| `share_volume` | `Volume` | `int64` | Adet hacmi | İşlem gören pay adedi | İlgili gün kapanışı sonrasında mevcut; `T+1` değeri T kapanışında mevcut değildir | D022 işlem gerçekleşme ve veri kalite kontrolü | İş Yatırım TL hacmiyle birlikte değerlendirilir | Negatif olmama, sıfır/eksik ve diğer hacim pozitif bayrağı |
| `dividends` | `Dividends` | `float64` | Action | Hisse başına temettü olayı/değeri | Tarihsel sorguda görülür; duyuru zamanındaki kullanılabilirlik doğrulanmadı | D023 `CORPORATE_ACTION_WINDOW`; feature değildir | Eksik action yok kabul edilmez; kaynak satırı yoksa bilinmiyor | Sıfır dışı olay tarihi, İş Yatırım faktör değişimiyle aynı gün karşılaştırması |
| `stock_splits` | `Stock Splits` | `float64` | Action | Bölünme oranı/olayı | Tarihsel sorguda görülür; duyuru zamanındaki kullanılabilirlik doğrulanmadı | D023 `CORPORATE_ACTION_WINDOW` ve fiyat ölçeği incelemesi; feature değildir | Eksik action yok kabul edilmez; kaynak satırı yoksa bilinmiyor | Sıfır dışı oran, pozitiflik ve İş Yatırım faktör değişimiyle aynı gün karşılaştırması |

## yFinance Nominal Ölçek Alanları

Bu alanlar kaynak sütunu değildir. Sağlayıcı değerlerini değiştirmeden, yFinance `Stock Splits` geçmişinden yalnız tarihsel fiyat birimini geri kurmak için üretilir. Formül:

```text
yf_future_split_factor[t] = t tarihinden sonra gerçekleşen geçerli split oranlarının çarpımı
yf_nominal_price[t] = yf_provider_price[t] × yf_future_split_factor[t]
```

Split gününün kendi oranı o günün faktörüne eklenmez. `0`, eksik, sonsuz, negatif veya sayıya çevrilemeyen oranlar nötr `1` olarak ele alınır. Ticker grupları birbirinden bağımsız hesaplanır.

| Alan adı | Kaynak sütun adı | Veri tipi | Ham/düzeltilmiş | Anlamı | Tahmin anında kullanılabilirlik | Label/backtest kullanım amacı | Eksik değer davranışı | Veri kalite kontrolü |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `yf_future_split_factor` | `Stock Splits` geçmişinden türetilir | `float64` | Tarihsel birim dönüşümü | İlgili tarihten kesinlikle sonra gerçekleşen geçerli split oranlarının kümülatif çarpımı | Gelecekteki olayları içerdiği için tahmin anında kullanılamaz ve feature değildir | Yalnız tarihsel sağlayıcı fiyatını döneminin nominal birimine geri taşımak | Split yoksa veya oran geçersizse `1` | Ticker izolasyonu, split günü hariç tutma, kümülatif çarpım ve geçersiz değer testleri |
| `yf_nominal_open` | `Open × yf_future_split_factor` | `float64` | Nominal ölçeğe geri dönüştürülmüş | Dönemin İş Yatırım ham fiyat birimiyle karşılaştırılmak üzere yeniden ölçeklenen açılış | `T+1` değeri T kapanışında mevcut değildir; faktör feature değildir | D022 giriş fiyatı için kaynak ölçeği adayı; nihai kabul kararı verilmedi | Sağlayıcı açılışı eksikse eksik kalır | `HG_MIN <= yf_nominal_open <= HG_MAX`, normal/action günü ayrımı ve kalan aralık farkı |
| `yf_nominal_high` | `High × yf_future_split_factor` | `float64` | Nominal ölçeğe geri dönüştürülmüş | Dönemin nominal birimine taşınan yFinance en yüksek fiyatı | İlgili gün sonrasında kalite testi için hesaplanır; feature değildir | İş Yatırım `HG_MAX` çapraz kontrolü | Sağlayıcı yüksek eksikse eksik kalır | İş Yatırım mutlak/yüzdesel farkı |
| `yf_nominal_low` | `Low × yf_future_split_factor` | `float64` | Nominal ölçeğe geri dönüştürülmüş | Dönemin nominal birimine taşınan yFinance en düşük fiyatı | İlgili gün sonrasında kalite testi için hesaplanır; feature değildir | İş Yatırım `HG_MIN` çapraz kontrolü | Sağlayıcı düşük eksikse eksik kalır | İş Yatırım mutlak/yüzdesel farkı |
| `yf_nominal_close` | `Close × yf_future_split_factor` | `float64` | Nominal ölçeğe geri dönüştürülmüş | Dönemin nominal birimine taşınan yFinance kapanışı | İlgili gün sonrasında kalite testi için hesaplanır; feature değildir | İş Yatırım `HG_KAPANIS` çapraz kontrolü | Sağlayıcı kapanışı eksikse eksik kalır | İş Yatırım mutlak/yüzdesel farkı |

## Kabul Testinde Üretilen Türetilmiş Alanlar

Aşağıdaki alanlar kaynak sütunu değil, kabul testi kalite çıktılarıdır:

```text
is_isyatirim_date
has_yfinance_row
has_open
has_isyatirim_tl_volume
has_yfinance_share_volume
both_volumes_zero
both_volumes_missing
one_volume_missing
one_volume_zero_other_positive
valid_ohlc
source_price_conflict
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
```

`adjustment_factor = HGDG_KAPANIS / HG_KAPANIS` olarak hesaplanır. Değişim kontrolünde yalnız kayan nokta ve kaynak yuvarlama gürültüsünü bastırmak için `rtol=0.0001`, `atol=0.00005` kullanılır. Kesin fiyat uyuşmazlığı eşiği veya BİST fiyat adımı toleransı bu görevde belirlenmemiştir.
