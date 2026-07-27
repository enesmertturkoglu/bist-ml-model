# FEATURE CATALOG

**Katalog sürümü:** `baseline_v1`

**Tahmin anı:** `prediction_date = T`, BİST seansı kapandıktan ve günlük kaynak snapshot'ları `COMPLETE` olduktan sonra

**Model:** LightGBM Classifier

**Hedef:** `T+1` açılışından sonraki üç BİST işlem günü içinde uygulanabilir `%5` hedef fiyatına ulaşma olasılığı

**Baseline feature sayısı:** `32`

Bu belge feature formüllerini, tahmin anındaki kullanılabilirliği, warm-up ve missing kurallarını ve veri sızıntısı kontrollerini tanımlar. Feature kodu, model eğitimi ve backtest bu belge kapsamında değildir.

## 1. Bağlayıcı hesaplama sözleşmesi

### 1.1 Satır ve kimlik

Her feature satırının tekil anahtarı:

```text
security_id + prediction_date
```

- `security_id` zorunludur.
- Yeni feature pipeline, `security_id` bulunmayan ticker tabanlı eski snapshot'ları sessizce kabul etmez ve açık hata üretir.
- `ticker`, `observed_ticker`, `current_ticker`, mapping durumu, mapping tarihi ve mapping checksum'u model feature'ı değildir.
- Rolling işlemleri yalnız `groupby(security_id)` sınırında yapılır.

### 1.2 Zaman ve BİST takvimi

- `T` gününün open, high, low, close, TL hacmi ve doğrulanmış endeks kapanışı T seansı kapandıktan sonra kullanılabilir.
- `T+1` ve sonrası fiyat/hacim/uygunluk/label alanları feature üretiminde okunamaz.
- Pencereler takvim günü değil global İş Yatırım BİST işlem takvimindeki ardışık oturumlarla tanımlanır.
- Bir security satırı gerekli bir BİST oturumunda eksikse pencere son mevcut satırlara doğru sıkıştırılmaz.
- Eksik oturum forward-fill, back-fill veya sentetik satırla doldurulmaz.
- `ret_n` tam olarak `n` BİST oturumu önceki değeri kullanır; yalnız “n'inci mevcut satır” kullanılmaz.
- Yeni halka arz ve kısa geçmiş doğal warm-up nedeniyle NA üretir; geçmiş geriye doğru doldurulmaz.

### 1.3 Fiyat kaynağı

Feature fiyat sembolleri:

```text
O_t = yf_provider_open[T]
H_t = yf_provider_high[T]
L_t = yf_provider_low[T]
C_t = yf_provider_close[T]
```

Kurallar:

- Fiyat-derived baseline feature'lar yalnız oran, getiri, normalize aralık veya sıralama biçimindedir.
- Mutlak `yf_provider_*` fiyat seviyesi model feature'ı değildir.
- `yf_nominal_*` giriş, label, çıkış ve tavan işlemleri için korunur; baseline feature hesabında kullanılmaz.
- `yf_future_split_factor`, `yf_stock_splits`, gelecekteki action bilgileri veya split tarihleri feature değildir.
- Provider OHLC'nin ölçekten bağımsız formüllerde kullanılması, gelecekteki splitlerin geçmiş pencerenin bütün fiyatlarını aynı katsayıyla yeniden ölçeklemesinden sinyal üretilmesini engellemek içindir.
- Her fiyat feature'ı için pozitif sabit ölçekleme invariance testi bulunmalıdır.
- Aynı formülde provider ve nominal fiyatlar karıştırılamaz.

### 1.4 Hacim kaynağı

```text
V_t = is_tl_volume[T]
```

- Baseline hacim ve likidite feature'larının temel kaynağı İş Yatırım TL işlem hacmidir.
- `yf_share_volume` adet hacmidir; TL hacmiyle aynı alan gibi birleştirilemez.
- İlk baseline'da `yf_share_volume` model feature'ı değildir.
- TL hacim eksik, sonlu değil veya `<= 0` ise ilgili hacim feature'ı NA kalır.
- Hacim feature'ı üretmek için tüm dönem ortalaması veya test dönemi istatistiği kullanılmaz.

### 1.5 Endeks kaynağı

```text
M_t = validated_xu100_close[T]
```

- Ana benchmark `XU100/BIST 100` olarak sabitlenmelidir.
- Endeks serisi ayrı, sürümlü ve doğrulanmış bir snapshot olmalıdır.
- Hisse endpoint'inde yan alan olarak görünen fakat tarih/kimlik doğrulaması tamamlanmamış endeks değeri sessiz fallback olamaz.
- Endeks kapanışı `prediction_date` ile aynı BİST oturumunda eşleşmelidir.
- Eksik endeks günü forward-fill veya başka gün değeriyle doldurulmaz.
- Doğrulanmış XU100 snapshot'ı yoksa market/relative feature pipeline'ı açık hata vermelidir.

### 1.6 Matematiksel kurallar

```text
safe_div(a, b) = a / b, yalnız a ve b sonlu ve b > 0 ise; aksi halde NA
std_ddof1      = örneklem standart sapması, ddof=1
mean/median    = yalnız gerekli pencerenin tüm gözlemleri geçerliyse hesaplanır
log1p(x)       = log(1+x), yalnız x >= 0 ve sonlu ise
```

- Kayan pencere `min_periods`, ilgili feature'ın tam pencere uzunluğuna eşittir.
- Eksik değer imputasyonu yapılmaz; LightGBM'e `NaN` olarak aktarılır.
- Sonsuz değerler `NaN` yapılır ve kalite raporunda sayılır.
- Winsorization, standardization veya tüm veri dönemi normalizasyonu baseline feature üretiminde yapılmaz.

### 1.7 Kesitsel hesaplama

Kesitsel rank:

```text
cs_rank(x_i,t) =
    (average_rank(x_i,t) - 1) / (N_valid,t - 1)
```

Kurallar:

- Grup yalnız `prediction_date` değeridir.
- Tie yöntemi `average`dır.
- NA değerler rank evrenine girmez.
- `N_valid < MIN_CS_SECURITIES` ise ilgili tarihte rank feature'ı bütün securities için NA olur.
- `MIN_CS_SECURITIES = 20`.
- Ranklar feature snapshot'ında label bağlantısından önce hesaplanır.
- `entry_eligible`, `entry_exclusion_reason`, `requires_review`, `target_hit`, `label` veya gelecekteki başka bir filtre rank evrenini belirleyemez.
- Aynı tarihte henüz işlem görmeye başlamamış veya T verisi bulunmayan security doğal olarak rank evrenine girmez.
- İlk sürümün sabit güncel aktif hisse evreni kararı korunur; bu nedenle survivorship bias sonuç yorumunda ayrıca belirtilir.

### 1.8 Yasak model girdileri

Aşağıdaki alanlar feature şemasına giremez:

```text
entry_date'e ait T+1 fiyat/hacim alanları
entry_eligible
entry_exclusion_reason
entry_exclusion_reasons
requires_review
estimated_upper_limit
raw_upper_limit
tick_size / price_step
price_step_resolution_status
is_limit_open / LIMIT_OPEN
corporate_action_window_flag
corporate_action_window_dates
target_price
raw_target_price
target_hit
target_hit_date
label
exit_price
label_status
yf_future_split_factor
yf_stock_splits
yf_dividends
snapshot_id / checksum / revision alanları
ticker_mapping_status
ticker_mapping_rule_id
ticker_mapping_version
ticker_mapping_checksum
current_ticker
ticker değişikliği tarihleri
security_id'nin kendisi
```

`security_id`, `prediction_date` ve lineage alanları yalnız kimlik, join, bölme ve denetim içindir.

## 2. Baseline v1 özet listesi

| Grup | Feature sayısı |
| --- | ---: |
| Fiyat getirisi ve momentum | 6 |
| Trend ve fiyat konumu | 4 |
| Volatilite ve fiyat aralığı | 5 |
| Hacim ve likidite | 5 |
| Mum/gün içi yapı | 3 |
| Sınırlı teknik gösterge | 1 |
| Endeks ve relatif güç | 4 |
| Kesitsel rank | 4 |
| **Toplam** | **32** |

## 3. Baseline v1 tam katalog

### 01. `ret_1`

**feature_name:** ret_1

**feature_group:** price_momentum

**description:** T kapanışının tam 1 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_1[t] = safe_div(C_t, C_(t-1)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 2

**minimum_history:** 2 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 1 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 02. `ret_2`

**feature_name:** ret_2

**feature_group:** price_momentum

**description:** T kapanışının tam 2 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_2[t] = safe_div(C_t, C_(t-2)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 3

**minimum_history:** 3 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(2)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 2 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 03. `ret_3`

**feature_name:** ret_3

**feature_group:** price_momentum

**description:** T kapanışının tam 3 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_3[t] = safe_div(C_t, C_(t-3)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 4

**minimum_history:** 4 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(3)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 3 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 04. `ret_5`

**feature_name:** ret_5

**feature_group:** price_momentum

**description:** T kapanışının tam 5 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_5[t] = safe_div(C_t, C_(t-5)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 6

**minimum_history:** 6 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(5)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 5 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 05. `ret_10`

**feature_name:** ret_10

**feature_group:** price_momentum

**description:** T kapanışının tam 10 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_10[t] = safe_div(C_t, C_(t-10)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 11

**minimum_history:** 11 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(10)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 10 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 06. `ret_20`

**feature_name:** ret_20

**feature_group:** price_momentum

**description:** T kapanışının tam 20 BİST işlem günü önceki kapanışa göre basit getirisi.

**exact_formula**

```text
ret_20[t] = safe_div(C_t, C_(t-20)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 21

**minimum_history:** 21 ardışık BİST oturumunda geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(20)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk 20 geçmiş BİST oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer yükseliş momentumu, negatif değer düşüş veya kısa dönem reversal adayıdır; yön model tarafından öğrenilir.

**data_leakage_risk:** Düşük; yalnız T ve geçmişi kullanır. yf_provider fiyat seviyeleri modele verilmez; formül ölçekten bağımsızdır. Yanlış nominal/provider karışımı ve takvim boşluğunu sıkıştırma testle engellenmelidir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 07. `close_to_sma_5`

**feature_name:** close_to_sma_5

**feature_group:** trend

**description:** Kapanışın son 5 BİST işlem günlük ortalama kapanışa göre konumu.

**exact_formula**

```text
close_to_sma_5[t] = safe_div(C_t, mean(C_(t-4):C_t)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 5

**minimum_history:** 5 ardışık geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** 5 oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer kısa vadeli trendin üzerinde olmayı gösterir.

**data_leakage_risk:** Düşük; T dahildir ve T kapanışında bilinir. Rolling pencere global BİST oturumlarıyla doğrulanmalıdır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 08. `close_to_sma_20`

**feature_name:** close_to_sma_20

**feature_group:** trend

**description:** Kapanışın son 20 BİST işlem günlük ortalama kapanışa göre konumu.

**exact_formula**

```text
close_to_sma_20[t] = safe_div(C_t, mean(C_(t-19):C_t)) - 1
```

**source_columns:** yf_provider_close

**lookback_days:** 20

**minimum_history:** 20 ardışık geçerli close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** 20 oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer orta dönem trendin üzerinde olmayı gösterir.

**data_leakage_risk:** Düşük; T dahildir ve T kapanışında bilinir. Rolling pencere global BİST oturumlarıyla doğrulanmalıdır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 09. `distance_from_high_20`

**feature_name:** distance_from_high_20

**feature_group:** trend

**description:** Kapanışın T dahil son 20 BİST oturumundaki en yüksek fiyata uzaklığı.

**exact_formula**

```text
distance_from_high_20[t] = safe_div(C_t, max(H_(t-19):H_t)) - 1
```

**source_columns:** yf_provider_close, yf_provider_high

**lookback_days:** 20

**minimum_history:** 20 ardışık geçerli high ve T close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** 20 oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** 0'a yakın değer yakın tepe/güç; daha negatif değer tepeden uzaklık gösterir.

**data_leakage_risk:** Düşük; T high kullanılabilir. Gelecekteki high veya T+1 fiyatı kesinlikle kullanılamaz.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 10. `positive_day_ratio_5`

**feature_name:** positive_day_ratio_5

**feature_group:** trend

**description:** Son 5 bir günlük getirinin pozitif olma oranı.

**exact_formula**

```text
positive_day_ratio_5[t] = mean(1(ret_1[j] > 0), j=t-4..t)
```

**source_columns:** yf_provider_close

**lookback_days:** 6

**minimum_history:** 6 ardışık close ile 5 geçerli ret_1

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ile ret_1

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** ret_1 değerlerinden biri NA ise feature NA; sıfır getiri pozitif sayılmaz.

**warmup_rule:** 5 günlük getiri dizisi tamamlanana kadar NA.

**expected_direction_or_interpretation:** 1'e yakın değer süreklilik gösteren yükseliş, 0'a yakın değer düşüş ağırlığıdır.

**data_leakage_risk:** Düşük; yalnız geçmiş günlük yönleri kullanır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 11. `return_volatility_5`

**feature_name:** return_volatility_5

**feature_group:** volatility

**description:** Son 5 bir günlük basit getirinin örneklem standart sapması.

**exact_formula**

```text
return_volatility_5[t] = std_ddof1(ret_1[t-4:t])
```

**source_columns:** yf_provider_close

**lookback_days:** 6

**minimum_history:** 5 geçerli ret_1, yani 6 ardışık close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ile ret_1

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Pencerede herhangi bir ret_1 NA ise NA; imputation yok.

**warmup_rule:** 5 getiri tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer kısa dönem oynaklık ve daha geniş hedef/zarar dağılımı gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş getirileri.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 12. `return_volatility_20`

**feature_name:** return_volatility_20

**feature_group:** volatility

**description:** Son 20 bir günlük basit getirinin örneklem standart sapması.

**exact_formula**

```text
return_volatility_20[t] = std_ddof1(ret_1[t-19:t])
```

**source_columns:** yf_provider_close

**lookback_days:** 21

**minimum_history:** 20 geçerli ret_1, yani 21 ardışık close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ile ret_1

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Pencerede herhangi bir ret_1 NA ise NA; imputation yok.

**warmup_rule:** 20 getiri tamamlanana kadar NA.

**expected_direction_or_interpretation:** Orta dönem risk rejimini temsil eder.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş getirileri.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 13. `volatility_ratio_5_20`

**feature_name:** volatility_ratio_5_20

**feature_group:** volatility

**description:** Kısa dönem getiri volatilitesinin orta dönem volatilitesine oranı.

**exact_formula**

```text
volatility_ratio_5_20[t] = safe_div(return_volatility_5[t], return_volatility_20[t])
```

**source_columns:** return_volatility_5, return_volatility_20

**lookback_days:** 21

**minimum_history:** Her iki volatilite geçerli ve vol_20 > 0

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Payda 0, eksik veya sonlu değilse NA.

**warmup_rule:** return_volatility_20 oluşana kadar NA.

**expected_direction_or_interpretation:** 1'in üzeri volatilite genişlemesi, 1'in altı daralma gösterir.

**data_leakage_risk:** Düşük; iki leakage-güvenli alt feature'ın oranı.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 14. `true_range_pct`

**feature_name:** true_range_pct

**feature_group:** volatility

**description:** T gününün true range değerinin önceki kapanışa oranı.

**exact_formula**

```text
TR_t = max(H_t-L_t, abs(H_t-C_(t-1)), abs(L_t-C_(t-1))); true_range_pct[t] = safe_div(TR_t, C_(t-1))
```

**source_columns:** yf_provider_high, yf_provider_low, yf_provider_close

**lookback_days:** 2

**minimum_history:** T high/low ve T-1 close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk önceki kapanış oluşana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer gün içi ve gap kaynaklı aralığın büyüdüğünü gösterir.

**data_leakage_risk:** Düşük; T high/low kapanış sonrası bilinir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 15. `range_expansion_5_20`

**feature_name:** range_expansion_5_20

**feature_group:** volatility

**description:** Son 5 günlük ortalama true range oranının son 20 günlük ortalamaya oranı.

**exact_formula**

```text
range_expansion_5_20[t] = safe_div(mean(true_range_pct[t-4:t]), mean(true_range_pct[t-19:t]))
```

**source_columns:** true_range_pct

**lookback_days:** 21

**minimum_history:** 20 ardışık geçerli true_range_pct için 21 OHLC oturumu

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** true_range_pct içindeki C.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Alt pencerelerden biri eksik veya 20 günlük ortalama <= 0 ise NA.

**warmup_rule:** 20 true range gözlemi tamamlanana kadar NA.

**expected_direction_or_interpretation:** 1'in üzeri aralık genişlemesi, 1'in altı sıkışma gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş aralıklar.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 16. `log_median_tl_volume_20`

**feature_name:** log_median_tl_volume_20

**feature_group:** volume_liquidity

**description:** Son 20 BİST işlem günündeki medyan TL işlem hacminin log dönüşümü.

**exact_formula**

```text
log_median_tl_volume_20[t] = log1p(median(V_(t-19):V_t))
```

**source_columns:** is_tl_volume

**lookback_days:** 20

**minimum_history:** 20 ardışık pozitif ve sonlu TL hacim

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli pozitif ve sonlu TL hacim gözlemlerinden biri eksikse NA; 0 veya negatif hacim geçerli sayı olarak kullanılmaz; imputation yok.

**warmup_rule:** 20 geçerli hacim oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer daha yüksek tipik TL likiditesi gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş TL hacmi kullanılır. Tüm dönemden hesaplanan normalizasyon veya gelecekteki giriş uygunluğu filtresi yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 17. `tl_volume_ratio_5_20`

**feature_name:** tl_volume_ratio_5_20

**feature_group:** volume_activity

**description:** Son 5 günlük ortalama TL hacmin son 20 günlük ortalama TL hacme oranı.

**exact_formula**

```text
tl_volume_ratio_5_20[t] = safe_div(mean(V_(t-4):V_t), mean(V_(t-19):V_t))
```

**source_columns:** is_tl_volume

**lookback_days:** 20

**minimum_history:** 20 ardışık pozitif ve sonlu TL hacim

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli pozitif ve sonlu TL hacim gözlemlerinden biri eksikse NA; 0 veya negatif hacim geçerli sayı olarak kullanılmaz; imputation yok.

**warmup_rule:** 20 geçerli hacim oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** 1'in üzeri yakın dönem aktivite artışı gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş TL hacmi kullanılır. Tüm dönemden hesaplanan normalizasyon veya gelecekteki giriş uygunluğu filtresi yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 18. `tl_volume_zscore_20`

**feature_name:** tl_volume_zscore_20

**feature_group:** volume_activity

**description:** T gününün log TL hacminin önceki 20 BİST oturumuna göre z-skoru; T referans dağılımına dahil değildir.

**exact_formula**

```text
L_t=log1p(V_t); mu=mean(L_(t-20):L_(t-1)); s=std_ddof1(L_(t-20):L_(t-1)); z=(L_t-mu)/s
```

**source_columns:** is_tl_volume

**lookback_days:** 21

**minimum_history:** T dahil 21 ardışık pozitif hacim ve önceki 20 log hacimde s > 0

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** rolling(20).mean/std ardından shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli pozitif ve sonlu TL hacim gözlemlerinden biri eksikse NA; 0 veya negatif hacim geçerli sayı olarak kullanılmaz; imputation yok. Önceki 20 log hacmin standart sapması 0 ise NA.

**warmup_rule:** 21 hacim oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif yüksek değer olağan dışı hacim artışıdır.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş TL hacmi kullanılır. Tüm dönemden hesaplanan normalizasyon veya gelecekteki giriş uygunluğu filtresi yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 19. `tl_volume_cv_20`

**feature_name:** tl_volume_cv_20

**feature_group:** volume_liquidity

**description:** Son 20 günlük TL hacmin değişim katsayısı.

**exact_formula**

```text
tl_volume_cv_20[t] = safe_div(std_ddof1(V_(t-19):V_t), mean(V_(t-19):V_t))
```

**source_columns:** is_tl_volume

**lookback_days:** 20

**minimum_history:** 20 ardışık pozitif hacim ve ortalama > 0

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli pozitif ve sonlu TL hacim gözlemlerinden biri eksikse NA; 0 veya negatif hacim geçerli sayı olarak kullanılmaz; imputation yok.

**warmup_rule:** 20 geçerli hacim oturumu tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer hacim istikrarsızlığı, düşük değer süreklilik gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş TL hacmi kullanılır. Tüm dönemden hesaplanan normalizasyon veya gelecekteki giriş uygunluğu filtresi yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 20. `amihud_20`

**feature_name:** amihud_20

**feature_group:** volume_liquidity

**description:** Mutlak günlük getiri başına TL hacim fiyat etkisinin 20 günlük log ölçekli ortalaması.

**exact_formula**

```text
amihud_20[t] = log1p(1e9 * mean(abs(ret_1[j]) / V_j, j=t-19..t))
```

**source_columns:** yf_provider_close, is_tl_volume

**lookback_days:** 21

**minimum_history:** 20 geçerli ret_1 ve aynı günlerde 20 pozitif TL hacim

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ile ret_1

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Getiri veya hacim gözlemlerinden biri eksik ya da hacim <= 0 ise NA.

**warmup_rule:** 20 getiri gözlemi tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer daha yüksek fiyat etkisi ve daha düşük likiditeyi gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş veri. TL hacim ile adet hacmi karıştırılmamalıdır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 21. `overnight_gap`

**feature_name:** overnight_gap

**feature_group:** intraday_structure

**description:** T açılışının önceki BİST oturumu kapanışına göre getirisi.

**exact_formula**

```text
overnight_gap[t] = safe_div(O_t, C_(t-1)) - 1
```

**source_columns:** yf_provider_open, yf_provider_close

**lookback_days:** 2

**minimum_history:** T open ve T-1 close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** İlk önceki kapanış oluşana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer gece/ön açılış talebini; negatif değer aşağı gap'i gösterir.

**data_leakage_risk:** Düşük; T açılışı ve önceki kapanış T kapanışında bilinmektedir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 22. `intraday_return`

**feature_name:** intraday_return

**feature_group:** intraday_structure

**description:** T gününün açılıştan kapanışa getirisi.

**exact_formula**

```text
intraday_return[t] = safe_div(C_t, O_t) - 1
```

**source_columns:** yf_provider_open, yf_provider_close

**lookback_days:** 1

**minimum_history:** T open ve close

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Gerekli fiyatlardan biri eksik, sonlu değil veya pozitif değilse NA; forward-fill/back-fill/imputation yok.

**warmup_rule:** Geçerli T open/close yoksa NA.

**expected_direction_or_interpretation:** Pozitif değer gün içi alım baskısını gösterir.

**data_leakage_risk:** Düşük; yalnız T günü kapanmış seans verisi.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 23. `close_location_value`

**feature_name:** close_location_value

**feature_group:** intraday_structure

**description:** Kapanışın günlük high-low aralığındaki sürekli konumu; [-1,1].

**exact_formula**

```text
close_location_value[t] = (2*C_t - H_t - L_t) / (H_t - L_t)
```

**source_columns:** yf_provider_high, yf_provider_low, yf_provider_close

**lookback_days:** 1

**minimum_history:** T high, low ve close; H_t > L_t

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** H_t <= L_t veya gerekli alan eksik/geçersizse NA.

**warmup_rule:** Geçerli T OHLC yoksa NA.

**expected_direction_or_interpretation:** 1'e yakın kapanış gün tepesine, -1'e yakın kapanış gün dibine yakındır.

**data_leakage_risk:** Düşük; isimlendirilmiş mum formasyonu yerine T gününün sürekli yapısını kullanır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 24. `rsi_14_sma`

**feature_name:** rsi_14_sma

**feature_group:** technical_indicator

**description:** Son 14 kapanış değişiminden hesaplanan deterministik basit-ortalama RSI (Cutler tipi).

**exact_formula**

```text
d_j=C_j-C_(j-1); g_j=max(d_j,0); l_j=max(-d_j,0); AG=mean(g_(t-13):g_t); AL=mean(l_(t-13):l_t); RSI=100 if AL=0<AG; 0 if AG=0<AL; 50 if AG=AL=0; else 100-100/(1+AG/AL)
```

**source_columns:** yf_provider_close

**lookback_days:** 15

**minimum_history:** 15 ardışık close ile 14 geçerli değişim

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ile close farkı

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** 14 değişimden biri eksikse NA; özel sıfır-kazanç/kayıp durumları formüldeki gibi deterministik çözülür.

**warmup_rule:** 14 değişim tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer güçlü/olası aşırı alım, düşük değer zayıflık/olası reversal bağlamıdır; yön önceden sabitlenmez.

**data_leakage_risk:** Düşük; kütüphane varsayımına bırakılmayan sabit formül kullanılır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 25. `market_ret_1`

**feature_name:** market_ret_1

**feature_group:** market_relative

**description:** Doğrulanmış XU100 kapanışının bir BİST oturumluk getirisi.

**exact_formula**

```text
market_ret_1[t] = safe_div(M_t, M_(t-1)) - 1
```

**source_columns:** validated_xu100_close joined by prediction_date

**lookback_days:** 2

**minimum_history:** 2 ardışık XU100 kapanışı

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** M.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Hisse veya doğrulanmış XU100 kapanış serisinde gerekli BİST günü eksikse NA; farklı gün eşleştirme, forward-fill ve back-fill yok.

**warmup_rule:** İlk önceki endeks kapanışı oluşana kadar NA.

**expected_direction_or_interpretation:** Piyasanın T günündeki yönünü ve rejimini temsil eder.

**data_leakage_risk:** Orta; endeks günü kesin olarak prediction_date ile eşleşmeli, özel/test dönemi dışı istatistik kullanılmamalı ve endpointte tesadüfen gelen doğrulanmamış seri yerine sürümlü XU100 snapshot'ı kullanılmalıdır.

**live_calculation_feasibility:** HIGH yalnız sürümlü ve doğrulanmış XU100 snapshot'ı hazırsa; aksi halde pipeline açık hata vermelidir.

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 26. `relative_ret_1`

**feature_name:** relative_ret_1

**feature_group:** market_relative

**description:** Hissenin 1 günlük getirisinin XU100 1 günlük getirisinden farkı.

**exact_formula**

```text
relative_ret_1[t] = ret_1[t] - (safe_div(M_t, M_(t-1)) - 1)
```

**source_columns:** yf_provider_close, validated_xu100_close

**lookback_days:** 2

**minimum_history:** Hisse ve XU100 için 2 ardışık geçerli kapanış

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(1) ve M.shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Hisse veya doğrulanmış XU100 kapanış serisinde gerekli BİST günü eksikse NA; farklı gün eşleştirme, forward-fill ve back-fill yok.

**warmup_rule:** 1 geçmiş oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer piyasa üstü relatif güç; negatif değer piyasa altı performanstır.

**data_leakage_risk:** Orta; endeks günü kesin olarak prediction_date ile eşleşmeli, özel/test dönemi dışı istatistik kullanılmamalı ve endpointte tesadüfen gelen doğrulanmamış seri yerine sürümlü XU100 snapshot'ı kullanılmalıdır.

**live_calculation_feasibility:** HIGH yalnız sürümlü ve doğrulanmış XU100 snapshot'ı hazırsa; aksi halde pipeline açık hata vermelidir.

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 27. `relative_ret_5`

**feature_name:** relative_ret_5

**feature_group:** market_relative

**description:** Hissenin 5 günlük getirisinin XU100 5 günlük getirisinden farkı.

**exact_formula**

```text
relative_ret_5[t] = ret_5[t] - (safe_div(M_t, M_(t-5)) - 1)
```

**source_columns:** yf_provider_close, validated_xu100_close

**lookback_days:** 6

**minimum_history:** Hisse ve XU100 için 6 ardışık geçerli kapanış

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(5) ve M.shift(5)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Hisse veya doğrulanmış XU100 kapanış serisinde gerekli BİST günü eksikse NA; farklı gün eşleştirme, forward-fill ve back-fill yok.

**warmup_rule:** 5 geçmiş oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer piyasa üstü relatif güç; negatif değer piyasa altı performanstır.

**data_leakage_risk:** Orta; endeks günü kesin olarak prediction_date ile eşleşmeli, özel/test dönemi dışı istatistik kullanılmamalı ve endpointte tesadüfen gelen doğrulanmamış seri yerine sürümlü XU100 snapshot'ı kullanılmalıdır.

**live_calculation_feasibility:** HIGH yalnız sürümlü ve doğrulanmış XU100 snapshot'ı hazırsa; aksi halde pipeline açık hata vermelidir.

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 28. `relative_ret_20`

**feature_name:** relative_ret_20

**feature_group:** market_relative

**description:** Hissenin 20 günlük getirisinin XU100 20 günlük getirisinden farkı.

**exact_formula**

```text
relative_ret_20[t] = ret_20[t] - (safe_div(M_t, M_(t-20)) - 1)
```

**source_columns:** yf_provider_close, validated_xu100_close

**lookback_days:** 21

**minimum_history:** Hisse ve XU100 için 21 ardışık geçerli kapanış

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** C.shift(20) ve M.shift(20)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Hisse veya doğrulanmış XU100 kapanış serisinde gerekli BİST günü eksikse NA; farklı gün eşleştirme, forward-fill ve back-fill yok.

**warmup_rule:** 20 geçmiş oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer piyasa üstü relatif güç; negatif değer piyasa altı performanstır.

**data_leakage_risk:** Orta; endeks günü kesin olarak prediction_date ile eşleşmeli, özel/test dönemi dışı istatistik kullanılmamalı ve endpointte tesadüfen gelen doğrulanmamış seri yerine sürümlü XU100 snapshot'ı kullanılmalıdır.

**live_calculation_feasibility:** HIGH yalnız sürümlü ve doğrulanmış XU100 snapshot'ı hazırsa; aksi halde pipeline açık hata vermelidir.

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 29. `cs_ret_1_rank`

**feature_name:** cs_ret_1_rank

**feature_group:** cross_sectional

**description:** Aynı prediction_date içindeki ret_1 değerinin [0,1] yüzdelik sırası.

**exact_formula**

```text
rank=(average_rank(ret_1)-1)/(N_valid-1); ties=average; N_valid>=20
```

**source_columns:** ret_1

**lookback_days:** 2

**minimum_history:** Alttaki feature geçerli ve aynı prediction_date için en az MIN_CS_SECURITIES=20 geçerli security

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date

**missing_value_rule:** Alttaki değer NA ise rank NA; NA değerler rank evrenine girmez; N<20 ise o tarih için tüm ranklar NA.

**warmup_rule:** Alttaki feature'ın warm-up kuralı + aynı tarih için en az 20 geçerli security.

**expected_direction_or_interpretation:** 1'e yakın değer aynı gün evrenin en güçlü kısa getirilerindendir.

**data_leakage_risk:** Yüksek; rank yalnız prediction_date içinde, label/entry_eligible/target_hit filtrelerinden önce hesaplanmalıdır. Gelecek evren bilgisi veya tüm dönem sıralaması yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 30. `cs_ret_5_rank`

**feature_name:** cs_ret_5_rank

**feature_group:** cross_sectional

**description:** Aynı prediction_date içindeki ret_5 değerinin [0,1] yüzdelik sırası.

**exact_formula**

```text
rank=(average_rank(ret_5)-1)/(N_valid-1); ties=average; N_valid>=20
```

**source_columns:** ret_5

**lookback_days:** 6

**minimum_history:** Alttaki feature geçerli ve aynı prediction_date için en az MIN_CS_SECURITIES=20 geçerli security

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date

**missing_value_rule:** Alttaki değer NA ise rank NA; NA değerler rank evrenine girmez; N<20 ise o tarih için tüm ranklar NA.

**warmup_rule:** Alttaki feature'ın warm-up kuralı + aynı tarih için en az 20 geçerli security.

**expected_direction_or_interpretation:** 1'e yakın değer aynı evrende güçlü 5 günlük momentumu gösterir.

**data_leakage_risk:** Yüksek; rank yalnız prediction_date içinde, label/entry_eligible/target_hit filtrelerinden önce hesaplanmalıdır. Gelecek evren bilgisi veya tüm dönem sıralaması yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 31. `cs_relative_ret_5_rank`

**feature_name:** cs_relative_ret_5_rank

**feature_group:** cross_sectional

**description:** Aynı prediction_date içindeki relative_ret_5 değerinin [0,1] yüzdelik sırası.

**exact_formula**

```text
rank=(average_rank(relative_ret_5)-1)/(N_valid-1); ties=average; N_valid>=20
```

**source_columns:** relative_ret_5

**lookback_days:** 6

**minimum_history:** Alttaki feature geçerli ve aynı prediction_date için en az MIN_CS_SECURITIES=20 geçerli security

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date

**missing_value_rule:** Alttaki değer NA ise rank NA; NA değerler rank evrenine girmez; N<20 ise o tarih için tüm ranklar NA.

**warmup_rule:** Alttaki feature'ın warm-up kuralı + aynı tarih için en az 20 geçerli security.

**expected_direction_or_interpretation:** 1'e yakın değer piyasa-düzeltilmiş kesitsel gücü gösterir.

**data_leakage_risk:** Yüksek; rank yalnız prediction_date içinde, label/entry_eligible/target_hit filtrelerinden önce hesaplanmalıdır. Gelecek evren bilgisi veya tüm dönem sıralaması yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —


### 32. `cs_volume_anomaly_rank`

**feature_name:** cs_volume_anomaly_rank

**feature_group:** cross_sectional

**description:** Aynı prediction_date içindeki tl_volume_zscore_20 değerinin [0,1] yüzdelik sırası.

**exact_formula**

```text
rank=(average_rank(tl_volume_zscore_20)-1)/(N_valid-1); ties=average; N_valid>=20
```

**source_columns:** tl_volume_zscore_20

**lookback_days:** 21

**minimum_history:** Alttaki feature geçerli ve aynı prediction_date için en az MIN_CS_SECURITIES=20 geçerli security

**available_at_prediction_time:** YES — T kapanışı ve ilgili günlük snapshot COMPLETE olduktan sonra

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date

**missing_value_rule:** Alttaki değer NA ise rank NA; NA değerler rank evrenine girmez; N<20 ise o tarih için tüm ranklar NA.

**warmup_rule:** Alttaki feature'ın warm-up kuralı + aynı tarih için en az 20 geçerli security.

**expected_direction_or_interpretation:** 1'e yakın değer evrene göre sıra dışı hacim aktivitesini gösterir.

**data_leakage_risk:** Yüksek; rank yalnız prediction_date içinde, label/entry_eligible/target_hit filtrelerinden önce hesaplanmalıdır. Gelecek evren bilgisi veya tüm dönem sıralaması yasaktır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** INCLUDE

**exclusion_reason:** —



## 4. Baseline dışında değerlendirilen adaylar

### 01. `sector_relative_ret_5`

**feature_name:** sector_relative_ret_5

**feature_group:** sector_relative

**description:** Hissenin 5 günlük getirisinin tarih-etkin sektör 5 günlük getirisinden farkı.

**exact_formula**

```text
ret_5_stock - ret_5_sector_equal_weight
```

**source_columns:** ret_5, point_in_time_sector_map, same-date sector members

**lookback_days:** 6

**minimum_history:** 6 ardışık oturum ve tarih-etkin sektör üyeliği

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date + sector_id

**missing_value_rule:** Sektör üyeliği veya yeterli üye yoksa NA; güncel sektör etiketi geçmişe taşınmaz.

**warmup_rule:** Sektör mapping ve sektör endeksi hazır olana kadar üretilmez.

**expected_direction_or_interpretation:** Pozitif değer sektör üstü güçtür.

**data_leakage_risk:** Yüksek; güncel sabit sektör sınıfını geçmişe uygulamak veya test dönemi üyelerini geçmişe taşımak leakage/bias yaratır.

**live_calculation_feasibility:** LOW until point-in-time sector mapping exists

**baseline_v1_status:** DEFER

**exclusion_reason:** Repo veri sözlüğünde tarih-etkin sektör mapping'i henüz doğrulanmış değildir.


### 02. `sector_relative_ret_20`

**feature_name:** sector_relative_ret_20

**feature_group:** sector_relative

**description:** Hissenin 20 günlük getirisinin tarih-etkin sektör 20 günlük getirisinden farkı.

**exact_formula**

```text
ret_20_stock - ret_20_sector_equal_weight
```

**source_columns:** ret_20, point_in_time_sector_map, same-date sector members

**lookback_days:** 21

**minimum_history:** 21 ardışık oturum ve tarih-etkin sektör üyeliği

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date + sector_id

**missing_value_rule:** Sektör üyeliği veya yeterli üye yoksa NA.

**warmup_rule:** Sektör mapping ve sektör endeksi hazır olana kadar üretilmez.

**expected_direction_or_interpretation:** Pozitif değer sektör üstü orta dönem güçtür.

**data_leakage_risk:** Yüksek; point-in-time üyelik zorunludur.

**live_calculation_feasibility:** LOW until point-in-time sector mapping exists

**baseline_v1_status:** DEFER

**exclusion_reason:** Tarih-etkin sektör verisi hazır değil.


### 03. `sector_momentum_rank_5`

**feature_name:** sector_momentum_rank_5

**feature_group:** sector_relative

**description:** Hissenin kendi sektörü içindeki 5 günlük getiri yüzdelik sırası.

**exact_formula**

```text
(average_rank(ret_5 within prediction_date+sector)-1)/(N_sector-1)
```

**source_columns:** ret_5, point_in_time_sector_map

**lookback_days:** 6

**minimum_history:** Alttaki feature ve en az 5 geçerli sektör üyesi

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** prediction_date + sector_id

**missing_value_rule:** N_sector<5 veya üyelik eksikse NA.

**warmup_rule:** Sektör mapping hazır olana kadar NA.

**expected_direction_or_interpretation:** 1'e yakın değer sektör liderliğini gösterir.

**data_leakage_risk:** Yüksek; sektör üyeliği tarih-etkin olmalıdır.

**live_calculation_feasibility:** LOW until point-in-time sector mapping exists

**baseline_v1_status:** DEFER

**exclusion_reason:** Tarih-etkin sektör üyeliği hazır değil.


### 04. `turnover_20`

**feature_name:** turnover_20

**feature_group:** liquidity

**description:** 20 günlük TL hacmin piyasa değerine oranının ortalaması.

**exact_formula**

```text
mean(V_j / market_cap_try_j, j=t-19..t)
```

**source_columns:** is_tl_volume, market_cap_try

**lookback_days:** 20

**minimum_history:** 20 pozitif hacim ve point-in-time piyasa değeri

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Piyasa değeri eksik/<=0 ise NA; fill yok.

**warmup_rule:** 20 geçerli gün ve point-in-time doğrulama sonrası.

**expected_direction_or_interpretation:** Yüksek değer sermayeye göre yüksek işlem aktivitesidir.

**data_leakage_risk:** Yüksek; bugünkü sorguda gelecekte revize edilen piyasa değeri geçmişe taşınmamalıdır.

**live_calculation_feasibility:** MEDIUM after point-in-time validation

**baseline_v1_status:** DEFER

**exclusion_reason:** market_cap_try alanının tarihsel point-in-time güvenliği feature amacıyla doğrulanmadı.


### 05. `free_float_turnover_20`

**feature_name:** free_float_turnover_20

**feature_group:** liquidity

**description:** 20 günlük TL hacmin halka açık piyasa değerine oranının ortalaması.

**exact_formula**

```text
mean(V_j / free_float_market_cap_try_j, j=t-19..t)
```

**source_columns:** is_tl_volume, free_float_market_cap_try

**lookback_days:** 20

**minimum_history:** 20 pozitif hacim ve point-in-time halka açık piyasa değeri

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Payda eksik/<=0 ise NA.

**warmup_rule:** 20 geçerli gün ve point-in-time doğrulama sonrası.

**expected_direction_or_interpretation:** Yüksek değer halka açık kısma göre yoğun işlem aktivitesidir.

**data_leakage_risk:** Yüksek; halka açıklık ve piyasa değeri sonradan revize olabilir.

**live_calculation_feasibility:** MEDIUM after point-in-time validation

**baseline_v1_status:** DEFER

**exclusion_reason:** Halka açık piyasa değerinin tarihsel point-in-time güvenliği doğrulanmadı.


### 06. `beta_60`

**feature_name:** beta_60

**feature_group:** market_sensitivity

**description:** Son 60 günlük hisse getirilerinin XU100 getirilerine rolling beta tahmini.

**exact_formula**

```text
cov_ddof1(ret_1_stock, market_ret_1,60) / var_ddof1(market_ret_1,60)
```

**source_columns:** ret_1, market_ret_1

**lookback_days:** 61

**minimum_history:** 60 eşleşmiş günlük getiri ve pozitif piyasa varyansı

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Eksik eşleşme veya sıfır piyasa varyansı varsa NA.

**warmup_rule:** 60 getiri oluşana kadar NA.

**expected_direction_or_interpretation:** 1 üzeri yüksek piyasa duyarlılığı; kısa hedefte rejim etkileşimi yaratabilir.

**data_leakage_risk:** Orta; yalnız geçmiş kullanılsa da kısa örneklem gürültüsü ve endpoint eşleşmesi riski vardır.

**live_calculation_feasibility:** HIGH after index pipeline

**baseline_v1_status:** EXPERIMENT_LATER

**exclusion_reason:** Baseline sadeliği için ertelendi; kısa vadeli hedefte ek katkısı kontrollü test edilmeli.


### 07. `idiosyncratic_ret_5`

**feature_name:** idiosyncratic_ret_5

**feature_group:** market_sensitivity

**description:** 5 günlük getirinin rolling beta ile açıklanan piyasa getirisinden kalan kısmı.

**exact_formula**

```text
ret_5 - beta_60 * market_ret_5
```

**source_columns:** ret_5, beta_60, market_ret_5

**lookback_days:** 61

**minimum_history:** Geçerli beta_60 ve 5 günlük getiriler

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Alt feature'lardan biri NA ise NA.

**warmup_rule:** beta_60 oluşana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer piyasa etkisinden bağımsız güçtür.

**data_leakage_risk:** Orta; beta yalnız T ve geçmişten hesaplanmalı, tam dönem regresyonu yasaktır.

**live_calculation_feasibility:** HIGH after beta experiment

**baseline_v1_status:** EXPERIMENT_LATER

**exclusion_reason:** Beta bağımlılığı ve ek karmaşıklık nedeniyle baseline dışında.


### 08. `downside_volatility_20`

**feature_name:** downside_volatility_20

**feature_group:** volatility

**description:** Son 20 gündeki negatif bir günlük getirilerin aşağı yönlü standart sapması.

**exact_formula**

```text
sqrt(mean(min(ret_1[j],0)^2, j=t-19..t))
```

**source_columns:** ret_1

**lookback_days:** 21

**minimum_history:** 20 geçerli ret_1

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Herhangi bir ret_1 eksikse NA.

**warmup_rule:** 20 getiri tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer aşağı yönlü risk ve olası reversal/çöküş rejimini gösterir.

**data_leakage_risk:** Düşük; yalnız geçmiş getirileri.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** EXPERIMENT_LATER

**exclusion_reason:** return_volatility_20 ile ek katkısı ablation ile ölçülmeli.


### 09. `breakout_strength_20`

**feature_name:** breakout_strength_20

**feature_group:** breakout

**description:** T kapanışının T hariç önceki 20 günün tepesini aşma derecesi.

**exact_formula**

```text
C_t / max(H_(t-20):H_(t-1)) - 1
```

**source_columns:** yf_provider_close, yf_provider_high

**lookback_days:** 21

**minimum_history:** T close ve önceki 20 high

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** rolling max(20).shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Önceki 20 high eksikse NA.

**warmup_rule:** 21 oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Pozitif değer kapanış bazlı breakout, negatif değer tepe altında kalmadır.

**data_leakage_risk:** Düşük; shift(1) unutulursa T high referansa girer ve anlam değişir.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** EXPERIMENT_LATER

**exclusion_reason:** distance_from_high_20 ile benzerlik nedeniyle ayrı deney gerektirir.


### 10. `failed_breakout_score_20`

**feature_name:** failed_breakout_score_20

**feature_group:** breakout

**description:** T gününde önceki 20 gün tepesinin aşılması fakat kapanışta korunamamasını sürekli ölçer.

**exact_formula**

```text
prior_high=max(H_(t-20):H_(t-1)); max(H_t-prior_high,0)/prior_high - max(C_t-prior_high,0)/prior_high
```

**source_columns:** yf_provider_high, yf_provider_close

**lookback_days:** 21

**minimum_history:** T high/close ve önceki 20 high

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** rolling max(20).shift(1)

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** prior_high eksik/<=0 ise NA.

**warmup_rule:** 21 oturum tamamlanana kadar NA.

**expected_direction_or_interpretation:** Yüksek değer gün içi kırılımın kapanışa taşınamadığını gösterir.

**data_leakage_risk:** Düşük; yalnız T ve geçmiş. Formülün ek katkısı kanıtlanmamıştır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** EXPERIMENT_LATER

**exclusion_reason:** Baseline için fazla özel; kontrollü breakout deneyinde denenmeli.


### 11. `momentum_x_volume_anomaly`

**feature_name:** momentum_x_volume_anomaly

**feature_group:** manual_interaction

**description:** 5 günlük momentum ile hacim anomalisi elle çarpımı.

**exact_formula**

```text
ret_5 * tl_volume_zscore_20
```

**source_columns:** ret_5, tl_volume_zscore_20

**lookback_days:** 21

**minimum_history:** Her iki alt feature geçerli

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Alt feature NA ise NA.

**warmup_rule:** Her iki alt feature oluşana kadar NA.

**expected_direction_or_interpretation:** Yüksek pozitif değer hacimle teyitli momentumu temsil edebilir.

**data_leakage_risk:** Düşük leakage; fakat gereksiz elle etkileşim model karmaşıklığını artırır.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** REJECT

**exclusion_reason:** LightGBM doğrusal olmayan etkileşimi kendisi öğrenebilir; baseline'a eklenmeyecek.


### 12. `named_candlestick_patterns`

**feature_name:** named_candlestick_patterns

**feature_group:** candlestick

**description:** Doji, hammer, engulfing gibi çok sayıda isimlendirilmiş ikili mum bayrağı.

**exact_formula**

```text
Çeşitli eşik ve ikili kurallar
```

**source_columns:** yf_provider_open/high/low/close

**lookback_days:** 1-3

**minimum_history:** Desene göre

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** VARIES

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Eksik OHLC'de NA.

**warmup_rule:** Desene göre.

**expected_direction_or_interpretation:** İsimlendirilmiş desen yorumu.

**data_leakage_risk:** Orta; threshold arbitrajı ve çoklu karşılaştırma overfitting riski.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** REJECT

**exclusion_reason:** Aynı bilgi intraday_return ve close_location_value gibi sürekli feature'larla daha sade temsil ediliyor.


### 13. `additional_oscillator_family`

**feature_name:** additional_oscillator_family

**feature_group:** technical_indicator

**description:** MACD, stochastic, CCI ve çok sayıda pencere varyasyonu.

**exact_formula**

```text
Göstergeye göre değişir
```

**source_columns:** yf_provider_ohlc

**lookback_days:** VARIES

**minimum_history:** VARIES

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** VARIES

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Eksik pencerede NA.

**warmup_rule:** Göstergeye göre.

**expected_direction_or_interpretation:** Benzer trend/momentum bilgisini tekrarlar.

**data_leakage_risk:** Orta; kütüphane varsayımları ve çoklu deneme overfitting riski.

**live_calculation_feasibility:** HIGH

**baseline_v1_status:** REJECT

**exclusion_reason:** İlk sürüm yalnız rsi_14_sma kullanacak; ek osilatörler ablation kanıtı olmadan eklenmeyecek.


### 14. `limit_proximity`

**feature_name:** limit_proximity

**feature_group:** market_microstructure

**description:** T veya T+1 tahmini tavan seviyesine fiyat uzaklığı.

**exact_formula**

```text
price / estimated_upper_limit - 1
```

**source_columns:** estimated_upper_limit, tick_size, price_limit fields

**lookback_days:** 1

**minimum_history:** Kural çözümü

**available_at_prediction_time:** YES only if stated source is point-in-time and snapshot-complete; otherwise NO

**required_shift:** NONE

**rolling_group_key:** security_id

**cross_sectional_group_key:** NONE

**missing_value_rule:** Kural yoksa NA.

**warmup_rule:** Kural çözümüne bağlı.

**expected_direction_or_interpretation:** Tavana yakınlık mikro-yapı baskısını temsil edebilir.

**data_leakage_risk:** Çok yüksek; proje talimatında estimated_upper_limit ve tavan uygunluk alanları feature olarak açıkça yasaktır.

**live_calculation_feasibility:** TECHNICALLY POSSIBLE BUT FORBIDDEN

**baseline_v1_status:** REJECT

**exclusion_reason:** İşlem uygunluğu/denetim alanları model sinyaline dönüştürülmeyecek.


## 5. Deney sırası

Her deneyde mümkün olduğunca yalnız bir ana feature grubu eklenir. Aynı deneyde LightGBM parametreleri, karar eşiği veya günlük seçim sayısı değiştirilmez.

### E0 — Temel fiyat, getiri ve hacim

- `ret_1`, `ret_2`, `ret_3`, `ret_5`, `ret_10`, `ret_20`
- `log_median_tl_volume_20`
- `tl_volume_ratio_5_20`
- `tl_volume_zscore_20`

Başarı ölçütü: Walk-forward testte modelin pozitif örnek seçmesi; PR-AUC, Precision@5/10 ve seçilen hisselerin getirilerinin kaydedilmesi.

### E1 — Trend ve volatilite

E0'a şunlar eklenir:

- `close_to_sma_5`
- `close_to_sma_20`
- `distance_from_high_20`
- `positive_day_ratio_5`
- `return_volatility_5`
- `return_volatility_20`
- `volatility_ratio_5_20`
- `true_range_pct`
- `range_expansion_5_20`

Başarı ölçütü: E0'a göre dönemler arası tutarlı ek katkı; tek bir kısa dönemdeki kazanç yeterli değildir.

### E2 — Mum/gün içi yapı ve sınırlı RSI

E1'e şunlar eklenir:

- `overnight_gap`
- `intraday_return`
- `close_location_value`
- `rsi_14_sma`

Başarı ölçütü: Özellikle kısa hedef Precision@5/10 ve ortalama işlem getirisine ek katkı.

### E3 — Endekse göre relatif güç

E2'ye şunlar eklenir:

- `market_ret_1`
- `relative_ret_1`
- `relative_ret_5`
- `relative_ret_20`

Ön koşul: Sürümlü XU100 snapshot'ı ve tarih eşleşmesi kabul testi `PASS`.

### E4 — Sektöre göre relatif güç

İlk aşamada koşulmaz. Tarih-etkin sektör mapping'i doğrulandıktan sonra ayrı deney olarak:

- `sector_relative_ret_5`
- `sector_relative_ret_20`
- `sector_momentum_rank_5`

### E5 — Kesitsel feature'lar

E3'e şunlar eklenir:

- `cs_ret_1_rank`
- `cs_ret_5_rank`
- `cs_relative_ret_5_rank`
- `cs_volume_anomaly_rank`

Başarı ölçütü: Günlük sıralama amacı nedeniyle özellikle Precision@5 ve Precision@10.

### E6 — Likidite feature'larının tamamlanması

E5'e şunlar eklenir:

- `tl_volume_cv_20`
- `amihud_20`

`log_median_tl_volume_20` temel hacim deneyinde zaten bulunur. Likidite feature'ları kesin likidite filtresi değildir; filtre ayrı karar ve deney konusudur.

### E7 — Sınırlı ileri adaylar

Yalnız önceki deneyler tamamlandıktan sonra tek tek:

- `downside_volatility_20`
- `beta_60`
- `idiosyncratic_ret_5`
- `breakout_strength_20`
- `failed_breakout_score_20`

### E8 — LightGBM parametre optimizasyonu ve etkileşimler

- `feature_fraction` dahil hiperparametreler ancak feature grubu deneyleri tamamlandıktan sonra incelenir.
- İlk kontrol `feature_fraction=1.0`; daha düşük değerler ayrı kontrollü deneydir.
- Elle çarpım feature'ları başlangıçta eklenmez.

## 6. Feature snapshot kabul kriterleri

Feature pipeline uygulandığında aşağıdaki kontroller zorunludur:

1. `security_id` yoksa açık hata; ticker fallback yok.
2. Satır anahtarı `security_id + prediction_date` tekil olmalı.
3. Kaynak snapshot'ları fiziksel checksum doğrulamasından geçen `COMPLETE` kayıtlar olmalı.
4. Feature üretimi label snapshot'ını girdi olarak alamamalı.
5. Yasak alanlar giriş şemasında görülürse açık hata veya denylist raporu oluşmalı.
6. T+1 ve sonraki veriler değiştirildiğinde T feature çıktısının checksum'u değişmemeli.
7. Rolling pencereler global BİST oturumlarını kullanmalı; eksik security günü pencereyi sıkıştıramamalı.
8. Her price feature'ı pozitif sabit fiyat ölçeklemesinde aynı sonucu üretmeli.
9. Provider ve nominal OHLC aynı feature formülünde karıştırılmamalı.
10. Ranklar label/entry uygunluğu eklenmeden önce hesaplanmalı.
11. Bir label sütununu değiştirmek cross-sectional feature sonuçlarını değiştirmemeli.
12. XU100 tarihi hisse `prediction_date` ile birebir eşleşmeli; forward-fill yasak.
13. `NaN` ve sonsuz sayıları ayrı sayan kalite özeti üretilmeli.
14. Aynı input snapshot/config/kod ile feature çıktısı idempotent olmalı.
15. Feature isimleri ve sırası merkezi config ve model metadata'sında değişmez olarak saklanmalı.
16. Baseline şemasında tam 32 `INCLUDE` feature bulunmalı.
17. `security_id`, tarih, ticker veya lineage alanları 32 model feature arasına girmemeli.
18. `feature_fraction` ve diğer model parametreleri feature kataloğunda feature kararı gibi uygulanmamalı.

## 7. Açık bağımlılıklar

- Sürümlü ve doğrulanmış ayrı XU100 kapanış snapshot'ının gerçek veri kabulü tamamlanmalıdır.
- Tarih-etkin sektör mapping'i bulunmadığı için sektör feature'ları `DEFER` durumundadır.
- `market_cap_try` ve `free_float_market_cap_try` alanlarının tarihsel point-in-time niteliği doğrulanmadan turnover feature'ları kullanılamaz.
- Tahmin tarihinde T verisi geçersiz veya işlem kanıtı bulunmayan securities için günlük tahmin evreni kuralı feature pipeline uygulama tasarımında ayrıca kesinleştirilmelidir. Bu kural T+1 `entry_eligible` alanına dayanamaz.

## 8. Belge durum özeti

```text
Kesinleşen kararlar:
- baseline_v1 toplam 32 feature içerir.
- Rolling anahtarı yalnız security_id'dir.
- BİST takvim boşlukları sıkıştırılmaz ve doldurulmaz.
- Price feature'lar ölçekten bağımsız formüllerle yf_provider OHLC kullanır.
- Nominal OHLC yalnız işlem/label/backtest tarafında kalır.
- Baseline hacim kaynağı is_tl_volume'dır.
- Cross-sectional ranklar label ve T+1 uygunluk filtrelerinden önce hesaplanır.
- security_id'siz eski snapshot feature pipeline tarafından reddedilir.
- Sektör, turnover, beta ve ileri breakout adayları ayrı durumlarla ertelenmiştir.
- feature_fraction parametre optimizasyonu aşamasına ertelenmiştir.

Sıradaki görev:
- Sürümlü ve doğrulanmış XU100 snapshot bağımlılığını netleştirmek veya uygulamak.
- Ardından yalnız bu belgeye uygun modüler feature pipeline tasarımını hazırlamak.
```
