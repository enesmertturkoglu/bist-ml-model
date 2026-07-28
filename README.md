# bist-ml-model

## Amaç

BİST hisselerini, T+1 açılışından sonraki üç BİST işlem günü içinde uygulanabilir `%5` hedef fiyatına ulaşma olasılığına göre LightGBM ile tahmin edip sıralayan bir karar destek sistemi geliştirmek.

## Mevcut durum

Veri toplama ve değişmez snapshot, temizleme ve uygunluk, üç işlem günlük label, security identity/tarih-etkin ticker mapping, doğrulanmış XU100, global BİST takvimi, tam 32 `baseline_v1` feature pipeline'ı ve leakage-safe LightGBM expanding walk-forward eğitim/artifact altyapısı tamamlandı. İlk gerçek model deneyi henüz çalıştırılmadı.

## Veri akışı

```text
raw snapshots
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

## Sıradaki aşama

- Tam aktif BİST evreni ve mapping sürümünü dondurmak
- `2020-03-13` sonrası tam snapshot zincirini üretmek
- Sınıf dağılımı/fold feasibility raporundan sonra ilk gerçek test tarihini ayrı kararla kesinleştirmek
