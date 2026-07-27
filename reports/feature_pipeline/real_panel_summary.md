# baseline_v1 Gerçek Panel Kabul Özeti

- Dönem: `2024-01-02`–`2024-02-23`
- Security: `20`
- Global BİST seansı: `39`
- Feature satırı: `780`
- Feature sayısı: `32`
- Duplicate `security_id + prediction_date`: `0`
- Sonsuz değer: `0`
- Genel missing oranı: `%25.9615` (doğal warm-up dahil)
- Son seansta geçerli feature oranı: `%100`

## XU100 timestamp doğrulaması

- İstanbul takvim eşleşmesi: `39/39` (`%100`)
- İstanbul yerel gece yarısı: `%100`
- UTC takvim eşleşmesi: `31/39` (`%79.4872`)
- Legacy `+1 gün` eşleşmesi: `39/39`; yalnız tanısal, ana yöntem değildir
- Kabul edilen kural: `utc_epoch_ms_to_europe_istanbul_calendar_date_v1`

## END_* çapraz kontrolü

- Security: `20`
- Satır: `780`
- `END_ENDEKS_KODU` dağılımı: `1 → 780`; literal `XU100` oranı `%0`
- `END_SEANS` dağılımı: `2 → 780`
- `END_TARIH`–hisse tarihi eşleşmesi: `%100`
- Aynı gün değer ve seans eşitliği: `%100`
- Bağımsız XU100 overlap: `39` gün
- Mutlak fark medyan/maksimum: `0.000160 / 0.000390`

## yFinance çapraz kontrolü

- Sembol: `XU100.IS`
- Overlap: `39/39`; iki yönde eksik gün `0`
- Mutlak fark medyan/maksimum: `0.020511 / 0.049805`
- Relatif fark medyan/maksimum: `0.000002372 / 0.000005402`
- Rol: yalnız tanısal; fallback değildir

## Snapshot'lar

- Global takvim: `snap_e42ff764cc64d9b3_r0002_ad73402528fa`
- XU100 raw: `snap_3b2f221ecd16d4e5_r0002_2d9dd72c4627`
- XU100 validated: `snap_14c275baa535b404_r0002_a8c6a1b90a70`
- Security identity: `snap_383a5cea3a989608_r0001_bf567c7d2348`
- baseline_v1 features: `snap_e3683df176da46de_r0002_87cc72905794`

Kabul verisi mevcut kullanıcı snapshot alanından ayrılmış `data/feature_acceptance` kökünde tutuldu. Test boyunca `END_*` ve yFinance hiçbir zaman ana XU100 kaynağı veya fallback olarak kullanılmadı.
