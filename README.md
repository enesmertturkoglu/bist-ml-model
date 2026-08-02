# bist-ml-model

## Amaç

BİST hisselerini, T+1 açılışından sonraki üç BİST işlem günü içinde uygulanabilir `%5` hedef fiyatına ulaşma olasılığına göre LightGBM ile tahmin edip sıralayan bir karar destek sistemi geliştirmek.

## Mevcut durum

Veri toplama ve değişmez snapshot, temizleme ve uygunluk, üç işlem günlük label, security identity/tarih-etkin ticker mapping, doğrulanmış XU100, global BİST takvimi, tam 32 `baseline_v1` feature pipeline'ı ve leakage-safe LightGBM expanding walk-forward eğitim/artifact altyapısı tamamlandı. Resmî kaynaklı `bist_active_universe_v1`, `2026-07-29` as-of tarihinde 621 security ile donduruldu. İlk gerçek model deneyi henüz çalıştırılmadı.

`scripts/run_full_history_pipeline.py` iki turlu, security-geneli süre bütçeli ve atomik checkpoint'li resumable orchestration olarak hazırdır. Son tutarlı production checkpoint'i 35/621 security'nin denendiğini gösterir: 17 COMPLETE, 14 PARTIAL, 4 NO_HISTORY ve 586 UNATTEMPTED. Sıradaki security MOPAS'tır. Koşuyu checksum doğrulamalı snapshot/cache reuse ile sürdürmek için:

```powershell
python -u scripts/run_full_history_pipeline.py
```

Collection'ın iki turu bitmeden derived zincir tamamlanmış deney verisi sayılmaz, `experiment_ready=true` olamaz ve gerçek LightGBM performans deneyine geçilmez.

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

- Production collection'ı 35/621 checkpoint'inden sürdürüp bütün security'leri denemek
- `2020-03-13` sonrası tam derived snapshot ve veri-kalitesi zincirini üretmek
- Sınıf dağılımı/fold feasibility raporundan sonra ilk gerçek test tarihini ayrı kararla kesinleştirmek
