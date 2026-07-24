# DECISIONS

Bu dosya yalnızca kesinleşmiş kararları içerir. Geçici fikirler ve henüz değerlendirilmemiş öneriler buraya eklenmez.

## Kesinleşmiş Kararlar

### D001 — Proje Amacı

BİST hisseleri arasından önümüzdeki 2-3 işlem günü içinde en az %5 yükselme ihtimali yüksek olan hisseleri belirleyen ve sıralayan bir makine öğrenmesi sistemi geliştirilecektir.

### D002 — Ana Model

Yalnızca LightGBM Classifier kullanılacaktır.

### D003 — Model Çıktısı

Model her hisse için pozitif sınıf olasılığı üretecektir.

Bu olasılık:

- `P(+%5)` olarak yorumlanacaktır.
- Hisseleri günlük sıralamak için kullanılacaktır.
- İlk 5-10 hisseyi seçmek için temel skor olacaktır.

### D004 — İlk Sürümde Kullanılmayacak Modeller

İlk sürümde aşağıdakiler kullanılmayacaktır:

- XGBoost
- Logistic Regression
- Random Forest
- Başka benchmark modeller
- Ensemble
- Ayrı ranking modeli
- Derin öğrenme modelleri

### D005 — Doğrulama Yöntemi

Random train-test split kullanılmayacaktır.

Model zaman sıralı walk-forward validation ile değerlendirilecektir. Her test döneminde model yalnızca o tarihten önceki verilerle eğitilecektir.

### D006 — Accuracy Kullanımı

Accuracy hesaplanacak ancak tek başına başarı kriteri olmayacaktır.

Precision, Recall, F1-score, ROC-AUC, PR-AUC, Precision@5, Precision@10, ortalama getiri, net getiri ve maximum drawdown da değerlendirilecektir.

### D007 — İlk Sürüm Kapsamı

İlk sürümde fiyat, hacim, endeks, sektör ve likidite verileri kullanılacaktır.

İlk sürümde haber, KAP metinleri, sosyal medya, LLM tabanlı feature'lar ve otomatik emir gönderme kullanılmayacaktır.

### D008 — Karmaşıklık İlkesi

Önce sade ve çalışan sistem kurulacaktır. Yeni model, veri kaynağı veya feature grubu yalnızca ölçülebilir katkı sağlıyorsa eklenecektir.

### D009 — Veri Belgeleri

Gerçek veri kaynağı ve sütunlar görülmeden ayrıntılı `DATA_DICTIONARY.md` hazırlanmayacaktır.

Feature'lar, kullanılabilir gerçek veri alanları görüldükten sonra `FEATURE_CATALOG.md` dosyasına yazılacaktır.

Model deneyleri başlamadan `EXPERIMENT_LOG.md` oluşturulmayacaktır.

### D010 — Tahmin ve Giriş Zamanı

**Karar:**  
Tahmin, `T` işlem günü piyasası kapandıktan ve günlük veriler tamamlandıktan sonra üretilecektir. Feature'larda yalnızca `T` günü ve öncesinde mevcut bilgiler kullanılacaktır. İşleme `T+1` işlem gününün açılış fiyatından girilecektir.

**Gerekçe:**  
Kapanış verileriyle tahmin üretip aynı kapanış fiyatından işlem yapmak gerçekçi değildir. Sonraki gün açılışı, günlük OHLC verileriyle tekrarlanabilir ve veri sızıntısı içermeyen bir giriş kuralıdır.

**Etkilenen alanlar:**  
Feature kullanılabilirlik zamanı, label, tahmin sistemi ve backtest.

**Tarih:**  
2026-07-24

### D011 — Tahmin Ufku ve Pozitif Label

**Karar:**  
Tahmin ufku, giriş günü dahil `T+1`, `T+2` ve `T+3` olmak üzere üç Borsa İstanbul işlem günüdür.

Giriş fiyatı:

```text
entry_price = open[T+1]
```

Hedef fiyat:

```text
target_price = entry_price × 1.05
```

Gerçek emir ve backtest simülasyonunda hedef fiyat, geçerli fiyat adımına aşağı düşmeyecek şekilde yukarı yuvarlanacaktır.

Pozitif label formülü:

```text
label = 1, eğer max(high[T+1], high[T+2], high[T+3]) >= target_price
label = 0, aksi halde
```

**Gerekçe:**  
Üç günlük pencere proje amacıyla uyumludur. Günlük `high` kullanımı, girişten sonra hedef fiyat seviyesinde bekleyen limit satış emri bulunduğu işlem senaryosunu temsil eder.

**Etkilenen alanlar:**  
Label üretimi, sınıf dağılımı, model çıktısının yorumu ve backtest.

**Tarih:**  
2026-07-24

### D012 — Çıkış Kuralları

**Karar:**  
Hedefe ulaşılması halinde işlem, hedefe ilk ulaşılan gün `target_price` üzerinden kapatılmış kabul edilecektir.

Hedef üç günlük tahmin ufku içinde gerçekleşmezse işlem `T+3` kapanış fiyatından kapatılacaktır.

İlk sürümde stop-loss kullanılmayacaktır.

**Gerekçe:**  
Sabit giriş ve çıkış kuralları label ile backtestin tekrarlanabilir olmasını sağlar. Günlük OHLC verilerinde hedef ve stop seviyelerinin gün içindeki gerçekleşme sırası bilinmediği için ilk sürüme stop-loss eklenmeyecektir.

**Etkilenen alanlar:**  
Backtest, işlem getirisi, komisyon ve slippage hesabı, risk metrikleri.

**Tarih:**  
2026-07-24

### D013 — İşlem Görmeme, Tavan Fiyat ve Eksik Veri

**Karar:**  
Aşağıdaki kurallar uygulanacaktır:

- `T+1` açılış fiyatı yoksa veya hisse işlem görmediyse pozisyona girilmez; kayıt negatif label yapılmaz ve `NA` olarak dışarıda bırakılır.
- Hisse `T+1` açılışında tavan fiyatındaysa ve alışın gerçekleştiği doğrulanamıyorsa kayıt işlem evreninden çıkarılır.
- Giriş sonrasında işlem görmeyen bir günde hedefe ulaşılmış kabul edilmez.
- Hedef gerçekleşmemişken `T+3` günü çıkış yapılamıyorsa çıkış, hissenin işlem gördüğü ilk sonraki günün açılışına ertelenir ve bu durum ayrıca işaretlenir.
- Veri sağlayıcı kaynaklı eksik veya bozuk OHLC kayıtları eğitim ve backtestten çıkarılır; veri kalitesi raporunda sayılır.
- Tahmin ufku, hissenin işlem gördüğü günlere göre değil Borsa İstanbul işlem takvimine göre sayılır.

**Gerekçe:**  
Gerçekleştirilemeyen işlemleri negatif örnek olarak kullanmak model hedefini bozar. İşlem yapılabilirlik ile fiyat hareketinin birbirinden ayrılması gerekir.

**Etkilenen alanlar:**  
Veri temizleme, label üretimi, işlem evreni ve backtest.

**Tarih:**  
2026-07-24

### D014 — Label ve Net Getiri Ayrımı

**Karar:**  
`%5 yükseliş` labelı brüt fiyat hareketine göre oluşturulacaktır. Komisyon ve slippage labela dahil edilmeyecek; yalnızca backtest ve net portföy getirisi hesaplarında uygulanacaktır.

**Gerekçe:**  
Labelın piyasa hareketini ölçmesi, işlem maliyetlerinin ise strateji performansında ayrı değerlendirilmesi modeli daha anlaşılır ve karşılaştırılabilir kılar.

**Etkilenen alanlar:**  
Label, backtest, net getiri ve deney karşılaştırmaları.

**Tarih:**  
2026-07-24

### D015 — Merkezi GitHub Kaynağı ve Belge Güncelleme Kuralı

**Karar:**  
Projenin güncel ve bağlayıcı belgeleri `https://github.com/enesmertturkoglu/bist-ml-model` reposunda tutulacaktır. GitHub reposundaki dosyalar projenin tek doğru kaynağıdır.

Her kesin teknik karar veya tamamlanan ana aşama sonrasında:

- Kesinleşen kararlar `DECISIONS.md` dosyasına işlenecektir.
- Mevcut aşama, tamamlanan işler ve sıradaki görevler `PROJECT_STATUS.md` dosyasında güncellenecektir.
- Veri alanları, feature'lar ve deneylerle ilgili belgeler gerektiğinde aynı repoda güncellenecektir.
- Yeni bir teknik çalışmaya başlamadan önce ilgili dosyaların GitHub'daki en güncel sürümü okunacaktır.
- Sohbetlere yüklenen veya geçici çalışma alanlarında oluşturulan dosya kopyaları bağlayıcı kabul edilmeyecektir.

**Gerekçe:**  
Sohbetler arasında farklı dosya kopyalarının oluşmasını ve proje durumunun tutarsızlaşmasını önlemek için merkezi, sürümlenmiş ve bütün sohbetlerden erişilebilir tek bir kaynak gereklidir.

**Etkilenen alanlar:**  
Proje yönetimi, karar kaydı, durum takibi, veri belgeleri, feature kataloğu ve deney kayıtları.

**Tarih:**  
2026-07-24

### D016 — ChatGPT–Codex Çalışma Modeli ve Zorunlu Devir Talimatı

**Karar:**  
Projenin teknik kararları ve proje yönetimi ChatGPT sohbetlerinde yürütülecek; GitHub dosyalarının düzenlenmesi, kod geliştirme, test, commit ve pull request işlemleri Codex tarafından gerçekleştirilecektir.

Bir sohbet sırasında kesin bir karar verildiğinde, tamamlanan iş nedeniyle proje durumu değiştiğinde veya herhangi bir proje belgesinin güncellenmesi gerektiğinde sohbet, kullanıcıya doğrudan Codex'e kopyalanabilecek bir `Codex Devir Talimatı` vermek zorundadır.

Codex devir talimatı aşağıdakileri açıkça belirtmelidir:

- Repo adresi: `https://github.com/enesmertturkoglu/bist-ml-model`
- Göreve başlamadan önce okunacak dosyalar
- Güncellenecek veya oluşturulacak dosyalar
- Her dosyada yapılacak kesin değişiklikler
- Korunması gereken mevcut kararlar ve içerikler
- Gerekli kodlama, test, veri sızıntısı ve belge tutarlılığı kontrolleri
- Beklenen commit veya pull request kapsamı
- Görev sonunda raporlanacak değiştirilen dosyalar, çalıştırılan testler, açık sorular ve sıradaki görev

Kesin karar oluşmuş ancak gerekli Codex devir talimatı verilmemişse kararın uygulama ve dokümantasyon aşaması tamamlanmış sayılmayacaktır. Codex işlemi bittikten sonra doğrulama, GitHub reposundaki güncel dosyalar üzerinden yapılacaktır.

**Gerekçe:**  
ChatGPT karar ve değerlendirme konusunda, Codex ise gerçek repo üzerinde uygulama ve test konusunda kullanılacaktır. Standart bir devir talimatı, kararların belgelere eksiksiz aktarılmasını ve sohbetler arasında tutarsızlık oluşmamasını sağlar.

**Etkilenen alanlar:**  
Proje yönetimi, GitHub iş akışı, karar kaydı, durum takibi, kod geliştirme, test ve sohbetler arası devir.

**Tarih:**  
2026-07-25

## Henüz Kesinleşmemiş Kararlar

- Likidite filtresi
- Hisse evreni
- Günlük seçilecek hisse sayısı
- Komisyon ve slippage varsayımları

## Yeni Karar Şablonu

```markdown
### DXXX — Karar Başlığı

**Karar:**  
Kesinleşen karar.

**Gerekçe:**  
Bu kararın verilme nedeni.

**Etkilenen alanlar:**  
Veri, label, feature, model, backtest veya canlı sistem.

**Tarih:**  
YYYY-MM-DD
```
