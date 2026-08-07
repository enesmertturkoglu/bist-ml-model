# bist-ml-model

## Amaç

BİST hisselerini, T+1 açılışından sonraki üç BİST işlem günü içinde uygulanabilir `%5` hedef fiyatına ulaşma olasılığına göre LightGBM ile tahmin edip sıralayan bir karar destek sistemi geliştirmek.

## Mevcut durum

Veri toplama ve değişmez snapshot, temizleme ve uygunluk, üç işlem günlük label, security identity/tarih-etkin ticker mapping, doğrulanmış XU100, global BİST takvimi, tam 32 `baseline_v1` feature pipeline'ı ve leakage-safe LightGBM expanding walk-forward eğitim/artifact altyapısı tamamlandı. Resmî kaynaklı `bist_active_universe_v1`, `2026-07-29` as-of tarihinde 621 security ile donduruldu. İlk gerçek model deneyi henüz çalıştırılmadı.

`scripts/run_full_history_pipeline.py` iki turlu, security-geneli süre bütçeli, empty-range cache'li ve tek-yazarlı atomik checkpoint kullanan resumable orchestration olarak hazırdır. HTTP 200 `{"value":[]}` `NO_DATA_IN_RANGE` olur ve retry/split üretmez. İş Yatırım cache dışı dönemi önce tek tam-aralık request ile sorgular; yalnız gerçek transient hata sürerse 12/6/3 aylık fallback'e geçer. Varsayılan üç kayan security worker process-geneli en fazla iki eşzamanlı İş Yatırım request'i kullanır; coordinator manifest sırasında commit eder. Production iki turu tamamlamıştır: 621/621 security denendi; 615 COMPLETE, 2 PARTIAL, 4 NO_HISTORY ve 0 UNATTEMPTED. Aynı komut, doğrulanmış snapshot/cache kapsamını provider'a yeniden sormadan derived zinciri güvenle yeniden üretmek için kullanılabilir:

```powershell
python -u scripts/run_full_history_pipeline.py `
  --security-workers 3 `
  --isyatirim-max-concurrency 2
```

Tek worker güvenli fallback'i `--security-workers 1` seçeneğidir. `--refresh` yalnız bilinçli yeniden sorgulama için kullanılır; normal resume komutunda verilmez.

Derived identity/clean/label/takvim/XU100/exact-32-feature zinciri 615 COMPLETE security ile üretildi ve fiziksel checksum doğrulamasından geçti. İki PARTIAL ile dört NO_HISTORY fail-closed dışlandığı için `experiment_ready=false` kalır ve gerçek LightGBM performans deneyine henüz geçilmez.

## Veri akışı

```text
raw snapshots
→ official active-universe snapshot
→ nominal/identity
→ cleaning
→ labels
→ global calendar + validated XU100
→ baseline_v1 features
→ prediction universe + training dataset
→ LightGBM walk-forward folds + immutable artifacts
```

## Ana belgeler

- `PROJECT_BRIEF.md`
- `PROJECT_STATUS.md`
- `DECISIONS.md`
- `DATA_DICTIONARY.md`
- `FEATURE_CATALOG.md`
- `SECURITY_MAPPING_AND_TRAINING_DATA.md`
- `AGENTS.md`

## Bağımlılıklar ve test

Doğrulanmış çalışma zamanı bağımlılıkları `requirements.txt`, test bağımlılıkları
ise `requirements-dev.txt` içinde tam sürümleriyle sabitlenmiştir.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Aktif evren komutları

```powershell
python scripts/build_active_bist_universe.py --as-of-date 2026-07-29 --report-dir reports/universe
python scripts/validate_active_bist_universe.py --snapshot-id <ACTIVE_UNIVERSE_SNAPSHOT_ID>
python scripts/build_history_collection_manifest.py --active-universe-snapshot-id <ACTIVE_UNIVERSE_SNAPSHOT_ID> --start-date 2020-03-13 --end-date 2026-07-29 --output reports/universe/full_history_collection_manifest_v1.csv
```

## Sıradaki aşama

- LYDHO ve LRSHO için kalan provider/mapping boşluklarını incelemek
- Fold feasibility raporundaki `2021-07-16` önerisini değerlendirip ilk gerçek test tarihini ayrı kararla kesinleştirmek
- Ancak tam kapsam veya açık kullanıcı kararı sonrasında ilk gerçek LightGBM walk-forward deneyine geçmek
