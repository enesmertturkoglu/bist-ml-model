# bist-ml-model

## Amaç

BİST hisselerini, T+1 açılışından sonraki üç BİST işlem günü içinde uygulanabilir `%5` hedef fiyatına ulaşma olasılığına göre LightGBM ile tahmin edip sıralayan bir karar destek sistemi geliştirmek.

## Mevcut durum

Veri toplama ve değişmez snapshot, temizleme ve uygunluk, üç işlem günlük label, security identity/tarih-etkin ticker mapping, doğrulanmış XU100, global BİST takvimi ve tam 32 `baseline_v1` feature pipeline'ı tamamlandı. Regresyon paketi `257 passed` sonucunu veriyor.

## Veri akışı

```text
raw snapshots
→ nominal/identity
→ cleaning
→ labels
→ global calendar + validated XU100
→ baseline_v1 features
→ ileride LightGBM
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

- Günlük prediction universe kararını kesinleştirmek
- LightGBM eğitim ve walk-forward altyapısını geliştirmek
