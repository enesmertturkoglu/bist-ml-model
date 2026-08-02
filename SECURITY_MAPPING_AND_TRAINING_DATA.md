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
python -u scripts/run_full_history_pipeline.py
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
```

Birinci tur bütün master securities'i sıralı işler. İş Yatırım için security-geneli bütçe bütün recursive `12→6→3` aylık chunk ve beş retry zincirini kapsar; her alt chunkta sıfırlanmaz. Bütçe dolduğunda yeni request/retry başlamaz ve `TIME_BUDGET_EXCEEDED` kaydedilir; devam eden request kendi timeout sınırına kadar tamamlanabilir. İş Yatırım başarısız olsa bile yFinance çalışır. Her security sonrasında `reports/full_history/collection_status.csv`, `collection_summary.json`, `run_provenance.json`, `collection_gaps.csv` ve `collection_failures.csv` atomik dosya değişimiyle yenilenir.

Satır düzeyi resume kaydı ayrıca `reports/full_history/collection_outcomes.json` içinde latest manifest outcome ve first/retry attempt history olarak atomik tutulur. Yeniden başlatılan process, status/summary/provenance bağlamını aktif evren, manifest ve mapping checksum'larıyla fail-closed doğrular; COMPLETE snapshot'ların fiziksel kullanılabilirliğini tekrar kontrol eder ve first pass'te ilk `UNATTEMPTED` security'den devam eder. Retry sonucu checkpoint edilmiş satıra üçüncü otomatik provider denemesi yapılmaz.

İkinci tur yalnız first-pass `PARTIAL`, retry-edilebilir provider hatalı `FAILED` ve `TIME_BUDGET_EXCEEDED` securities'i işler. `COMPLETE` snapshot'lar ve başarılı İş Yatırım cache parçaları yeniden indirilmez; yalnız unresolved provider/tarih aralıkları istenir. Permanent schema/mapping hataları ve `NO_HISTORY` otomatik retry edilmez; üçüncü otomatik tur yoktur. Bütçeler gerektiğinde açık CLI argümanlarıyla değiştirilebilir:

```powershell
python -u scripts/run_full_history_pipeline.py `
  --first-pass-security-budget-seconds 1200 `
  --retry-pass-security-budget-seconds 1800
```

Kesilmiş koşuda aynı komut yeniden çalıştırılır; fiziksel bütünlükten geçen `COMPLETE` raw/nominal snapshot'lar provider'a yeniden sorulmaz ve başarılı chunk cache'leri korunur. Başarılı snapshot'ı bilinçli yeniden indirmek için yalnız birinci turda açıkça `--refresh` gerekir; ikinci tur doğrulanmış başarıları hiçbir koşulda yenilemez.

Yalnız preflight çalıştırmak için:

```powershell
python scripts/run_full_history_pipeline.py --preflight-only
```

Üretim komutu security/provider düzeyinde sıralıdır; paralel/agresif provider isteği veya sessiz veri kaynağı fallback'i yoktur. İki tur bitmeden derived zincir başlamaz ve bitmiş collection'da bütün 621 securities `COMPLETE/PARTIAL/FAILED/NO_HISTORY` sınıflarından birindedir. Derived zincire yalnız checksum doğrulamasından geçen `COMPLETE` securities girer; kapsam 621'den küçükse `experiment_ready=false` kalır.

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
