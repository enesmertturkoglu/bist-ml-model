# PROJECT BRIEF

## Proje Adı

BİST Kısa Vadeli Hisse Yükseliş Tahmin Sistemi

## Projenin Amacı

Borsa İstanbul'da işlem gören hisseler arasından, önümüzdeki 2-3 işlem günü içinde en az %5 yükselme ihtimali yüksek olan hisseleri belirleyen ve sıralayan sade bir makine öğrenmesi sistemi geliştirmek.

Sistem her hisse için LightGBM ham pozitif sınıf skorunu üretecek ve hisseleri bu skora göre sıralayacaktır. Bu skor, kalibrasyon doğrulanmadan gerçek gerçekleşme olasılığı olarak iddia edilmeyecektir.

## Ana Model

- LightGBM Classifier
- Model çıktısı: Her hisse için ham `LGBMClassifier.predict_proba(X)[:,1]` pozitif sınıf skoru
- Skor kalibre edilmiş gerçek olasılık olarak yorumlanmayacaktır.
- Günlük seçim sayısı henüz kesinleşmemiştir; model hisseleri ham pozitif sınıf skoruna göre sıralayacaktır.

## İlk Sürümün Kapsamı

### `baseline_v1` mevcut kapsamı

- Günlük BİST fiyat ve hacim verileri
- BİST endeks verileri
- Veri toplama başlangıcındaki güncel aktif BİST şirket paylarından oluşan sabit hisse evreni
- Güncel aktif hisselerin doğrulanmış eski işlem kodlarının aynı menkul kıymet kimliği altında birleştirilmesi
- Tam 32 fiyat, hacim, momentum, volatilite, gün içi yapı, endeks/relatif güç ve kesitsel feature
- Likiditenin TL hacim, hacim anomalisi, hacim değişkenliği ve Amihud fiyat etkisi gibi proxy'lerle temsil edilmesi
- Zaman sıralı walk-forward validation

`baseline_v1` içinde point-in-time sektör feature'ı yoktur. Sektör feature'ları tarih-etkin sektör mapping'i hazır olana kadar ertelenmiştir. Piyasa değeri ve halka açık piyasa değeri tabanlı turnover feature'ları point-in-time güvenlikleri doğrulanana kadar ertelenmiştir. Likidite filtresi henüz kesinleşmemiştir; mevcut likidite proxy'leri master evren filtresi değildir.

### Daha geniş ilk sürüm deney yol haritası

- Tarih-etkin sektör mapping'i doğrulandıktan sonra sektör feature'larının ayrı deneylerde değerlendirilmesi
- Point-in-time piyasa değeri ve halka açık piyasa değeri doğrulandıktan sonra turnover feature'larının değerlendirilmesi
- Likidite filtresinin ayrı karar ve deney konusu olarak belirlenmesi
- Gerçekçi backtest
- Daha sonra paper trading

## İlk Sürüm Evren Sınırlaması

İlk sürümde veri toplama ve model geliştirme sürecini sadeleştirmek için güncel aktif BİST şirket paylarından oluşan sabit evren kullanılacaktır.

Günümüzde aktif olmayan ve kot dışı kalmış hisseler ilk sürümün geçmiş eğitim ve backtest evrenine dahil edilmeyecektir.

Bu seçim survivorship bias oluşturur. Bu nedenle ilk sürüm sonuçları tam point-in-time tarihsel evren performansı olarak yorumlanmayacaktır.

Point-in-time tarihsel evren, sade pipeline çalışır hale geldikten sonra ayrı bir geliştirme ve karşılaştırmalı deney konusu olacaktır.

## İlk Sürüm Veri Kaynakları

yFinance, bütün fiyat bağımlı hesapların tek kaynağıdır. Open, high, low ve close değerleri sağlayıcının `Stock Splits` kayıtlarıyla dönemin nominal fiyat ölçeğine geri taşınır; giriş, label, çıkış, OHLC geçerlilik ve tavan hesabında yalnız bu yFinance nominal OHLC serisi kullanılır.

Orijinal yFinance sağlayıcı fiyatları ile nominal fiyatlar ayrı saklanır. Split normalizasyonu yalnız tarihsel fiyat birimi dönüşümüdür; split faktörü model feature'ı veya tahmin sinyali değildir.

İş Yatırım ana BİST işlem takvimi, TL işlem hacmi, endeks verileri, ağırlıklı ortalama fiyat, piyasa değeri, halka açık piyasa değeri ve kurumsal işlem/veri kalite sinyalleri için kullanılır. İş Yatırım fiyatları yFinance fiyatlarıyla label veya backtest hesabında karıştırılmaz; yalnız çapraz veri kalite uyarısı üretir.

Kaynakta piyasa değeri, halka açık piyasa değeri veya sektör alanlarının bulunması bunların `baseline_v1` feature'ı olduğu anlamına gelmez. Bu alanlar yalnız tarih-etkin ve point-in-time güvenlikleri ayrıca doğrulandıktan sonra daha geniş ilk sürüm deney yol haritasında değerlendirilebilir.

## İlk Sürümde Kullanılmayacaklar

- XGBoost ve diğer benchmark modeller
- Ensemble modeller
- Ayrı ranking modeli
- Derin öğrenme
- Haber analizi
- KAP metin analizi
- Sosyal medya analizi
- Otomatik emir gönderme

## Başarı Değerlendirmesi

Accuracy kaydedilecek ancak tek başına başarı ölçütü olmayacaktır.

Temel metrikler:

- Precision
- Recall
- F1-score
- ROC-AUC
- PR-AUC
- Precision@5
- Precision@10
- Ortalama işlem getirisi
- Net getiri
- Maximum drawdown

## Çalışma Akışı

İlk sürümün operasyonel akışı birbirinden ayrılmış ve sürümlü dört adımdan oluşacaktır:

1. Günlük veri güncellemesi, sağlayıcı verilerini değişmez ve checksum ile doğrulanabilir snapshot'lar halinde kaydeder.
2. Bağımsız model eğitimi yalnız kullanıcı tarafından açıkça çalıştırılır; belirtilen `as_of_date` tarihindeki tamamlanmış label'ları kullanarak LightGBM'i sıfırdan eğitir ve yeni bir model sürümü oluşturur.
3. Günlük tahmin, yeniden eğitim yapmadan kullanıcının seçtiği veya aktif model sürümüyle tahmin tarihindeki en güncel kullanılabilir feature'ları değerlendirir ve hisseleri ham pozitif sınıf skoruna göre sıralar.
4. Tahmin sonucu; `as_of_date`, model sürümü, veri snapshot kimlikleri ve üretim zamanı ile sürümlü olarak kaydedilir.

Model ve tahmin kayıtları ilk sürümde MLflow gibi ek bir sistem yerine sade, dosya tabanlı ve değişmez artifact yapısıyla yönetilecektir.

## Mevcut Aşama

Ana model dönemi `2020-03-13` tarihinde başlar. Standart normal adi paylarda tavan açılış `%10` marj ve içeri doğru fiyat adımı yuvarlamasıyla hesaplanır; baz fiyat ve açılış karşılaştırması yFinance nominal OHLC serisinden alınır.

Hibrit fiyat hesabından vazgeçilmiş, bütün fiyat alanları için yFinance nominal OHLC tek kaynak olarak kesinleştirilmiş ve dayanıklı kaynak kabul koşusu `PASS` ile tamamlanmıştır.

Veri toplama ve değişmez snapshot altyapısı, temizleme, label üretimi, security identity/tarih-etkin ticker mapping, global BİST takvimi, bağımsız doğrulanmış XU100, 32 feature'lı `baseline_v1`, prediction universe, LightGBM expanding walk-forward ve değişmez model artifact altyapısı tamamlanmıştır.

Gerçek kabul paneli 20 security × 39 seans = 780 satırla `PASS` tamamlanmıştır. Duplicate `security_id + prediction_date` ve sonsuz değer sayısı `0`, son seansta feature geçerliliği `%100` olmuştur.

Resmî kaynaklı `bist_active_universe_v1`, exact `2026-07-29` as-of tarihinde 621 security ile dondurulmuştur. PR #5 sonrasında resumable full-history orchestration ve LightGBM çağırmayan fold feasibility altyapısı tamamlanmıştır. İki turlu production collection'ın son tutarlı checkpoint'i 43/621 security denenmiş, 22 COMPLETE, 17 PARTIAL, 4 NO_HISTORY ve 578 UNATTEMPTED durumundadır; sıradaki security EKSUN'dur. Sıradaki iş collection'ı checkpoint'ten tamamlamak ve ardından `2020-03-13` sonrası raw, identity, clean, label, XU100 ve feature snapshot zincirini üretmektir. İlk gerçek test tarihi fold feasibility raporundan sonra ayrı kararla kesinleştirilecektir.

## Sohbetler Arası Devir Standardı

Her teknik sohbetin sonunda aşağıdaki dört başlık mutlaka çıkarılacaktır:

```text
Kesinleşen kararlar:
Tamamlanan işler:
Açık sorular:
Sıradaki görev:
```

Bu özet, ilgili proje dosyalarının güncellenmesi ve başka bir sohbette çalışmaya devam edilirken bağlam kaybı yaşanmaması için kullanılacaktır.

- Kesinleşen kararlar gerektiğinde `DECISIONS.md` dosyasına eklenir.
- Güncel aşama, tamamlanan işler ve sıradaki görevler `PROJECT_STATUS.md` dosyasına işlenir.
- Veri alanları netleştiğinde `DATA_DICTIONARY.md` güncellenir.
- Feature kararları netleştiğinde `FEATURE_CATALOG.md` güncellenir.
- Deney sonuçları oluştuğunda `EXPERIMENT_LOG.md` güncellenir.

## Merkezi Kaynak ve Güncelleme Kuralı

Projenin güncel ve bağlayıcı belgeleri aşağıdaki GitHub reposunda tutulacaktır:

`https://github.com/enesmertturkoglu/bist-ml-model`

GitHub reposundaki dosyalar projenin tek doğru kaynağıdır. Sohbetlere yüklenen veya geçici çalışma alanlarında oluşturulan kopyalar bağlayıcı kabul edilmez.

Her kesin karar veya tamamlanan ana aşama sonrasında:

- Kesinleşen teknik kararlar `DECISIONS.md` dosyasına işlenir.
- Mevcut aşama, tamamlanan işler ve sıradaki görevler `PROJECT_STATUS.md` dosyasında güncellenir.
- Gerekli diğer proje belgeleri aynı GitHub reposunda güncellenir.
- Yeni bir teknik çalışmaya başlamadan önce ilgili dosyaların GitHub'daki en güncel sürümü okunur.

Dosya değişiklikleri mümkün olduğunca doğrudan GitHub üzerinde commit edilmelidir. Yerel veya sohbet içi dosya kopyaları yalnızca geçici çalışma amacıyla kullanılabilir.


## ChatGPT–Codex İş Bölümü

Proje iki araç birlikte kullanılarak yönetilecektir:

### ChatGPT sohbetlerinin görevi

- Teknik seçenekleri değerlendirmek
- Karar verilmesi gereken konuları küçük adımlara bölmek
- Kararların etkilerini, risklerini ve başarı kriterlerini açıklamak
- Kesinleşen kararları geçici fikirlerden ayırmak
- Sıradaki işi ve Codex'e devredilecek uygulama kapsamını belirlemek
- Codex tarafından yapılan değişiklikleri GitHub'daki güncel dosyalardan kontrol etmek

### Codex'in görevi

- GitHub reposundaki gerçek dosyaları değiştirmek
- Kod yazmak ve mevcut kodu düzenlemek
- Testleri ve gerekli kontrolleri çalıştırmak
- İlgili proje belgelerini güncellemek
- Değişiklikleri commit veya pull request ile GitHub'a aktarmak

ChatGPT sohbetlerinde karar verilmesi, GitHub dosyalarının güncellendiği anlamına gelmez. Bağlayıcı değişiklik ancak Codex veya kullanıcı tarafından GitHub reposuna işlendiğinde tamamlanmış sayılır.

## Zorunlu Codex Devir Talimatı

Bir sohbet sırasında kesin bir karar verildiğinde, ana aşama tamamlandığında veya proje belgelerinden herhangi birinin güncellenmesi gerektiğinde sohbet, cevabının sonunda doğrudan Codex'e kopyalanabilecek bir **Codex Devir Talimatı** vermelidir.

Talimat en az şu bilgileri içermelidir:

1. Repo: `https://github.com/enesmertturkoglu/bist-ml-model`
2. Göreve başlamadan önce okunacak dosyalar
3. Güncellenecek veya oluşturulacak dosyaların tam listesi
4. Her dosyaya eklenecek, değiştirilecek veya kaldırılacak içerik
5. Korunması gereken mevcut kararlar ve içerikler
6. Gerekli kod, test, veri sızıntısı ve tutarlılık kontrolleri
7. Beklenen commit veya pull request özeti
8. Görev sonunda raporlanacak değiştirilen dosyalar, testler, açık sorular ve sıradaki görev

Belge güncellemesi gerekmeyen bir görüşmede, sohbet bunu açıkça belirtmelidir. Kesin karar oluştuğu halde Codex devir talimatı verilmeden konu tamamlanmış kabul edilmez.

Codex görevi tamamlandıktan sonra GitHub'daki güncel dosyalar tekrar okunmalı; proje durumu sohbet hafızasına veya eski dosya kopyalarına göre değerlendirilmemelidir.
