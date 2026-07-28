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

Aktif ticker listesini güncelledikten ve gerekiyorsa mapping CSV'sini elle doğruladıktan sonra mevcut aşamalar şu komutlarla çalıştırılır:

```powershell
python scripts/collect_market_data.py THYAO --start-date 2020-03-13 --end-date 2026-07-27
python scripts/resolve_security_identity.py --nominal-snapshot-id <NOMINAL_SNAPSHOT_ID>
python scripts/clean_market_data.py --snapshot-set THYAO,<IS_RAW_ID>,<YF_RAW_ID>,<YF_NOMINAL_ID> --security-identity-snapshot-id <IDENTITY_SNAPSHOT_ID>
python scripts/generate_labels.py --clean-snapshot-id <CLEAN_SNAPSHOT_ID>
python scripts/build_global_calendar.py --isyatirim-raw-snapshot-id <IS_RAW_ID> --report reports/global_calendar.json
python scripts/collect_xu100.py --start-date 2020-03-13 --end-date 2026-07-27 --global-calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> --report reports/xu100_validation.json
python scripts/generate_features.py --yfinance-raw-snapshot-id <YF_RAW_ID> --isyatirim-raw-snapshot-id <IS_RAW_ID> --identity-snapshot-id <IDENTITY_SNAPSHOT_ID> --xu100-snapshot-id <XU100_SNAPSHOT_ID> --calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> --quality-report reports/baseline_v1_quality.csv
python scripts/validate_feature_snapshot.py --snapshot-id <FEATURE_SNAPSHOT_ID>
```

Birden fazla eski/güncel ticker için `--nominal-snapshot-id`, `--snapshot-set`, `--isyatirim-raw-snapshot-id` ve `--yfinance-raw-snapshot-id` seçenekleri tekrarlanır. END_* kabul çapraz kontrolü istenirse `collect_xu100.py` komutuna en az 20 adet `--isyatirim-stock-snapshot-id` eklenir. Identity snapshot'taki mapping checksum'u clean, label ve feature metadata'sına taşınır.

D030 prediction universe, ana aktif pay listesini `security_id` üzerinden uygular; tarih-etkin identity satırı gerçek provider ticker'ını ve yFinance nominal OHLC'yi sağlar. Feature ve label birleşimi yalnız `security_id + prediction_date` one-to-one anahtarıyla yapılır.

LightGBM eğitim girişi oluşturulmuştur; ancak tam aktif evren/mapping dondurulmadan ve fold feasibility raporuyla ilk gerçek test tarihi ayrı kararla kesinleşmeden gerçek deney çalıştırılmamalıdır. Hazır snapshot zincirinden sonra komut şablonu şöyledir:

```powershell
python scripts/train_lightgbm.py `
  --yfinance-raw-snapshot-id <YF_RAW_ID> `
  --isyatirim-raw-snapshot-id <IS_RAW_ID> `
  --identity-snapshot-id <IDENTITY_SNAPSHOT_ID> `
  --feature-snapshot-id <FEATURE_SNAPSHOT_ID> `
  --label-snapshot-id <LABEL_SNAPSHOT_ID> `
  --xu100-snapshot-id <XU100_SNAPSHOT_ID> `
  --calendar-snapshot-id <CALENDAR_SNAPSHOT_ID> `
  --as-of-date <AS_OF_DATE> `
  --first-test-start-date <AYRI_KARARLA_KESINLESTIRILMIS_TARIH>
```

Her eski/güncel ticker için iki raw snapshot seçeneği tekrarlanır. Komut yalnız doğrulanmış `COMPLETE` snapshot'ları kabul eder; feature katalog checksum'u, label/feature checksum'ları, config, kod SHA, fold tanımları ve seed'i fingerprint'e bağlar. Aynı tamamlanmış fingerprint yeni klasör açmadan mevcut artifact'ı döndürür.

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
