# DATA DICTIONARY

**Son doğrulama:** 2026-07-26

**Doğrulama kapsamı:** `scripts/source_acceptance_test.py` ile THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL ve HEKTS gerçek yanıtları

**Kaynaklar:** İş Yatırım web veri uç noktası (repo içi dayanıklı istemci; `isyatirimhisse 5.0.1` davranışı referans alınmıştır) ve yFinance (`yfinance 1.5.2`)

Bu sözlük yalnız kaynak kabul testinde gerçekten gözlenen sütunları ve kaynak ölçeği testinde bunlardan üretilen açık kalite alanlarını içerir. `T+1–T+3` işlem yapılabilirlik, kurumsal işlem ve gelecekteki split faktörü model feature'ı değildir. Tarihsel düzeltilmiş değerler ve yFinance action geçmişi bugünkü sorguda gelecekteki düzeltmeleri içerebildiği için point-in-time feature olarak kullanılamaz.

## Veri Snapshot Katmanları

Varsayılan dosya tabanlı yapı aşağıdaki katmanları kullanır:

```text
data/
├── raw/<source>/<dataset_type>/<instrument>/<logical_key>/.../data.jsonl
├── derived/<source>/<dataset_type>/<instrument>/<logical_key>/.../data.jsonl
└── manifests/
    ├── snapshots.jsonl
    └── provider_revisions.jsonl
```

- `raw`: Sağlayıcı alanları ve değerleri değiştirilmeden saklanır. yFinance tarih indeksi yalnız serializasyon için yerel `date` sütununa taşınır ve istek tickera `ticker` kimliği eklenir. İş Yatırım'ın kabul edilmiş yardımcı alanları aynı ham frame içinde korunur.
- `derived`: Ham veriyle karışmayan dönüşüm çıktılarıdır. İlk oluşturulan dataset `yfinance/nominal_ohlc` olup D024 nominal OHLC ve split-normalizasyon denetim alanlarını içerir; kaynak ham snapshot `input_snapshot_ids` ile bağlanır.
- `manifests`: Commit edilmiş snapshot kayıtları ile gerçek sağlayıcı revision farklarını tutar. Geçici `.snapshot-tmp-*` dosya veya dizinleri manifest kaydı olmadan geçerli snapshot sayılmaz.

Snapshot verileri ek bir Parquet bağımlılığı gerektirmeyen `canonical-jsonl-v1` biçiminde saklanır. Checksum öncesinde sütun ve satır sırası, tarih, sayısal değer ve null gösterimi deterministik hale getirilir. Varsayılan algoritma `sha256`dır. Fiziksel veri ve metadata önce aynı dosya sisteminde geçici dizine yazılır, ardından atomik olarak son değişmez dizinine taşınır; manifest atomik olarak son commit sınırıdır.

## Snapshot ve Manifest Metadata Alanları

| Alan | Veri tipi | Anlamı ve doğrulama kuralı |
| --- | --- | --- |
| `snapshot_id` | `string` | Mantıksal dataset anahtarı, revision numarası, içerik ve şema checksum'ından yeniden üretilebilen kararlı kimlik |
| `source` | `string` | `yfinance` veya `isyatirim`; kaynak revision zincirleri birbirinden bağımsızdır |
| `dataset_type` | `string` | Örneğin `equity_history` veya `nominal_ohlc` |
| `ticker_or_instrument` | `string` | İstek kapsamındaki ticker/endeks/enstrüman kimliği; ayrı mantıksal zincir oluşturur |
| `request_start_date` | ISO `date` | İstek döneminin kapsayıcı başlangıcı; dönem izolasyonunun parçasıdır |
| `request_end_date` | ISO `date` | İstek döneminin kapsayıcı bitişi; yFinance hariç bitiş çağrısında bir gün ileri taşınır |
| `fetch_timestamp_utc` | UTC ISO `datetime` | Snapshot denemesinin UTC üretim zamanı |
| `row_count` | `integer` | Canonical veri satırı sayısı; fiziksel JSONL satır sayısıyla doğrulanır |
| `column_names` | `array[string]` | Deterministik sıralı sütun listesi |
| `column_types` | `object` | Sütun başına canonical semantik tip (`date`, `datetime`, `number`, `integer`, `boolean`, `string`, `null`, vb.) |
| `content_checksum` | hex `string` | Canonical JSONL içeriğinin checksum'ı; idempotency ve provider revision tespiti için kullanılır |
| `schema_checksum` | hex `string` | Sıralı sütun adları ve canonical tiplerin checksum'ı |
| `file_path` | POSIX bağıl `string` | `data_root` altındaki fiziksel `data.jsonl`; kök dışına çıkmasına izin verilmez |
| `revision_number` | `integer` | Aynı mantıksal dataset içindeki artan sıra numarası |
| `previous_snapshot_id` | `string/null` | Önceki fiziksel olarak doğrulanmış `COMPLETE` snapshot kimliği |
| `request_parameters` | `object` | `auto_adjust`, `actions`, endpoint, kapsayıcı bitiş ve dönüşüm sürümü gibi sonucu etkileyen istek parametreleri |
| `config_checksum` | hex `string` | Etkin merkezi `MarketDataConfig` değerlerinin checksum'ı |
| `code_commit_sha` | `string` | Snapshot'ı üreten repo commit SHA'sı; alınamazsa açıkça `unknown` |
| `provider_library_version` | `string` | `yfinance` veya `isyatirimhisse` paket sürümü |
| `snapshot_status` | enum `string` | `COMPLETE`, `FAILED`, `PARTIAL` veya `CORRUPT`; yalnız fiziksel doğrulamadan geçen `COMPLETE` kayıt kullanılabilir |
| `logical_dataset_key` | hex `string` | Katman, kaynak, dataset türü, instrument, dönem ve istek parametrelerinin deterministik anahtarı |
| `layer` | enum `string` | `raw` veya `derived`; iki katman aynı dizinde saklanmaz |
| `checksum_algorithm` | `string` | İçerik, şema, config ve kimlik doğrulamasında kullanılan algoritma; varsayılan `sha256` |
| `storage_format` | `string` | İlk sürümde `canonical-jsonl-v1` |
| `snapshot_schema_version` | `string` | Snapshot metadata şema sürümü; ilk sürümde `v1` |
| `input_snapshot_ids` | `array[string]` | Türetilmiş snapshot'ın kaynak aldığı değişmez snapshot kimlikleri |
| `identity_columns` | `array[string]` | Revision satır karşılaştırmasında kullanılan ticker/tarih anahtarları |
| `error_message` | `string/null` | `FAILED` veya `PARTIAL` sağlayıcı denemesinin açık hata bilgisi |
| `revision` | `object/null` | Önceki `COMPLETE` snapshot'a göre provider revision fark özeti |

`FAILED`, `PARTIAL` ve `CORRUPT` kayıtlar manifestte denetim amacıyla bulunabilir; eğitim, feature, label, backtest veya günlük tahmin için kullanılabilir kabul edilmez. Bir `COMPLETE` kaydın da kullanılmadan önce metadata dosyası, fiziksel dosya, satır sayısı, içerik checksum'ı, şema checksum'ı ve yeniden üretilen `snapshot_id` ile doğrulanması gerekir.

## Provider Revision Alanları

| Alan | Veri tipi | Anlamı |
| --- | --- | --- |
| `revision_id` | `string` | Revision fark özetinin deterministik kimliği |
| `logical_dataset_key` | `string` | Değişikliğin ait olduğu izole kaynak/ticker/dönem/istek zinciri |
| `previous_snapshot_id` | `string` | Karşılaştırılan önceki geçerli snapshot |
| `snapshot_id` | `string` | Değişen içerikle oluşturulan yeni snapshot |
| `detected_at_utc` | UTC ISO `datetime` | Sağlayıcı değişikliğinin tespit zamanı |
| `changed_row_count` | `integer` | Aynı kimlik anahtarında en az bir hücresi değişen satır sayısı |
| `added_dates` | `array[date]` | Yeni içerikte eklenen benzersiz tarihler |
| `removed_dates` | `array[date]` | Yeni içerikten kaldırılan benzersiz tarihler |
| `changed_columns` | `array[string]` | Değişen hücre veya şema nedeniyle etkilenen sütunlar |
| `changed_cell_count` | `integer` | Aynı kimlikli satırlarda değeri değişen hücre sayısı |

İçerik ve şema checksum'ları aynıysa yeni revision veya yeni dosya oluşturulmaz; mevcut snapshot kimliği idempotent olarak döner. İçerik ya da şema değişirse eski revision korunur, yeni fiziksel dizin oluşturulur ve zincir `previous_snapshot_id` ile bağlanır.

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
| `raw_close` | `HG_KAPANIS` | `float64` | Ham | İş Yatırım'ın tarihindeki nominal kapanış fiyatı | T kapanışı sonrasında mevcut; model feature'ı değildir | Giriş, label, T+3 çıkışı veya tavan baz fiyatı değildir; yalnız `cross_source_price_warning`, `adjusted_close/raw_close` kurumsal işlem sinyali ve denetim | Eksikse İş Yatırım çapraz kontrolü ve faktör sinyali üretilemez; yFinance ana fiyat satırını tek başına dışlamaz | Pozitiflik, ham OHLC sınırları, düzeltme faktörü ve yFinance nominal fark dağılımı |
| `raw_weighted_average` | `HG_AOF` | `float64` | Ham | Tarihindeki nominal ağırlıklı ortalama fiyat | T kapanışı sonrasında mevcut | Veri kalite/likidite analizi; ilk label formülünde kullanılmıyor | Eksik olarak korunur | Pozitiflik ve ham günlük aralık içinde olma |
| `raw_low` | `HG_MIN` | `float64` | Ham | İş Yatırım'ın tarihindeki nominal günlük en düşük fiyatı | T kapanışı sonrasında mevcut; model feature'ı değildir | Giriş, label, çıkış veya tavan hesabında kullanılmaz; yalnız `cross_source_price_warning` ve denetim | Eksikse çapraz fiyat kontrolü yapılamaz; yFinance ana fiyat satırını tek başına dışlamaz | İş Yatırım ham aralığı ve yFinance nominal low farkı |
| `raw_high` | `HG_MAX` | `float64` | Ham | İş Yatırım'ın tarihindeki nominal günlük en yüksek fiyatı | T kapanışı sonrasında mevcut; model feature'ı değildir | `%5` hedefi, giriş, çıkış veya tavan hesabında kullanılmaz; yalnız `cross_source_price_warning` ve denetim | Eksikse çapraz fiyat kontrolü yapılamaz; yFinance ana fiyat satırını tek başına dışlamaz | İş Yatırım ham aralığı ve yFinance nominal high farkı |
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
