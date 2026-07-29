# AGENTS.md

## Amaç

Bu repo, BİST hisseleri arasından önümüzdeki üç işlem günü içinde en az `%5` yükselme ihtimali yüksek hisseleri LightGBM Classifier ile tahmin edip sıralayan karar destek sistemini içerir.

Bu dosya Codex'in repo üzerinde çalışırken uyması gereken kalıcı kuralları tanımlar.

## Tek Doğru Kaynak

Ana repo:

`https://github.com/enesmertturkoglu/bist-ml-model`

GitHub reposundaki dosyalar bağlayıcı ve güncel kaynaktır. Sohbetlerde, indirme klasörlerinde veya geçici çalışma alanlarında bulunan kopyalar yalnızca çalışma kopyasıdır.

## Her Görevden Önce Okunacak Dosyalar

Codex her göreve başlamadan önce en az şu dosyaları okumalıdır:

1. `PROJECT_BRIEF.md`
2. `PROJECT_STATUS.md`
3. `DECISIONS.md`
4. Bu `AGENTS.md`

Görev veri alanlarıyla ilgiliyse `DATA_DICTIONARY.md`, feature'larla ilgiliyse `FEATURE_CATALOG.md`, deneylerle ilgiliyse `EXPERIMENT_LOG.md` de okunmalıdır. Bu dosyalar henüz yoksa görev gerektirmeden oluşturulmamalıdır.

## ChatGPT–Codex İş Bölümü

- ChatGPT sohbetleri seçenekleri değerlendirir, teknik kararları kesinleştirir, riskleri ve başarı kriterlerini tanımlar.
- Codex gerçek repo üzerinde dosya değiştirir, kod yazar, test çalıştırır ve değişiklikleri GitHub'a aktarır.
- Codex yeni bir ürün veya model kararı vermemelidir. Belirsiz kararları uygulamak yerine açık soru olarak raporlamalıdır.
- ChatGPT'den gelen `Codex Devir Talimatı`, görev kapsamının ana kaynağıdır; ancak repo içindeki daha güncel kesin kararlarla çelişirse çelişki raporlanmalı ve kesin karar sessizce değiştirilmemelidir.

## Belge Güncelleme Zorunluluğu

Bir görev kesinleşmiş kararı uyguluyorsa veya proje durumunu değiştiriyorsa ilgili belgeler aynı görev içinde güncellenmelidir:

- Kesin teknik kararlar: `DECISIONS.md`
- Mevcut aşama, tamamlanan işler, sıradaki görevler ve açık sorular: `PROJECT_STATUS.md`
- Proje amacı veya kapsamındaki değişiklikler: `PROJECT_BRIEF.md`
- Gerçek veri alanları ve anlamları: `DATA_DICTIONARY.md`
- Feature formülleri, kaynak alanları ve tahmin anındaki kullanılabilirlik: `FEATURE_CATALOG.md`
- Gerçek model deneyleri ve sonuçları: `EXPERIMENT_LOG.md`

Kesin kararlarla geçici fikirler birbirine karıştırılmamalıdır. Mevcut kararlar, özellikle `DECISIONS.md` içindeki D010–D016, açık yeni bir karar olmadan silinmemeli veya anlamı değiştirilmemelidir.

## Codex Devir Talimatının Uygulanması

Codex bir devir talimatı aldığında:

1. Repo ve hedef branch'i doğrular.
2. Talimatta ve bu dosyada belirtilen zorunlu belgeleri okur.
3. Değiştirilecek dosyaları işlemden önce listeler.
4. Yalnızca görevle ilgili dosyaları değiştirir.
5. Talimatta belirtilen kararları tam ve açık şekilde belgelere işler.
6. Mevcut bağlayıcı kararları korur.
7. Kod değişikliği varsa uygun testleri ekler veya çalıştırır.
8. Diff'i inceleyerek ilgisiz değişiklik bulunmadığını kontrol eder.
9. Tercihen odaklı bir branch ve commit kullanır; kullanıcı talep ederse pull request oluşturur.
10. Görev sonunda sonuç raporu verir.

## Kodlama Kuralları

- Yalnızca LightGBM Classifier kullanılacaktır; açık yeni karar olmadan farklı model veya ensemble eklenmez.
- Kod modüler ve test edilebilir olmalıdır.
- Veri toplama, temizleme, label üretme, feature üretme, model eğitme, tahmin ve backtest ayrı sorumluluklarda tutulmalıdır.
- Ayarlar merkezi config yapısında tutulmalıdır.
- Random seed, veri dönemi ve model parametreleri kaydedilmelidir.
- Fiyat bağımlı giriş, label, çıkış, OHLC geçerlilik ve tavan hesaplarında yalnız yFinance nominal OHLC alanları kullanılmalıdır.
- İş Yatırım ve yFinance fiyatları aynı işlem hesabında karıştırılmamalı; İş Yatırım fiyatları yalnız veri kalite çapraz kontrolünde kullanılmalıdır.
- yFinance sağlayıcı OHLC değerleri `yf_provider_*`, nominal karşılıkları `yf_nominal_*` alanlarında ayrı ve değişmeden saklanmalıdır.
- `yf_future_split_factor` ve gelecekteki action bilgileri model feature'ı veya tahmin sinyali yapılmamalıdır.
- Ham yFinance yanıtları ve normalizasyonda kullanılan split kayıtları veri sürümüyle saklanmalı; yeni indirmeler eski sürümlerin üzerine yazılmamalıdır.
- Kullanıcının paylaşmadığı dosya içeriği varsayılmamalıdır.
- İlgisiz dosyalar değiştirilmemelidir.
- Büyük mimari değişiklikler gerekçesiz yapılmamalıdır.

## Veri Sızıntısı Kontrolü

Her veri ve feature değişikliğinde aşağıdakiler açıkça kontrol edilmelidir:

- Bilgi tahmin anında gerçekten mevcut mu?
- Gelecek günlerden bilgi kullanılıyor mu?
- Rolling ve shift işlemlerinin yönü doğru mu?
- Label penceresi feature hesaplarına sızıyor mu?
- Aynı tarihteki hisseler zaman ayrımında birlikte tutuluyor mu?
- Canlı sistemde aynı hesaplama tekrar üretilebilir mi?

Veri sızıntısı riski bulunan satırlar veya tasarım kararları görev sonucunda özellikle belirtilmelidir.

## Görev Sonu Raporu

Her Codex görevi şu başlıklarla tamamlanmalıdır:

```text
Değiştirilen dosyalar:
Yapılan değişiklikler:
Çalıştırılan testler ve sonuçları:
Veri sızıntısı kontrolleri:
Açık sorular:
Sıradaki önerilen görev:
Commit veya PR:
```

Bir test çalıştırılamadıysa nedeni açıkça yazılmalıdır. Yapılmamış bir işlem yapılmış gibi gösterilmemelidir.

## Mevcut Aşama

Ana model dönemi `2020-03-13` tarihinde başlar.

Standart normal adi paylarda tavan açılış `%10` marj ve içeri doğru fiyat adımı yuvarlamasıyla hesaplanır.

Tek fiyat kaynaklı dayanıklı kabul koşusu eksiksiz gerçek veride `PASS` ile tamamlanmıştır.

Veri toplama ve değişmez snapshot altyapısı, temizleme, üç BİST işlem günlük label pipeline'ı ve security identity/tarih-etkin ticker mapping tamamlanmıştır.

D028 `baseline_v1` kataloğu tam 32 feature olarak kesinleştirilmiş; D029 bağımsız XU100, global BİST takvimi ve 32 feature pipeline'ı tamamlanmıştır.

D030 prediction universe ve training dataset tamamlanmıştır.

D031 expanding 60-validation/20-test walk-forward ve label availability purge tamamlanmıştır.

D032 LightGBM baseline, günlük sıralama ve metrikler tamamlanmıştır.

D033 immutable model artifact registry tamamlanmıştır.

D034 exact `2026-07-29` aktif BİST master evreni 621 security ile dondurulmuştur.

Son doğrulanmış regresyon sonucu `306 passed` olmuştur. İlk gerçek LightGBM performans deneyi henüz yapılmamıştır.

Sıradaki teknik aşama `2020-03-13` sonrası tam raw, identity, clean, label, XU100 ve `baseline_v1` feature snapshot zinciridir.

Açık kararlar:

- Likidite filtresi
- Günlük seçim sayısı
- Komisyon ve slippage varsayımları
- İlk walk-forward test tarihi
