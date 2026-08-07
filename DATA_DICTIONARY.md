# DATA DICTIONARY

**Belge son güncellemesi:** 2026-07-31

**Kaynak sütunu kabul doğrulaması:** 2026-07-27

**Aktif evren ve training provenance doğrulaması:** 2026-07-29

**Kaynak sütunu doğrulama kapsamı:** `scripts/source_acceptance_test.py` ile THYAO, GARAN, ASELS, BIMAS, TUPRS, EREGL, SISE, SASA, KCHOL ve HEKTS gerçek İş Yatırım/yFinance yanıtları

**Kaynaklar:** İş Yatırım web veri uç noktası (repo içi dayanıklı istemci; `isyatirimhisse 5.0.1` davranışı referans alınmıştır) ve yFinance (`yfinance 1.5.2`)

10 hisselik kabul paneli yalnız İş Yatırım/yFinance kaynak sütunlarının gerçek yanıtlardaki kabulünü doğrular. D034 aktif evren, D030 prediction universe ve D031–D033 model artifact/training provenance alanları bu 10 hisselik kaynak paneliyle doğrulanmış sayılmaz; bunların kapsamı ayrı snapshot, entegrasyon ve regresyon doğrulamalarıyla belgelenir.

Bu sözlük kaynak kabul testinde gerçekten gözlenen sütunları, bunlardan üretilen açık kalite alanlarını ve ayrıca doğrulanmış derived XU100, global BİST takvimi, `baseline_v1`, aktif evren, prediction universe ve model artifact sözleşme alanlarını içerir. `T+1–T+3` işlem yapılabilirlik, kurumsal işlem ve gelecekteki split faktörü model feature'ı değildir. Tarihsel düzeltilmiş değerler ve yFinance action geçmişi bugünkü sorguda gelecekteki düzeltmeleri içerebildiği için point-in-time feature olarak kullanılamaz.

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
- `derived`: Ham veriyle karışmayan dönüşüm çıktılarıdır. `yfinance/nominal_ohlc` D024 nominal OHLC ve split-normalizasyon denetim alanlarını; `security_identity/nominal_ohlc` D027 security birleştirmesini; `cleaning/market_data_eligibility` D022/D023 temizleme, kalite ve işlem uygunluğu alanlarını; `isyatirim/global_bist_sessions` gözlenen global takvimi; `benchmark/validated_xu100_close` doğrulanmış benchmark'ı; `features/baseline_v1` sıralı 32 feature'ı; `universe/active_bist_equities` ise exact as-of aktif şirket payı master evrenini içerir. Her türetilmiş snapshot kaynak ham/türetilmiş snapshot'larına `input_snapshot_ids` ile bağlanır.
- `manifests`: Commit edilmiş snapshot kayıtları ile gerçek sağlayıcı revision farklarını tutar. Geçici `.snapshot-tmp-*` dosya veya dizinleri manifest kaydı olmadan geçerli snapshot sayılmaz.

Snapshot verileri ek bir Parquet bağımlılığı gerektirmeyen `canonical-jsonl-v1` biçiminde saklanır. Checksum öncesinde sütun ve satır sırası, tarih, sayısal değer ve null gösterimi deterministik hale getirilir. Varsayılan algoritma `sha256`dır. Fiziksel veri ve metadata önce aynı dosya sisteminde geçici dizine yazılır, ardından atomik olarak son değişmez dizinine taşınır; manifest atomik olarak son commit sınırıdır.

## Snapshot ve Manifest Metadata Alanları

| Alan | Veri tipi | Anlamı ve doğrulama kuralı |
| --- | --- | --- |
| `snapshot_id` | `string` | Mantıksal dataset anahtarı, revision numarası, içerik/şema ve varsa revision context checksum'ından yeniden üretilebilen kararlı kimlik |
| `source` | `string` | Örneğin `yfinance`, `isyatirim`, `benchmark`, `features`, `security_identity`, `cleaning` veya `labels`; kaynak revision zincirleri birbirinden bağımsızdır |
| `dataset_type` | `string` | Örneğin `equity_history`, `nominal_ohlc` veya `market_data_eligibility` |
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
| `revision_context` | `object` | Logical dataset anahtarını değiştirmeden revision'a bağlanan input checksum, takvim, mapping, katalog, config ve kod provenance değerleri |
| `revision_context_checksum` | hex `string/null` | Context boş değilse canonical `revision_context` SHA özeti; bağlam değişikliği içerik aynı olsa bile yeni revision üretir |
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

`END_ENDEKS_KODU`, `END_TARIH`, `END_SEANS` ve `END_DEGER` yalnız XU100 kalite ve çapraz kontrolünde kullanılır; feature ana kaynağı değildir ve doğrulanmış XU100 snapshot'ına fallback olamaz. Kabul panelinde literal endeks kodu `XU100` yerine `1` gözlenmiştir. Tarih, seans ve değer aynı gün farklı hisseler arasındaki tutarlılığı doğrulamak için kullanılır. Market ve relative feature'ların tek benchmark kaynağı `validated_xu100_close` alanıdır.

| Alan adı | Kaynak sütun adı | Veri tipi | Ham/düzeltilmiş | Anlamı | Tahmin anında kullanılabilirlik | Label/backtest kullanım amacı | Eksik değer davranışı | Veri kalite kontrolü |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `symbol` | `HGDG_HS_KODU` | `object` | Kimlik | BİST işlem kodu | T ve öncesinde mevcut | Hisse/tarih anahtarı | Eksikse kayıt kullanılamaz | İstenen sembol ve yFinance `.IS` koduyla eşleştir |
| `date` | `HGDG_TARIH` | `datetime64[ns]` | Kimlik | İş Yatırım işlem tarihi | T kapanışı sonrasında mevcut | Ana BİST işlem takvimi ve birleştirme anahtarı | Eksikse kayıt kullanılamaz | Tekil `symbol/date`, sıralama ve yFinance yerel tarihiyle eşleşme |
| `adjusted_close` | `HGDG_KAPANIS` | `float64` | Düzeltilmiş | Bugünkü sorguya göre geçmişe dönük düzeltilmiş kapanış | T tarihinde sorgulanabilir; gelecekteki işlemlerle tarihsel değer değişebilir | D023 düzeltme katsayısı ve kalite kontrolü | Faktör üretilemez; olay sinyali belirsiz kalır | Pozitiflik ve `adjusted_close/raw_close` sürekliliği |
| `adjusted_weighted_average` | `HGDG_AOF` | `float64` | Düzeltilmiş | Düzeltilmiş ağırlıklı ortalama fiyat | T tarihinde sorgulanabilir; point-in-time güvenli feature olduğu doğrulanmadı | Kaynak doğrulama; ilk sürüm labelında kullanılmıyor | Eksik olarak korunur | Pozitiflik ve ham karşılığıyla katsayı tutarlılığı |
| `adjusted_low` | `HGDG_MIN` | `float64` | Düzeltilmiş | Düzeltilmiş günlük en düşük fiyat | T tarihinde sorgulanabilir; gelecekteki düzeltmelerden etkilenebilir | Kaynak doğrulama; tavan ve ham label hesabında kullanılmaz | Eksik olarak korunur | Pozitiflik, düzeltilmiş OHLC sınırları ve katsayı tutarlılığı |
| `adjusted_high` | `HGDG_MAX` | `float64` | Düzeltilmiş | Düzeltilmiş günlük en yüksek fiyat | T tarihinde sorgulanabilir; gelecekteki düzeltmelerden etkilenebilir | Kaynak doğrulama; tavan ve ham label hesabında kullanılmaz | Eksik olarak korunur | Pozitiflik, düzeltilmiş OHLC sınırları ve katsayı tutarlılığı |
| `is_tl_volume` | `HGDG_HACIM` | `float64` | Hacim; fiyat düzeltmesi uygulanmıyor | Günlük TL işlem hacmi; kabul örneğinde `HG_HACIM` ile aynı değer | İlgili günün kapanışı sonrasında mevcut | D022 işlem gerçekleşme ve veri kalite kontrolü | yFinance hacmiyle birlikte değerlendirilir; iki kaynak da eksikse açık durum | Negatif olmama, sıfır/eksik ve kaynaklar arası hacim bayrakları |
| `index_code` | `END_ENDEKS_KODU` | `object` | Referans | Hisse yanıtında eşlik eden endeks kodu; kabul panelinde literal `XU100` yerine `1` gözlendi | İlgili gün sonrasında yalnız kalite/çapraz kontrol için mevcut; feature veya fallback değildir | XU100 kimlik tutarlılığı denetimi; label/backtest fiyatı değildir | Eksik olarak korunur; doğrulanmış XU100 yerine kullanılmaz | Aynı gün hisseler arası kod tutarlılığı; literal `XU100` varsayılmaz |
| `index_timestamp` | `END_TARIH` | `int64` | Referans | Hisse yanıtındaki endeks kaydının milisaniye epoch zaman damgası | İlgili gün sonrasında yalnız kalite/çapraz kontrol için mevcut; feature veya fallback değildir | Aynı gün farklı hisselerde tarih tutarlılığı denetimi | Eksikse END_* çapraz kontrolü kurulmaz; doğrulanmış XU100 etkilenmez | Hisse tarihi ve aynı gün diğer hisselerin END_* tarihiyle uyum |
| `index_session` | `END_SEANS` | `int64` | Referans | Hisse yanıtında eşlik eden endeks seans kodu | İlgili gün sonrasında yalnız kalite/çapraz kontrol için mevcut; feature veya fallback değildir | Aynı gün farklı hisselerde seans tutarlılığı denetimi | Eksik olarak korunur; doğrulanmış XU100 yerine kullanılmaz | Aynı gün hisseler arası seans kodu tutarlılığı |
| `index_value` | `END_DEGER` | `float64` | Referans | Hisse yanıtında eşlik eden endeks değeri | İlgili gün sonrasında yalnız kalite/çapraz kontrol için mevcut; feature veya fallback değildir | Aynı gün farklı hisselerde değer tutarlılığı ve doğrulanmış XU100 ile tanısal fark kontrolü | Eksik olarak korunur; market/relative feature'lar yalnız `validated_xu100_close` kullanır | Pozitiflik, tarih/seans uyumu ve aynı gün hisseler arası değer tutarlılığı |
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

## D026 Fiyat Adımı Referans Verisi

`reference_data/bist_equity_tick_sizes_v1.csv`, Borsa İstanbul'un `E-18454353-100.04.02-19412` sayılı resmî duyurusundaki pay fiyat adımlarını tarih-etkin ve eklemeli biçimde saklar. Fiyat bantları alt sınırı dahil, üst sınırı hariçtir. Son bandın `price_max_exclusive` değeri boştur ve sonsuz üst sınırı ifade eder.

| Alan | Anlam |
| --- | --- |
| `rule_set_id` | Değişmez tarife rejimi kimliği |
| `instrument_type` | Tarifenin araç türü; bu dosyada yalnız `EQUITY` |
| `effective_from` | Rejim başlangıcı, dahil |
| `effective_to` | Rejim sonu, dahil; boşsa açık uçlu |
| `price_min_inclusive` | Fiyat bandının dahil alt sınırı |
| `price_max_exclusive` | Fiyat bandının hariç üst sınırı; boşsa açık uçlu |
| `tick_size` | İlgili fiyat bandının TRY fiyat adımı |
| `currency` | `TRY` |
| `official_source_name` | Resmî kurum; `Borsa İstanbul` |
| `official_document_number` | `E-18454353-100.04.02-19412` |
| `official_document_date` | Belge tarihi; `2023-08-28` |
| `official_effective_date` | Belgede belirtilen değişiklik yürürlük tarihi; `2023-11-06` |
| `official_source_url` | Resmî PDF adresi |
| `source_checksum` | Doğrulanan PDF'nin SHA-256 özeti |
| `notes` | Kaynak yorumu ve kapsam sınırı; eski rejimin `2020-03-13` başlangıcının proje model dönemi başlangıcı olduğu burada açıklanır |

Referans tablosu yüklenirken her rejimin `[0.01, ∞)` fiyat aralığını boşluksuz/çakışmasız kapattığı, tarih rejimlerinin ardışık olduğu, resmî kaynak metadata'sının tam bulunduğu ve checksum biçiminin SHA-256 olduğu doğrulanır. Bilinmeyen tarih veya pay dışı araç için kural döndürülmez.

## D027 Security Kimliği ve Ticker Mapping Alanları

`reference_data/bist_security_ticker_map_v1.csv`, yalnız açıkça doğrulanıp elle eklenen ticker değişikliklerini dahil tarih aralıklarıyla taşır. Boş referans dosyası geçerlidir; mapping'de bulunmayan ticker veri akışını durdurmadan deterministik otomatik security olur. Aynı security altındaki aralıklar ve aynı ticker'ın farklı security'lere bağlandığı aralıklar çakışamaz.

| Mapping alanı | Anlamı |
| --- | --- |
| `security_id` | Eski ve güncel ticker dönemlerini birleştiren kalıcı pay kimliği |
| `ticker` | Sağlayıcı uzantısı kaldırılmış büyük harf BİST işlem kodu |
| `valid_from` | Ticker döneminin dahil ilk geçerli tarihi |
| `valid_to` | Ticker döneminin dahil son geçerli tarihi; güncel açık uçlu dönemde boş |
| `is_current_ticker` | Satırın security için güncel ticker olup olmadığı |
| `mapping_status` | Elle doğrulanmış referans satırının durumu; doğrulanmış satırda `CONFIRMED` |
| `official_source_name` | Doğrulamada kullanılan resmî kurum |
| `official_source_reference` | Resmî duyuru/belge referansı |
| `official_source_date` | Resmî belgenin tarihi |
| `official_source_url` | Resmî kaynak bağlantısı |
| `notes` | Kapsam ve doğrulama notu |

`security_identity/nominal_ohlc`, yalnız checksum doğrulamasından geçen `COMPLETE` yFinance nominal snapshot'larını okur, kaynak snapshot'ları değiştirmez ve aynı `security_id + date` serisini ayrı değişmez derived snapshot olarak yazar. Geçerlilik dışı provider satırı kullanılmaz; mükerrer kayıtta tarih-etkin açık mapping satırı tercih edilir. Mapping sürümü/checksum'u snapshot istek metadata'sında ve her satırda saklanır.

| Çıktı alanı | Kaynak/formül | Anlamı | Feature kuralı |
| --- | --- | --- | --- |
| `security_id` | Açık mapping; yoksa `SEC_` + `SHA256("BIST:EQUITY:" + normalized_ticker)` ilk 12 hex | Ticker dönemlerinden bağımsız kalıcı gruplama kimliği | Yalnız kimlik ve rolling/group anahtarıdır; sinyal değildir |
| `observed_ticker` | Provider satırındaki normalize ticker | İlgili tarihte gerçekten gözlenen kod; geçmiş değer değiştirilmez | Kimlik/audit alanıdır |
| `current_ticker` | Aynı security'nin `is_current_ticker=true` satırı; otomatik security'de observed ticker | Güncel provider/raporlama kodu | Feature yapılmaz |
| `ticker_mapping_status` | Resolver | `MAPPED_CURRENT_TICKER`, `MAPPED_HISTORICAL_TICKER`, `AUTO_NEW_TICKER` veya `OUTSIDE_VALIDITY` | Feature yapılmaz; otomatik durum dışlama değildir |
| `ticker_mapping_rule_id` | Mapping satırının canonical SHA-256 özeti | Kullanılan tarih-etkin kural kimliği; otomatik/geçerlilik dışı durumda boş | Lineage; feature yapılmaz |
| `ticker_mapping_version` | Mapping dosya adı/sürümü | Identity çözümünün referans sürümü | Lineage; feature yapılmaz |
| `ticker_mapping_checksum` | Normalize mapping içeriğinin SHA-256 özeti | Aynı mapping'in yeniden üretilebilir kimliği | Lineage; feature yapılmaz |

Identity-etkin yeni tam veri yolunda bu yedi alan clean ve label snapshot'larına taşınır; clean ve label satır kimliği/gruplaması `security_id + prediction_date` olur. Eski identity alanı içermeyen küçük snapshot'lar geriye uyumlu olarak `ticker + prediction_date` kullanmaya devam eder. `baseline_v1` feature rolling hesapları `ticker` yerine `security_id` ile yapılır; mapping durumu, geçiş tarihi, güncel ticker ve resmî kaynak metadata'sı modele verilmez.

## D022/D023/D026/D027 Temiz Snapshot Alanları

`cleaning/market_data_eligibility` yalnız fiziksel checksum'ı doğrulanan `COMPLETE` İş Yatırım raw, yFinance raw ve ilgili yFinance raw snapshot ID'sini `input_snapshot_ids` içinde taşıyan `yfinance/nominal_ohlc` snapshot'larından üretilir. Ana takvim, TL hacmi, kurumsal aksiyon sinyali ve fiyat kalite karşılaştırması İş Yatırım'dan; fiyat bağımlı bütün hesaplar yalnız yFinance nominal OHLC'den gelir. Ham snapshot'lar değiştirilmez.

Temiz snapshot tarihsel uygunluk datasetidir. `prediction_date=T` satırında `entry_date=T+1` ve kurumsal aksiyon penceresi `T+1–T+3` global İş Yatırım BİST takviminden kurulur. `T+1` giriş günü alanları ve `T+1–T+3` aksiyon sonucu T kapanışında bilinmediğinden model feature'ı değildir; yalnız tarihsel giriş/işlem uygunluğu ve ilerideki label/backtest dışlama akışı içindir.

| Alan | Kaynak/formül | Anlam ve durum davranışı | Tahmin anı / veri sızıntısı kuralı |
| --- | --- | --- | --- |
| `ticker` | Snapshot seti | Hisse işlem kodu | Kimlik; feature değildir |
| `trade_date` | BİST takvimi | Bu datasette `entry_date` ile aynı T+1 işlem günü | T kapanışında gelecektir; feature değildir |
| `prediction_date` | BİST takvimi | Tahmin satırının T tarihi | Zaman bölme ve kimlik alanı |
| `entry_date` | `prediction_date` sonrasındaki ilk BİST günü | T+1 giriş günü | T kapanışında tarih bilinir, o güne ait veri bilinmez |
| `yf_nominal_open` | D024 nominal snapshot | T+1 giriş fiyatı; eksik veya pozitif değilse `NO_OPEN` | T kapanışında bilinmez; feature değildir |
| `yf_nominal_high` | D024 nominal snapshot | T+1 günlük yüksek; nominal OHLC kontrolünün parçası | T kapanışında bilinmez; feature değildir |
| `yf_nominal_low` | D024 nominal snapshot | T+1 günlük düşük; `low <= open/close <= high` kontrolü | T kapanışında bilinmez; feature değildir |
| `yf_nominal_close` | D024 nominal snapshot | T+1 kapanış; günlük kalite ve sonraki günün tavan bazı | T+1 kapanışına kadar bilinmez; T satırında feature değildir |
| `is_tl_volume` | İş Yatırım `HGDG_HACIM` | T+1 TL hacmi; yFinance hacmiyle birlikte D022 kontrolü | T kapanışında bilinmez; feature değildir |
| `yf_share_volume` | yFinance `Volume` | T+1 adet hacmi; İş Yatırım hacmiyle birlikte D022 kontrolü | T kapanışında bilinmez; feature değildir |
| `previous_nominal_close` | Giriş gününden önceki son geçerli `yf_nominal_close` | Standart tavan baz fiyatı; bulunamazsa `NO_PREVIOUS_CLOSE` | T+1 için normalde T kapanışında bilinir; yalnız tavan/uygunluk hesabıdır |
| `raw_upper_limit` | `Decimal(str(previous_nominal_close)) × Decimal("1.10")` | Fiyat adımına yuvarlanmamış standart üst limit | Model feature'ı değildir |
| `tick_size` | D026 tarih-etkin `EQUITY` referans tablosu | `entry_date` ve `raw_upper_limit` için çözülen TRY fiyat adımı; kural yoksa `NA` | Yalnız işlem uygunluğu; feature değildir |
| `price_step` | `tick_size` | Geriye uyumluluk için aynı değeri taşıyan eski alan adı | Feature değildir |
| `tick_rule_set_id` | D026 referans tablosu | Çözülen değişmez rejim kimliği; kural yoksa `NA` | Lineage/denetim; feature değildir |
| `tick_rule_effective_from` | D026 referans tablosu | Çözülen rejimin dahil başlangıç tarihi | Denetim; feature değildir |
| `tick_rule_effective_to` | D026 referans tablosu | Çözülen rejimin dahil son tarihi; açık uçluysa `NA` | Denetim; feature değildir |
| `estimated_upper_limit` | `raw_upper_limit` değerinin `tick_size` katına `Decimal` ile içeri/aşağı yuvarlanması | Standart adi pay tahmini tavanı | Yalnız giriş uygunluğu kontrolü; feature değildir |
| `price_step_resolution_status` | Tarife çözümlemesi | `RESOLVED` veya `UNAVAILABLE` | Denetim; feature değildir |
| `official_source_document` | Çözülen D026 kuralı | Borsa İstanbul kurum, belge numarası ve belge tarihi | Lineage/denetim; feature değildir |
| `ohlc_quality_flag` | yFinance nominal OHLC | `VALID`, `NO_OPEN` veya `INVALID_OHLC` | T+1 sonucu; feature değildir |
| `volume_quality_flag` | İki bağımsız hacim kaynağı | Hacim kanıtı/uyuşmazlığı/çözümsüzlük durumu | T+1 sonucu; feature değildir; düşük pozitif hacim eşiği yoktur |
| `cross_source_price_warning` | yFinance nominal high/low/close ile İş Yatırım raw high/low/close karşılaştırması | Yalnız kalite uyarısı; satırı dışlamaz ve fiyatları birleştirmez | Model feature'ı değildir |
| `corporate_action_flag` | yFinance action veya İş Yatırım düzeltme faktörü değişimi | T+1 günlük bağımsız aksiyon sinyallerinin birleşimi | Tarihsel sorgu gelecekteki düzeltmeleri içerebilir; feature değildir |
| `corporate_action_signal_sources` | İki bağımsız sinyal | `isyatirim_adjustment_factor` ve/veya `yfinance_actions` listesi | Feature değildir; denetim alanıdır |
| `corporate_action_source_count` | Sinyal kaynakları | Günlük sinyal veren kaynak sayısı (`0–2`) | Feature değildir |
| `corporate_action_source_agreement` | Sinyal kaynakları | `NO_SIGNAL`, `SINGLE_SOURCE` veya `BOTH_SOURCES` | Feature değildir |
| `corporate_action_window_flag` | Global BİST takviminde T+1–T+3 günlük sinyaller | Pencerede en az bir olay varsa `true` ve satır dışlanır | Gelecek bilgi içerir; feature/sinyal yapılamaz |
| `corporate_action_window_dates` | T+1–T+3 aksiyon tarihleri | Olay görülen BİST günlerinin listesi | Gelecek bilgi; yalnız tarihsel dışlama/denetim |
| `corporate_action_window_signal_sources` | Penceredeki bağımsız sinyaller | Pencere boyunca gözlenen kaynakların birleşik listesi | Gelecek bilgi; feature değildir |
| `entry_eligible` | Bütün D022/D023 giriş kuralları | `true`, kesin dışlamada `false`, çözülmemiş kalite durumunda `NA` | T+1/T+3 sonuçlarını feature'a dönüştürmez |
| `entry_exclusion_reason` | Deterministik raporlama önceliği | İlk/ana durum kodu | Yalnız raporlama; tek başına tam gerekçe değildir |
| `entry_exclusion_reasons` | Bütün tetiklenen kurallar | Sıralı tam durum kodu listesi | Denetim ve downstream filtreleme; feature değildir |
| `entry_exclusion_detail` | `NO_PREVIOUS_CLOSE` ayrıntısı | İlk gün/geçmiş yoksa `FIRST_TRADING_DAY_OR_NO_HISTORY` | Denetim alanıdır |
| `requires_review` | Çözümsüz hacim veya fiyat adımı durumu | İnsan/veri kaynağı incelemesi gereken satır | `true` iken başka kesin dışlama yoksa `entry_eligible=NA` |
| `input_snapshot_ids` | Manifest | Satırın üç doğrulanmış kaynak snapshot kimliği | Veri lineage; feature değildir |
| `input_snapshot_checksums` | Manifest | Kaynak içerik checksum'ları | Tekrarlanabilirlik ve fiziksel doğrulama; feature değildir |
| `cleaning_config_checksum` | Merkezi `CleaningConfig` | Etkin D022/D023 ayarlarının SHA-256 kimliği | Denetim alanıdır |
| `cleaning_code_commit_sha` | Repo | Temizleme kodunu tanımlayan commit SHA | Denetim alanıdır |
| `cleaning_version` | Merkezi config | İlk sürümde `d022-d023-v1` | Şema/kural sürümü; feature değildir |

### Durum Kodları ve Öncelik

Ana neden önceliği yalnız raporlama içindir; bütün nedenler `entry_exclusion_reasons` içinde korunur: `NO_OPEN`, `NO_TRADE`, `INVALID_OHLC`, `NO_PREVIOUS_CLOSE`, `SPECIAL_MARGIN_OR_CORPORATE_ACTION`, `LIMIT_OPEN`, `CORPORATE_ACTION_WINDOW`, `PRICE_STEP_UNAVAILABLE`.

| Kod/bayrak | Anlam | `entry_eligible` etkisi |
| --- | --- | --- |
| `NO_OPEN` | T+1 nominal open eksik, sonlu değil veya pozitif değil | `false` |
| `NO_TRADE` | İş Yatırım TL hacmi ve yFinance adet hacmi birlikte `0` | `false` |
| `INVALID_OHLC` | Open mevcutken OHLC eksik/pozitif değil veya sınır ilişkileri geçersiz | `false` |
| `NO_PREVIOUS_CLOSE` | Giriş gününden önce geçerli nominal kapanış yok | `false`, `requires_review=true` |
| `LIMIT_OPEN` | T+1 nominal open tahmini tavana yalnız küçük kayan nokta toleransıyla eşit | `false` |
| `SPECIAL_MARGIN_OR_CORPORATE_ACTION` | T+1 nominal open veya high standart tahmini tavanı aşıyor | `false`, `requires_review=true` |
| `CORPORATE_ACTION_WINDOW` | T+1–T+3 BİST günlerinden en az birinde bağımsız aksiyon sinyali var | `false` |
| `PRICE_STEP_UNAVAILABLE` | Tarih/fiyat için doğrulanmış fiyat adımı kuralı yok | Başka dışlama yoksa `NA`, `requires_review=true` |
| `BOTH_VOLUMES_MISSING_UNRESOLVED` | Open var fakat iki hacim de eksik | Başka dışlama yoksa `NA`, `requires_review=true` |
| `SOURCE_VOLUME_CONFLICT` | Bir hacim pozitifken diğeri sıfır veya eksik | Dışlamaz; kalite uyarısı |
| `POSITIVE_VOLUME_CONFIRMED` | En az bir pozitif hacim var ve kaynak çatışması yok | Hacim nedeniyle dışlamaz |

`LIMIT_OPEN` eşitliğinde `rtol=1e-12`, `atol=1e-8` yalnız sağlayıcı/çıktı sınırındaki kayan nokta gürültüsü içindir; bir tam fiyat adımı tolerans olarak kullanılmaz. Para, band seçimi ve fiyat adımına yuvarlama hesapları `Decimal` ile yapılır. D026 tablosunda tarih/fiyat/enstrüman için kural yoksa `tick_size`, `price_step`, kural metadata'sı ve `estimated_upper_limit` `NA` kalır; durum `UNAVAILABLE` olarak kaydedilir.

## D011–D014 Üç Günlük Label Snapshot Alanları

`derived/labels/three_day_target`, yalnız fiziksel checksum doğrulamasından geçen `COMPLETE` `cleaning/market_data_eligibility` snapshot'larından üretilir. Kaynak clean veya raw snapshot üzerine yazılmaz. Doğrudan kaynak clean snapshot ID/checksum'u, label config checksum'u ve üretim kodu commit SHA'sı her satırda ve snapshot metadata'sında saklanır.

Global BİST takvimi clean snapshot'taki tutarlı `prediction_date → entry_date` ilişkilerinden kurulur. Bir ticker satırı eksik olduğunda horizon sonraki mevcut ticker gününe kaydırılmaz. T+2/T+3 takvim bağı veya ilgili ticker/gün clean satırı bulunamazsa label `NA` kalır. T+4 ve sonrası fiyatlar label hesabına girmez.

| Alan | Kaynak/formül | Anlam ve durum davranışı | Tahmin anı / veri sızıntısı kuralı |
| --- | --- | --- | --- |
| `ticker` | Kaynak clean snapshot | Hisse işlem kodu | Kimlik; feature değildir |
| `prediction_date` | Kaynak clean snapshot | Tahmin tarihi `T` | Zaman bölme/kimlik alanı |
| `entry_date` | Global BİST takvimi | `T+1` giriş tarihi | Tarih T kapanışında bilinir; o günün fiyatı bilinmez |
| `horizon_t2_date` | Global BİST takvimi | İkinci horizon işlem günü | Gelecek sonuç tarihi; feature değildir |
| `horizon_t3_date` | Global BİST takvimi | Üçüncü horizon işlem günü | Gelecek sonuç tarihi; feature değildir |
| `entry_price` | `yf_nominal_open[T+1]` | Giriş fiyatı; yalnız giriş uygun ve pozitifse kullanılır | T kapanışında bilinmez; label sonucu alanıdır |
| `raw_target_price` | `Decimal(str(entry_price)) × Decimal("1.05")` | Fiyat adımına yuvarlanmamış brüt `%5` hedef | Label hesabı; feature değildir |
| `target_tick_size` | D026 tablosu; `entry_date + EQUITY + raw_target_price` | Hedef emir için çözülen fiyat adımı | Tarih-etkin referans; feature değildir |
| `target_price` | `raw_target_price` değerinin `target_tick_size` katına `Decimal` ile yukarı yuvarlanması | Uygulanabilir hedef satış fiyatı; aşağı yuvarlanmaz | Label/backtest işlem kuralı; feature değildir |
| `target_hit` | T+1–T+3 `yf_nominal_high` | Üç günden birinde high hedefe eşit/yüksekse `true`; NA satırda `NA` | Gelecek sonuç; feature değildir |
| `target_hit_date` | İlk hedef high günü | Hedefe ilk ulaşılan global BİST tarihi | Gün içi saat bilinmez; yalnız günlük high kanıtıdır |
| `target_hit_horizon` | İlk hedef günü | `1`, `2` veya `3`; hedef yoksa/NA ise boş | Gelecek sonuç; feature değildir |
| `label` | `max(high[T+1:T+3]) >= target_price` | Pozitif `1`, hedef yoksa `0`, uygunluk/veri sorunu varsa nullable `NA` | Yalnız tamamlanmış horizon eğitimde kullanılabilir |
| `label_status` | Label üretim sonucu | `LABELED` veya `NA` | Eğitim filtresi/denetim alanı |
| `label_exclusion_reason` | İlk source veya label kalite nedeni | NA kaydın ana nedeni | Negatif sınıf değildir |
| `label_exclusion_reasons` | Source clean nedenleri veya label kalite nedeni | Source dışlamalarını kaybetmeyen tam neden listesi | Denetim; feature değildir |
| `exit_date` | İlk hedef günü veya T+3 | Hedefte ilk hit tarihi; hedefsiz işlemde T+3 | Gelecek sonuç; feature değildir |
| `exit_price` | `target_price` veya `yf_nominal_close[T+3]` | Brüt label senaryosu çıkış fiyatı | Komisyon/slippage içermez |
| `exit_reason` | Label sonucu | `TARGET_HIT` veya `HORIZON_CLOSE`; NA kayıtta boş | Denetim; feature değildir |
| `gross_return` | `exit_price / entry_price - 1` | Brüt fiyat getirisi | Komisyon/slippage içermez; net backtest getirisi değildir |
| `input_clean_snapshot_id` | Snapshot manifesti | Doğrudan kaynak clean snapshot kimliği | Lineage; feature değildir |
| `input_clean_snapshot_checksum` | Snapshot manifesti | Fiziksel olarak doğrulanmış clean içerik checksum'u | Lineage/tekrarlanabilirlik |
| `label_config_checksum` | Merkezi `LabelConfig` | `%5`, üç gün, `EQUITY` ve label sürümü ayarlarının SHA-256 kimliği | Denetim alanı |
| `label_code_commit_sha` | Repo | Label kodunu tanımlayan commit SHA | Denetim alanı |
| `label_version` | Merkezi `LabelConfig` | `d011-d014-d020-d023-d024-d026-v1` | Kural/şema sürümü |

`entry_eligible != true`, `requires_review=true` veya source `entry_exclusion_reasons` doluysa label hesaplanmaz. `CORPORATE_ACTION_WINDOW`, `LIMIT_OPEN`, `NO_OPEN`, `NO_TRADE`, `INVALID_OHLC`, `NO_PREVIOUS_CLOSE`, `SPECIAL_MARGIN_OR_CORPORATE_ACTION` ve `PRICE_STEP_UNAVAILABLE` nedenleri korunur. Ek label nedenleri `ENTRY_NOT_ELIGIBLE`, `REQUIRES_REVIEW`, `TARGET_TICK_SIZE_UNAVAILABLE`, `INCOMPLETE_HORIZON`, `MISSING_HORIZON_ROW`, `HORIZON_NO_TRADE`, `INVALID_HORIZON_PRICE` ve `MISSING_T3_CLOSE` olabilir. Bunların hiçbiri negatif label değildir.

Label hesabı yalnız yFinance nominal open/high/close alanlarını kullanır. İş Yatırım fiyatları, `yf_future_split_factor`, gelecek action alanları, komisyon ve slippage label formülüne girmez. Kurumsal işlem penceresi clean snapshot'taki tarihsel dışlama sonucu olarak taşınır; model feature'ına dönüştürülmez.

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

## D029 Global BİST Takvimi Alanları

`derived/isyatirim/global_bist_sessions`, yalnız doğrulanmış `COMPLETE` raw İş Yatırım hisse snapshot'larındaki gerçek `HGDG_TARIH` birleşimidir.

| Alan | Kaynak/formül | Anlam | Feature/leakage kuralı |
| --- | --- | --- | --- |
| `session_date` | Raw İş Yatırım `HGDG_TARIH` birleşimi | Gerçek gözlenen global BİST oturumu | Sentetik hafta içi veya doldurma yok |
| `session_index` | Artan `session_date` üzerinde sıfır tabanlı sıra | Exact shift/rolling oturum konumu | Security satır eksikliğinde sıkıştırılamaz |

Takvim metadata'sı doğrudan kaynak snapshot ID/checksum'larını ve `verified_isyatirim_stock_session_union_v1` yöntemini taşır. Tek hissedeki eksik tarih global seansı kaldırmaz.

## D029 XU100 Snapshot Alanları

Raw seri `raw/isyatirim/xu100_index_history`; kabul edilen benchmark `derived/benchmark/validated_xu100_close` altında saklanır.

| Alan | Katman | Anlam | Kabul/leakage kuralı |
| --- | --- | --- | --- |
| `index_code` | Raw + validated | Bağımsız endpoint endeks kimliği | Tam olarak `XU100` olmalıdır |
| `source_timestamp_ms` | Raw + validated | Sağlayıcının değişmeden korunan epoch milisaniyesi | Sayısal ham değer canonicalizer tarafından tarihe çevrilmez |
| `source_value` | Raw | Sağlayıcının değişmeden korunan endeks değeri | Pozitif ve sonlu olmalıdır |
| `utc_calendar_date` | Raw + validated denetim | Epoch'un UTC takvim günü | Ana eşleme değildir |
| `istanbul_calendar_date` | Raw denetim | UTC-aware timestamp'in `Europe/Istanbul` takvim günü | Doğrulama sonrası `prediction_date` olur |
| `legacy_plus_one_date` | Raw + validated denetim | Eski sabit `+1 gün` adayının sonucu | Yalnız tanısal; ana yöntem/fallback değildir |
| `prediction_date` | Validated | Kabul edilmiş İstanbul takvim günü | Global BİST seansıyla birebir eşleşir |
| `validated_xu100_close` | Validated | Aynı seansın doğrulanmış XU100 kapanışı | Market/relative feature kaynağı |
| `timestamp_resolution_rule` | Validated | `utc_epoch_ms_to_europe_istanbul_calendar_date_v1` | Sabit `+1 gün` kullanılmadığını denetler |
| `validation_status` | Validated | Kabul edilen satırlarda `PASS` | Belirsizlikte snapshot üretilmez |

`END_ENDEKS_KODU`, `END_TARIH`, `END_SEANS`, `END_DEGER` ve yFinance `XU100.IS` yalnız çapraz kontrol raporuna girer; doğrulanmış kapanışa fallback olamaz.

## D029 baseline_v1 Feature Snapshot Alanları

`derived/features/baseline_v1` anahtarı `security_id + prediction_date` olan tam 32 feature içerir. Sıra `FEATURE_CATALOG.md` ve `src/features/catalog.py` içindeki tek sabit listeyle belirlenir. Kimlikler model feature'ı değildir.

Feature hesabına girebilen kaynak alanları yalnız şunlardır:

```text
security_id
prediction_date
yf_provider_open
yf_provider_high
yf_provider_low
yf_provider_close
is_tl_volume
validated_xu100_close
```

Feature metadata/provenance alanları:

| Alan | Anlam |
| --- | --- |
| `feature_set_id` | `baseline_v1` |
| `feature_catalog_version` | Bağlayıcı katalog sürümü |
| `feature_catalog_file_sha256` | `FEATURE_CATALOG.md` ham dosya özeti |
| `feature_config_checksum` | Etkin merkezi `FeatureConfig` özeti |
| `feature_names` / `feature_count` | Sıralı 32 alan ve sayısı |
| `input_snapshot_ids` / `input_content_checksums` | Bütün doğrudan raw/identity/XU100/takvim girdileri |
| `global_calendar_snapshot_id` / `global_calendar_checksum` | Exact oturum ızgarası bağı |
| `xu100_snapshot_id` / `xu100_checksum` | Doğrulanmış benchmark bağı |
| `ticker_mapping_version` / `ticker_mapping_checksum` | Tarih-etkin security kimlik bağı |
| `excluded_non_session_provider_rows` | Takvim min/max sınırları içinde olup doğrulanmış global BİST oturumu olmayan yFinance satırlarının toplamı |
| `excluded_non_session_provider_ticker_count` | Bu audit sınıfından etkilenen tekil provider ticker sayısı |
| `excluded_non_session_provider_date_counts` | Hariç tutulan satırların tarih bazında deterministik sayımları |
| `excluded_non_session_provider_audit_checksum` | Canonical ticker+tarih audit kaydının SHA-256 özeti |
| `revision_context_checksum` | İçerikten bağımsız provenance revizyon kimliği |
| `quality_summary` | Her feature için `valid`, `missing`, `warmup`, `source_missing`, `invalid_math`, `xu100_missing`, `cross_section_insufficient`, `infinite_replaced` sayıları |

Per-row 32 ayrı missing-reason sütunu üretilmez. `NaN` imputasyon yapılmadan korunur; sonsuz sonuçlar `NaN` yapılır ve kalite özetinde sayılır. D029 global takvim sınırları içindeki fakat doğrulanmış oturum kümesinde bulunmayan provider satırları feature hesabından önce hariç tutulup yukarıdaki provenance alanlarıyla denetlenir. Takvim min/max sınırları dışındaki provider tarihi sessizce kırpılmaz; fail-closed hatadır. Bu işlem feature allowlist'ini veya 32 feature formülünü değiştirmez.

## D034 Aktif BİST Pay Evreni Alanları

`reference_data/bist_active_universe_v1.csv`, KAP BIST Şirketleri ile KAP Pazarlar verisinin exact `as_of_date` kesitinden üretilir. KAP üyeliği sona eren şirketler hariç tutulur; Borsa İstanbul İşlem Gören Şirketler sayfasının Pay Piyasası ve KAP referansı çapraz kontrol olarak saklanır. Her ham HTML yanıtı `official_reference/active_universe_source_html` raw snapshot'ında source URL, as-of, ham içerik checksum'u, parser sürümü ve kod SHA ile korunur.

| Alan | Kaynak/formül | Anlam | Leakage/model kuralı |
| --- | --- | --- | --- |
| `universe_version` | Sabit `bist_active_universe_v1` | Aktif master evren sürümü | Model feature'ı değildir |
| `as_of_date` | CLI exact tarih girdisi | Kaynak kesitinin tarihi | Tarihsel membership point-in-time iddiası değildir |
| `security_id` | `generate_security_id(current_ticker)`; doğrulanmış alias varsa aynı kalıcı kimlik | Snapshot tekil anahtarı | Kimliktir, feature değildir |
| `current_ticker` | KAP Pazarlar `stockCode` | As-of tarihteki işlem kodu | Provider sınırında `.IS` eklenebilir; feature değildir |
| `company_name` | KAP Pazarlar `title` | Resmî şirket/pay adı | Feature değildir |
| `market_group`, `market_name` | KAP `financialMarketName`, `marketName` | Pay Piyasası ve alt pazar üyeliği | Likidite veya model sinyali yapılmaz |
| `instrument_type` | KAP şirket üyeliği, `fundOid`, pazar ve resmî ad sınıflaması | `EQUITY` dahil; fon/ETF/sertifika vb. audit'te hariç | Yalnız evren kapsamı |
| `is_active`, `include_in_v1` | Resmî active-company + Pay Piyasası eşleşmesi | V1 master üyeliği | D030 ön koşuludur; T+1 sonucu kullanmaz |
| `official_source_name/reference/date/url` | KAP pazar kaydı | Satır bazlı resmî provenance | Feature değildir |
| `source_record_checksum` | Canonical kaynak kayıt SHA-256 | Satır kaynağının değişim bağı | Feature değildir |

Derived snapshot `source=universe`, `dataset_type=active_bist_equities`, `layer=derived`, `ticker_or_instrument=BIST_ACTIVE_EQUITIES` kimliğini taşır. Metadata `input_snapshot_ids`, `input_content_checksums`, `active_universe_file_checksum`, `ticker_mapping_version`, `ticker_mapping_checksum`, `as_of_date`, `parser_version`, `code_commit_sha`, `included_security_count` ve `excluded_candidate_count` alanlarına bağlanır. Anahtar `security_id` tekildir; aynı içerik ve bağlam idempotent, kaynak/checksum bağlamı değişirse yeni revision'dır.

## D030 Prediction Universe ve Eğitim Dataset Alanları

Prediction universe anahtarı `security_id + prediction_date` olur. Üretim assembler'ı `active_universe_snapshot_id` olmadan çalışmaz ve master üyeliği yalnız doğrulanmış `universe/active_bist_equities/derived` snapshot'ındaki tekil `security_id` listesinden alır. Identity snapshot yalnız ticker ve nominal OHLC çözümüdür; master evren fallback'i olamaz. Sentetik testler master security listesini açık fixture olarak verir. Duplicate master/observation/feature anahtarı açık hatadır.

| Alan | Kaynak/formül | Anlam | Leakage/model kuralı |
| --- | --- | --- | --- |
| `prediction_eligible` | D030 koşullarının tamamı | Satırın T kapanışı sonrasında skorlanabilir olduğunu gösterir | Yalnız T ve geçmiş bilgi |
| `prediction_exclusion_reason` | İlk fail-closed D030 nedeni | `NOT_IN_MASTER_UNIVERSE`, `NO_T_OBSERVATION`, `INVALID_T_OHLC`, `NO_TRADE_ON_T`, `MISSING_TRADE_EVIDENCE`, `INSUFFICIENT_HISTORY`, `MISSING_FEATURE_ROW`, `MISSING_XU100_SESSION`; duplicate feature koşuyu durdurur | Model feature'ı değildir |
| `available_history_sessions` | Security'nin ilk gerçek gözleminden T'ye global `session_index` farkı + 1 | 21 oturum warm-up kontrolü | Eksik security günleri sıkıştırılmaz |
| `label_available_date` | T sonrasındaki üçüncü global BİST oturumu | Labelın as-of zamanda bilindiği ilk tarih | Ticker satır `shift(3)` kullanılmaz |
| `feature_snapshot_id` | Doğrulanmış feature girdisi | Satırın feature provenance bağı | Model feature'ı değildir |
| `label_snapshot_id` | Doğrulanmış label girdisi | Satırın label provenance bağı | Model feature'ı değildir |
| `active_universe_snapshot_id` | Doğrulanmış D034 master snapshot | Eğitim/prediction master üyelik bağı | Zorunlu provenance; feature değildir |
| `active_universe_snapshot_checksum` | Master snapshot içerik checksum'u | Evren değişimini training fingerprint'e bağlar | Değişirse yeni fingerprint |
| `active_universe_version`, `active_universe_as_of_date` | Snapshot request/revision context | Dondurulan evren sürümü ve exact tarihi | Model feature'ı değildir |

T-günü OHLC geçerliliği yalnız identity snapshot'taki `yf_nominal_open/high/low/close` ile kontrol edilir. İşlem kanıtı raw İş Yatırım `HGDG_HACIM → is_tl_volume` veya raw yFinance `Volume → yf_share_volume` pozitifliğidir; ikisi de yoksa `MISSING_TRADE_EVIDENCE`, ikisi de mevcut ve sıfırsa `NO_TRADE_ON_T` üretilir. Bu OHLC/hacim alanları evren audit girdileridir, 32 feature model matrisine eklenmez.

## D031–D033 Walk-Forward, OOS ve Model Artifact Alanları

Walk-forward fold tanımı aşağıdaki tarih alanlarını taşır:

```text
fold_id
training_start_date
training_end_date
fit_calendar_session_count
fit_labeled_session_count
fit_purged_session_count
validation_start_date
validation_end_date
validation_calendar_session_count
validation_labeled_session_count
validation_purged_session_count
test_start_date
test_end_date
test_calendar_session_count
```

`training_start_date`, 21 oturumluk warm-up tamamlandıktan sonraki ilk oturumdur. `fit_calendar_session_count` bu tarihten validation başlangıcından önceki son takvim oturumuna kadar olan nominal expanding fit penceresini; `fit_labeled_session_count` strict availability sonrası kullanılabilir oturumları; `fit_purged_session_count` ise label sonucu henüz bilinmeyen son üç oturumu gösterir. Validation tarafında aynı ayrım 60 takvim oturumu, 57 labeled oturum ve 3 purged oturum olarak saklanır. `fit_used_session_count` ve `validation_used_session_count`, D030 eligibility ve geçerli label koşullarından sonra modelde fiilen en az bir satırla temsil edilen oturum sayılarıdır.

Fit satırında `label_available_date < validation_start_date`, validation satırında `label_available_date < test_start_date` zorunludur. Test satırları label durumundan bağımsız olarak eligible ise skorlanır.

OOS minimum şeması:

| Alan | Anlam |
| --- | --- |
| `security_id`, `observed_ticker`, `prediction_date` | Kimlik ve skor anı; feature değildir |
| `model_version`, `fold_id` | `<experiment_id>_fold_NNN` ve kaynak test fold'u |
| `probability_up_5pct` | Ham `LGBMClassifier.predict_proba(X)[:,1]` skoru |
| `predicted_class_default_threshold` | `probability_up_5pct >= 0.50` |
| `daily_rank` | Tarih içinde skor azalan, `security_id` artan deterministik sıra |
| `prediction_eligible`, `prediction_exclusion_reason` | D030 evren sonucu/audit alanı |
| `label`, `label_status` | Mevcutsa gerçekleşen sonuç; rankı değiştirmez, geçersizse metrikten çıkarılır |
| `feature_snapshot_id`, `label_snapshot_id` | OOS provenance bağları |

Daily Precision@K tarih satırı `requested_k`, `effective_k`, `selected_count`, `valid_label_count`, `positive_count`, `precision_at_k` ve `label_coverage_at_k` alanlarını taşır. Önce seçim yapılır; seçilmiş `NA` label yerine alt ranktan satır alınmaz.

`models/lightgbm/<experiment_id>/metadata.json` ve fold metadata'sı model/fold sürümü, UTC eğitim zamanı, as-of/dönem sınırları, son kullanılabilir label tarihi, feature/label snapshot ID ve checksum'ları, aktif evren snapshot ID/checksum/sürüm/as-of alanları, feature katalog checksum'u, sıralı 32 feature, effective LightGBM parametreleri, random seed, kod commit SHA, satır/sınıf oranları, fold tanımları, train/validation/OOS metrikleri ve `training_fingerprint` alanlarını saklar. Fingerprint kod SHA + config checksum + feature/label snapshot checksum'ları + aktif evren kimliği/checksum/sürüm/as-of + katalog checksum + fold tanımları + seed bağlamıdır. Artifact klasörü atomik ve değişmezdir; aynı tamamlanmış fingerprint mevcut experiment'ı döndürür.

## D036 İş Yatırım Empty-Range Coverage Cache Alanları

`.cache/market_data/isyatirim/v2_<TICKER>_<START>_<END>.json`, HTTP 200 ve doğrulanmış `value=[]` cevabının operational coverage kaydıdır. Raw/training snapshot değildir; snapshot manifest veya revision log'a girmez ve `FAILED/CORRUPT` snapshot sayılmaz.

| Alan | Anlam | Doğrulama/kullanım |
| --- | --- | --- |
| `ticker` | Gerçekte sorgulanan provider ticker | Resume request kimliği; otomatik alias değildir |
| `start_date`, `end_date` | Inclusive doğrulanmış boş tarih aralığı | Coverage overlap/gap hesabına katılır; alt 6/3 aylık split üretilmez |
| `result` | Sabit `NO_DATA_IN_RANGE` | Retry veya security failure değildir |
| `fetch_timestamp` | Provider cevabının UTC alım zamanı | Audit/provenance; model feature'ı değildir |
| `schema_validation` | HTTP/JSON/value sözleşmesinin `PASS` ayrıntıları | `value` mevcut, list ve boş olmalıdır |
| `cache_schema_version` | `v2` | Eski `v1` dolu kayıtlar geriye uyumlu okunur; silinmez |
| `checksum` | `checksum` alanı hariç canonical metadata SHA-256 | Uyuşmazlıkta cache kullanılmaz ve aralık yeniden sorgulanır |

Dolu v2 cache kaydı ayrıca `result=DATA_IN_RANGE`, column/row count, data filename ve data SHA-256 taşır. Empty-range kaydının CSV/data dosyası yoktur. `--refresh` cache coverage'ını bypass eder. Provider dolu cevap verip bütün tarihler istenen aralığın dışında kalırsa empty sayılmaz; kalıcı schema/date consistency hatasıdır.

## Tam Tarihsel Zincir Operasyon ve Feasibility Raporları

`reports/full_history/collection_status.csv` her master security için tek satır taşır. Provider dönemleri birden fazlaysa ID/ticker alanları `|` ile sıralı birleştirilir; ayrıntılı dönemler bağlayıcı manifestte kalır.

| Alan | Anlam |
| --- | --- |
| `security_id`, `current_ticker` | D034 master kimliği ve as-of ticker |
| `provider_tickers_queried` | Tamamlanan manifest satırlarında sorgulanan gerçek provider ticker'ları |
| `requested_start_date`, `requested_end_date` | Security'nin bağlayıcı manifest kapsamı |
| `isyatirim_status`, `yfinance_status`, `nominal_status` | Security dönemlerinin ayrı provider durumu; İş Yatırım tam boş coverage için ayrıca `NO_DATA_IN_RANGE`, diğer sonuçlarda `PENDING/COMPLETE/PARTIAL/FAILED` |
| `status` | İki tur sonundaki security sınıfı: `COMPLETE`, `PARTIAL`, `FAILED`, `NO_HISTORY`; bitmiş koşuda `PENDING/UNATTEMPTED` kalamaz |
| `raw_snapshot_ids`, `nominal_snapshot_id` | Fiziksel olarak doğrulanmış değişmez kaynak/nominal ID'leri |
| `identity_snapshot_id`, `clean_snapshot_id`, `label_snapshot_id` | Derived zincir tamamlandıysa security kapsamını taşıyan batch snapshot'ları |
| `first_observed_date`, `last_observed_date`, `observed_session_count` | Provider gözlem kapsamı |
| `missing_session_count`, `longest_internal_gap_sessions` | Doğrulanmış global takvime göre eksik toplam ve en uzun iç boşluk |
| `collection_complete` | Bütün manifest dönemlerinde iki raw provider ve nominal zincirinin doğrulanmış `COMPLETE` olması |
| `failure_stage`, `failure_class`, `failure_reason`, `last_successful_stage` | Son başarısız aşama, hassas değerleri redakte edilmiş exception bilgisi ve kesinti öncesi son başarılı aşama |
| `retry_recommended`, `last_collection_pass` | Hatanın ikinci tur için retry-edilebilirliği ve security'nin son işlendiği tur (`1` veya `2`) |
| `elapsed_seconds`, `security_budget_seconds` | Security İş Yatırım zincirinde `time.monotonic()` ile ölçülen geçen süre ve ilgili turun toplam bütçesi |
| `network_request_count`, `cache_hit_count`, `retry_count`, `timeout_count` | Son security sonucunun provider/cache telemetri sayaçları |
| `mapping_review_required` | Geç/erken seri, iç boşluk, provider kapsam farkı veya provider hatası nedeniyle resmî inceleme gereği |

`collection_gaps.csv`, her unresolved provider/tarih aralığını ayrı satırda `security_id`, ticker, provider, collection pass, durum, eksik başlangıç/bitiş, failure stage/class/reason, son başarılı aşama, retry önerisi, elapsed/budget ve request/cache/retry/timeout sayaçlarıyla taşır. Bütçe kesintisinde hem aktif hata aralığı hem de henüz request başlatılmamış sonraki aralıklar `TIME_BUDGET_EXCEEDED` olarak eksiksiz yazılır; doğrulanmış cache kapsamı gap sayılmaz. `collection_failures.csv` tamamen başarısız veya `NO_HISTORY` securities'i partial aralıklardan ayırır. `ticker_mapping_review.csv` açıklanamayan seri başlangıcı/bitişi/iç boşlukları için `OFFICIAL_EVIDENCE_REQUIRED` üretir; alias önermez.

`collection_outcomes.json`, processler arası gerçek resume için yeni yazımlarda `full_history_manifest_outcomes_v2_compact` şemasını kullanır. Bağlam alanları aktif evren snapshot ID, manifest checksum ve mapping checksum'dur. `latest_outcomes` her manifest satırının son sonucunu; `attempt_history` ise first/retry pass geçmişini, provider durumlarını, snapshot ID'lerini, gerçek gap aralıklarını, hata/telemetri alanlarını ve collection pass numarasını saklar. D036 sonuçları ayrıca `empty_range_count`, `empty_range_cache_hit_count` ve yalnız operasyonel `operational_hint_date` taşıyabilir. v2 compact tekrar eden `isyatirim_dates` ve `yfinance_dates` dizilerini dosyada taşımaz; bunlar resume sırasında yalnız fiziksel checksum doğrulamasından geçen immutable raw snapshot'lardan yeniden oluşturulur. Snapshot bulunmayan doğrulanmış empty coverage için tarih dizisi boş kalır ve coverage cache ayrı doğrulanır. Eski `full_history_manifest_outcomes_v1` dosyaları geriye uyumlu okunur, tarih dizileri korunur ve sessizce silinmez. Dosya her coordinator security commit'inde atomik değiştirilir. Eski status/summary/provenance checkpoint'i yalnız tek manifest dönemli security satırlarında fail-closed doğrulamayla migrate edilebilir; COMPLETE olarak geri yüklenen her snapshot fiziksel checksum kontrolünden geçmelidir.

`collection_summary.json` master/attempted/complete/partial/failed/no-history/unattempted sayılarını; İş Yatırım raw, yFinance raw ve nominal başarı oranlarını; first-pass complete, retry attempted/recovered ve retry sonrası remaining partial/failed sayaçlarını verir. Provider oranlarının denominator'ı `attempted_security_count` olup `PENDING/UNATTEMPTED` securities dahil edilmez. `run_provenance.json`; iki turun başlangıç/bitiş zamanlarını, `1200/1800` varsayılan veya CLI ile verilen bütçeleri, first-pass sonucunu, retry/recovered/remaining listelerini, hata geçmişini, kullanılan/dışlanan security listelerini ve her snapshot için ID/checksum/input IDs/row count/status/source/layer/used-security-count alanlarını taşır. `collection_configuration`; security worker sayısı, global İş Yatırım concurrency/interval, tek-writer/deterministik commit, empty cache schema/migration ve yFinance first-observation hint'in kapsam daraltmadığı bilgisini kaydeder. İş Yatırım telemetrisindeki `full_range_requests`, ilk tam-kapsam denemelerini; `split_to_year_count`, yalnız gerçek transient hata sonrasında 12 aylık fallback'e geçişi ifade eder. `PARTIAL`, kesilmiş veya derived zinciri tamamlanmamış koşu `experiment_ready=false` kalır.

`ticker_mapping_review.csv` geç başlangıç, erken bitiş, her uzunluktaki iç oturum boşluğu, provider kapsam uyuşmazlığı, symbol/redirect, iki sağlayıcıda tarihçe yokluğu ve olası ticker geçiş sinyalini raporlar. `possible_historical_ticker` yalnız resmî kanıtla doldurulabilir; orchestration alias tahmin etmez ve ana mapping CSV'sini değiştirmez.

Kalite/prediction raporları `data_quality_summary.json`, `data_quality_by_security.csv`, `feature_quality.csv`, `class_distribution.json`, `prediction_universe_daily.csv` ve `prediction_universe_exclusions.csv` dosyalarıdır. Duplicate `security_id+date` veya duplicate feature key derived üretimi fail-closed durdurur. Prediction exclusion raporu her global oturum için D030'un yedi bağlayıcı nedenini sıfır sayılar dahil ayrı tutar.

`fold_feasibility.csv` her global aday ilk test tarihinde fit/purge/validation/test oturumlarını, gerçek row/sınıf sayılarını, 2020–2021 kapsamını ve üretilebilecek tam fold sayısını taşır. `feasible=true` yalnız 20 warm-up, en az 252 kullanılabilir fit label oturumu, 60 validation takvim/57 kullanılabilir validation label oturumu, 20 tam test oturumu, fit+validation iki sınıf ve üç splitin boş olmamasıyla verilir. Rapor LightGBM çağırmaz ve ilk test tarihini bağlayıcı karara dönüştürmez.
