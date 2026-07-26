## 1. Security mapping nedir?

`security_id`, bir şirket payını ticker değişse bile aynı tarihsel seri altında tutan kalıcı kimliktir. Provider'dan görülen gerçek kod `observed_ticker` olarak korunur; geçmiş kod güncel kodla değiştirilmez. Mapping dosyasında bulunmayan ticker otomatik ve deterministik kimlikle yeni security kabul edilir, veri akışı durmaz.

İleride rolling feature hesapları `ticker` yerine `security_id` ile gruplanmalıdır. `current_ticker`, mapping durumu, geçiş tarihleri ve kaynak bilgileri feature değildir.

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
```

Birden fazla eski/güncel ticker için `--nominal-snapshot-id` ve `--snapshot-set` seçenekleri tekrarlanır. Identity snapshot'taki mapping checksum'u clean ve label metadata'sına taşınır. Feature snapshot ve model eğitim komutları henüz oluşturulmadı; bu aşamalar için komut uydurulmamalıdır.

## 4. Mapping güncellenmezse ne olur?

Yeni halka arz yeni security olarak alınır. Kod değiştirmiş fakat mapping'e eklenmemiş pay da geçici olarak yeni security olur ve eski tarihsel seriyle birleşmez. Mapping daha sonra düzeltildiğinde identity, clean, label ve ileride feature snapshot'ları yeniden üretilmeli; model yeni mapping sürümüyle yeniden eğitilmelidir. Eski snapshot'lar değiştirilmez.

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
