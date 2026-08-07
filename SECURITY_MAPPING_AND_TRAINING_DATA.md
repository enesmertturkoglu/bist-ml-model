## 1. Security mapping nedir?

`security_id`, bir şirket payını ticker değişse bile aynı tarihsel seri altında tutan kalıcı kimliktir. Provider'dan görülen gerçek kod `observed_ticker` olarak korunur; geçmiş kod güncel kodla değiştirilmez. Mapping dosyasında bulunmayan ticker otomatik ve deterministik kimlikle yeni security kabul edilir, veri akışı durmaz.

`baseline_v1` rolling feature hesapları `ticker` yerine `security_id` ile gruplanır. `current_ticker`, mapping durumu, geçiş tarihleri ve kaynak bilgileri feature değildir.

## 2. Mapping dosyası nasıl güncellenir?

Dosya: `reference_data/bist_security_ticker_map_v1.csv`

```csv
security_id,ticker,valid_from,valid_to,is_current_ticker,mapping_status
SEC_001,ESKI,2020-03-13,2024-05-10,false,CONFIRMED
SEC_001,YENI,2024-05-11,,true,CONFIRMED
```

Gerçek CSV'deki resmî kaynak alanları da doldurulmalıdır. Eski ve yeni ticker aynı `security_id` değerini almalı; geçiş aralıkları çakışmamalıdır. Eski ticker'ın son, yeni ticker'ın ilk geçerli günü yazılmalı ve resmî duyuru bağlantısı referans alanına eklenmelidir. ISIN kullanılmıyor. Kod dış kaynaktan kendi başına eşleme kararı üretmez.

## 3. Yeni eğitim verisi nasıl çekilir?

Aktif evren ve mapping V1 dondurulmuştur. Resmî kaynaklı `bist_active_universe_v1`, exact `2026-07-29` tarihinde 621 security içerir. V1 kaynaklarında resmî tarihsel alias kanıtı bulunmadığından ana mapping CSV'si boş kalmıştır; bu durum veri akışını durdurmaz ve güncel ticker `AUTO_NEW_TICKER` olarak planlanır. Alias benzerlikten türetilmez; `reports/universe/ticker_mapping_review_v1.csv` içindeki `NO_HISTORICAL_TICKER_FOUND` satırları ana mapping'e aktarılmaz. Bu inceleme durumu, ilgili payın hiç ticker değiştirmediğinin başarıyla doğrulandığı anlamına gelmez. Tam tarihsel veri toplama sırasında açıklanamayan seri başlangıcı, bitişi veya boşluğu görülürse ayrı resmî mapping incelemesi açılır; alias ancak eski/yeni ticker ve geçiş tarihleri KAP veya Borsa İstanbul kanıtıyla doğrulandıktan sonra ana mapping'e eklenir.

```powershell
python scripts/build_active_bist_universe.py `
  --as-of-date <YYYY-MM-DD> `
  --report-dir reports/universe

python scripts/validate_active_bist_universe.py `
  --snapshot-id <ACTIVE_UNIVERSE_SNAPSHOT_ID>

python scripts/build_history_collection_manifest.py `
  --active-universe-snapshot-id <ACTIVE_UNIVERSE_SNAPSHOT_ID> `
  --start-date 2020-03-13 `
  --end-date <AS_OF_DATE> `
  --output reports/universe/full_history_collection_manifest_v1.csv
```

Ardından manifestteki ticker/dönemler için mevcut aşamalar şu komutlarla çalıştırılır:

```powershell
python scripts/collect_market_data.py THYAO --start-date 2020-03-13 --end-date <AS_OF_DATE>
python scripts/resolve_security_identity.py --nominal-snapshot-id <NOMINAL_SNAPSHOT_ID>
python scripts/clean_market_data.py --snapshot-set THYAO,<IS_RAW_ID>,<YF_RAW_ID>,<YF_NOMINAL_ID> --security-identity-snapshot-id <IDENTITY_SNAPSHOT_ID>
python scripts/generate_labels.py --clean-snapshot-id <CLEAN_SNAPSHOT_ID>
python scripts/build_global_calendar.py --isyatirim-raw-snapshot-id <IS_RAW_ID> --report reports/global_calendar.json
python scripts/collect_xu100.py --start-date 2020-03-13 --end-date <AS_OF_DATE> --global-calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> --report reports/xu100_validation.json
python scripts/generate_features.py --yfinance-raw-snapshot-id <YF_RAW_ID> --isyatirim-raw-snapshot-id <IS_RAW_ID> --identity-snapshot-id <IDENTITY_SNAPSHOT_ID> --xu100-snapshot-id <XU100_SNAPSHOT_ID> --calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> --quality-report reports/baseline_v1_quality.csv
python scripts/validate_feature_snapshot.py --snapshot-id <FEATURE_SNAPSHOT_ID>
```

Birden fazla eski/güncel ticker için `--nominal-snapshot-id`, `--snapshot-set`, `--isyatirim-raw-snapshot-id` ve `--yfinance-raw-snapshot-id` seçenekleri tekrarlanır. END_* kabul çapraz kontrolü istenirse `collect_xu100.py` komutuna en az 20 adet `--isyatirim-stock-snapshot-id` eklenir. Identity snapshot'taki mapping checksum'u clean, label ve feature metadata'sına taşınır.

D030 prediction universe, ana aktif pay listesini `security_id` üzerinden uygular; tarih-etkin identity satırı gerçek provider ticker'ını ve yFinance nominal OHLC'yi sağlar. Feature ve label birleşimi yalnız `security_id + prediction_date` one-to-one anahtarıyla yapılır.

Aktif evren ve mapping V1 artık dondurulmuştur. Gerçek eğitimin kalan ön koşulları `2020-03-13` sonrası tam raw, identity, clean, label, XU100 ve `baseline_v1` feature snapshot zinciri; sınıf dağılımı/fold feasibility raporu ve ilk gerçek test tarihinin ayrı kararla kesinleştirilmesidir. Bu ön koşullar tamamlanmadan gerçek LightGBM performans deneyi çalıştırılmamalıdır. Hazır snapshot zincirinden sonra komut şablonu şöyledir:

```powershell
python scripts/train_lightgbm.py `
  --yfinance-raw-snapshot-id <YF_RAW_ID> `
  --isyatirim-raw-snapshot-id <IS_RAW_ID> `
  --identity-snapshot-id <IDENTITY_SNAPSHOT_ID> `
  --active-universe-snapshot-id <ACTIVE_UNIVERSE_SNAPSHOT_ID> `
  --feature-snapshot-id <FEATURE_SNAPSHOT_ID> `
  --label-snapshot-id <LABEL_SNAPSHOT_ID> `
  --xu100-snapshot-id <XU100_SNAPSHOT_ID> `
  --calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> `
  --as-of-date <AS_OF_DATE> `
  --first-test-start-date <AYRI_KARARLA_KESINLESTIRILMIS_TARIH>
```

Her eski/güncel ticker için iki raw snapshot seçeneği tekrarlanır. Komut yalnız doğrulanmış `COMPLETE` snapshot'ları kabul eder; feature katalog checksum'u, label/feature checksum'ları, aktif evren snapshot ID/checksum/sürüm/as-of alanları, config, kod SHA, fold tanımları ve seed'i fingerprint'e bağlar. Identity snapshot master evren yerine kullanılamaz. Aynı tamamlanmış fingerprint yeni klasör açmadan mevcut artifact'ı döndürür.

## 3.1 Tam manifest koşusu ve resume

Dondurulmuş V1 bağlamının tek orchestration komutu:

```powershell
python -u scripts/run_full_history_pipeline.py `
  --security-workers 3 `
  --isyatirim-max-concurrency 2
```

Komut varsayılan olarak aşağıdaki değerleri fail-closed doğrular ve değiştirmez:

```text
active_universe_snapshot_id = snap_fb0011eaecf3b4b7_r0002_112665b37839
universe_version = bist_active_universe_v1
active_universe_as_of_date = 2026-07-29
master_security_count = 621
collection_start_date = 2020-03-13
collection_end_date = 2026-07-29
first_pass_security_budget_seconds = 1200
retry_pass_security_budget_seconds = 1800
security_worker_count = 3
isyatirim_max_concurrency = 2
global_request_interval_seconds = 1.0
```

Birinci tur bütün master securities'i manifest sırasında tek task olarak kuyruğa alır. Üç worker yalnız provider sorgusu, parsing, DataFrame hazırlığı ve telemetri/hata sonucu üretir. İş Yatırım cache tarafından kapsanmayan dönemi önce tek tam-aralık request ile sorgular. Yalnız timeout, ConnectionError, 429 veya retry-edilebilir 5xx gibi gerçek transient hata bounded retry sonrasında sürerse `tam aralık → 12 → 6 → 3 ay` fallback'i çalışır; security-geneli bütçe bütün zinciri kapsar ve alt parçalarda sıfırlanmaz. HTTP 200, JSON object ve list tipindeki boş `value` doğrudan `NO_DATA_IN_RANGE` olur; retry/split/bütçe patlaması üretmez ve doğrulanmış coverage cache'ine yazılır. İş Yatırım başarısız olsa bile yFinance çalışır.

Process genelindeki semaphore eşzamanlı İş Yatırım request sayısını `2` ile sınırlar ve global request interval worker'lar arasında ortaktır. Sabit üçlü batch bariyeri yoktur: bir worker tamamlanınca sıradaki security boşalan slota alınır. Worker snapshot manifest/revision veya full-history raporlarına yazmaz. Tek coordinator sonuçları completion sırasından bağımsız olarak manifest/security sırasında snapshot'a ve `reports/full_history/collection_status.csv`, `collection_summary.json`, `run_provenance.json`, `collection_gaps.csv`, `collection_failures.csv`, `collection_outcomes.json` checkpoint'lerine atomik olarak yazar.

yFinance ilk gözlem tarihi yalnız provenance'a yazılan operasyonel sinyaldir. Tam-aralık İş Yatırım isteğinin başlangıç/bitişini değiştirmez ve önceki dönemlerin hiçbiri atlanmaz; doğrulanmış boş cevaplar `NO_DATA_IN_RANGE` coverage olur. Provider başlangıçları açıklanamayacak ölçüde farklıysa mevcut `ticker_mapping_review.csv` akışı resmî kanıt ister; mapping CSV otomatik değiştirilmez. yFinance çağrıları per-security kalır; multi-ticker batch gerçek checksum eşdeğerliği kanıtlanmadığı için production yolunda kullanılmaz.

Satır düzeyi resume kaydı ayrıca `reports/full_history/collection_outcomes.json` içinde latest manifest outcome ve first/retry attempt history olarak atomik tutulur. Yeni compact v2 şeması tekrar eden tarih dizilerini yazmaz; resume bunları checksum doğrulamalı immutable snapshot'lardan yeniden kurar ve eski v1 outcome checkpoint'ini geriye uyumlu okur. Yeniden başlatılan process, status/summary/provenance bağlamını aktif evren, manifest ve mapping checksum'larıyla fail-closed doğrular; COMPLETE snapshot'ların fiziksel kullanılabilirliğini tekrar kontrol eder ve first pass'te ilk `UNATTEMPTED` security'den devam eder. Retry sonucu checkpoint edilmiş satıra üçüncü otomatik provider denemesi yapılmaz.

İkinci tur yalnız first-pass `PARTIAL`, retry-edilebilir provider hatalı `FAILED` ve `TIME_BUDGET_EXCEEDED` securities'i işler. `COMPLETE` snapshot'lar ve başarılı İş Yatırım cache parçaları yeniden indirilmez; yalnız unresolved provider/tarih aralıkları istenir. Permanent schema/mapping hataları ve `NO_HISTORY` otomatik retry edilmez; üçüncü otomatik tur yoktur. Bütçeler gerektiğinde açık CLI argümanlarıyla değiştirilebilir:

```powershell
python -u scripts/run_full_history_pipeline.py `
  --first-pass-security-budget-seconds 1200 `
  --retry-pass-security-budget-seconds 1800
```

Kesilmiş koşuda aynı komut yeniden çalıştırılır; fiziksel bütünlükten geçen `COMPLETE` raw/nominal snapshot'lar provider'a yeniden sorulmaz ve başarılı dolu/boş cache coverage'ı korunur. Worker fetch'i bitmiş fakat coordinator commit'i tamamlanmamış security yeniden denenebilir ve başarılı checkpoint sayılmaz. Başarılı snapshot veya empty-range coverage'ı bilinçli yeniden indirmek için yalnız birinci turda açıkça `--refresh` gerekir; ikinci tur doğrulanmış başarıları hiçbir koşulda yenilemez. Eski v1 dolu cache kayıtları geriye uyumlu okunur ve sessizce silinmez.

Yalnız preflight çalıştırmak için:

```powershell
python scripts/run_full_history_pipeline.py --preflight-only
```

Üretim komutu security düzeyinde kontrollü paraleldir; İş Yatırım process-geneli concurrency sınırı `2`dir ve sessiz veri kaynağı fallback'i yoktur. First pass bütün securities için bitmeden retry pass başlamaz; aynı security aynı pass içinde iki worker'a verilmez ve üçüncü otomatik pass yoktur. İki tur bitmeden derived zincir başlamaz ve bitmiş collection'da bütün 621 securities `COMPLETE/PARTIAL/FAILED/NO_HISTORY` sınıflarından birindedir. Derived zincire yalnız checksum doğrulamasından geçen `COMPLETE` securities girer; kapsam 621'den küçükse `experiment_ready=false` kalır.

Production iki turu `621 attempted / 615 COMPLETE / 2 PARTIAL / 4 NO_HISTORY / 0 UNATTEMPTED` durumuyla tamamlamıştır. `LYDHO` ve `LRSHO` PARTIAL; `SKYLP`, `MHRGY`, `MIATK` ve `AZTEK` NO_HISTORY kalmıştır. Derived zincir yalnız fiziksel checksum doğrulamasından geçen 615 COMPLETE security ile üretilmiş; bu alt kapsam nedeniyle `experiment_ready=false` tutulmuştur.

Identity revision context'i doğrudan nominal input snapshot ID/checksum'larına, mapping sürüm/checksum'una ve üretim kodu commit SHA'sına bağlıdır. Aynı içerik ve bağlam idempotenttir; input, mapping veya kod bağı değişirse eski snapshot değiştirilmeden yeni revision oluşur. Clean satırlarında yalnız ilgili security'nin İş Yatırım raw, yFinance raw ve yFinance nominal snapshot bağı taşınır; 621-security batch'inin tam lineage'ı satırlara çoğaltılmadan snapshot metadata'sında korunur.

Tam collection tamamlanmadan identity/clean/label/XU100/feature/prediction/fold raporları tam sayılmaz. `ticker_mapping_review.csv` sinyalleri otomatik alias değildir; `NO_HISTORICAL_TICKER_FOUND` da “ticker hiç değişmedi” doğrulaması değildir. Açıklanamayan boşluklar için KAP/Borsa İstanbul kanıtı ayrı incelenir.

`scripts/report_fold_feasibility.py`, gerektiğinde dışa aktarılmış auditable training panel ve global takvim CSV'sinden yalnız feasibility raporunu yeniden üretir; LightGBM çağırmaz:

```powershell
python scripts/report_fold_feasibility.py `
  --training-panel-csv <TRAINING_PANEL_CSV> `
  --global-calendar-csv <GLOBAL_CALENDAR_CSV> `
  --as-of-date 2026-07-29
```

## 4. Mapping güncellenmezse ne olur?

Yeni halka arz yeni security olarak alınır. Kod değiştirmiş fakat mapping'e eklenmemiş pay da geçici olarak yeni security olur ve eski tarihsel seriyle birleşmez. Mapping daha sonra düzeltildiğinde identity, clean, label ve feature snapshot'ları yeniden üretilmeli; model yeni mapping sürümüyle yeniden eğitilmelidir. Eski snapshot'lar değiştirilmez.

## 5. Kontrol listesi

```text
[ ] Eski ticker doğru mu?
[ ] Yeni ticker doğru mu?
[ ] Geçiş tarihi doğru mu?
[ ] Aynı security_id kullanıldı mı?
[ ] Tarih aralıkları çakışıyor mu?
[ ] Resmî kaynak bağlantısı eklendi mi?
[ ] Veri yeniden çekildi mi?
[ ] Clean/label/feature snapshot yeniden üretildi mi?
[ ] Model yeniden eğitildi mi?
```
