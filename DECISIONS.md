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

### D017 — İlk Sürüm Veri Kaynakları

**Karar:**  
İlk sürümde ücretsiz hibrit veri yaklaşımı kullanılacaktır.

Ana veri kaynağı İş Yatırım’ın internet sitesinden veri alan `isyatirimhisse` kütüphanesi olacaktır.

İş Yatırım kaynağından öncelikle şu alanlar kullanılacaktır:

- Ham en yüksek, en düşük ve kapanış fiyatları
- Düzeltilmiş en yüksek, en düşük ve kapanış fiyatları
- TL işlem hacmi
- Ağırlıklı ortalama fiyat
- BIST endeks verileri
- Piyasa değeri ve halka açık piyasa değeri gibi mevcut yardımcı alanlar
- Ana işlem günü takvimi

yFinance tamamlayıcı veri kaynağı olacaktır.

yFinance kaynağından öncelikle şu alanlar kullanılacaktır:

- Açılış fiyatı
- İşlem gören pay adedi
- İş Yatırım fiyatları için bağımsız çapraz kontrol

Kaynaklar tarih ve hisse kodu üzerinden birleştirilecektir.

Birleştirme kuralları:

1. Ana işlem takvimi İş Yatırım verisinden oluşturulacaktır.
2. yFinance’te bulunup İş Yatırım’da bulunmayan bir tarih otomatik olarak geçerli işlem günü kabul edilmeyecektir.
3. İş Yatırım’da bulunup yFinance’te bulunmayan bir tarihte açılış fiyatı eksik kabul edilecek; giriş ve label hesabı `NA` olarak dışarıda bırakılacaktır.
4. Ham high, low veya close değerleri kaynaklar arasında geçerli fiyat adımından daha fazla farklıysa kayıt veri kalite kontrolüne alınacaktır.
5. Çözülemeyen önemli fiyat uyuşmazlıkları eğitim ve backtest verisine dahil edilmeyecektir.
6. yFinance fiyatları otomatik düzeltilmiş şekilde kullanılmayacaktır. Ham fiyatlar ayrı, düzeltilmiş fiyatlar ayrı tutulacaktır.
7. yFinance tarih aralığında bitiş tarihinin hariç olması dikkate alınacaktır.
8. Her iki kaynaktan alınan ham cevaplar sonradan denetlenebilmesi için değişmeden saklanacaktır.

Tavan fiyatı, işlem durumu ve tarihsel hisse evreni bu iki kaynak tarafından tam olarak çözülmemektedir. Bu konular ayrı kararlar olarak ele alınacaktır.

**Gerekçe:**  
İş Yatırım verisi ham ve düzeltilmiş fiyatları, TL hacmi, AOF ve endeks bilgilerini birlikte sunmaktadır ancak açılış fiyatı sağlamamaktadır. yFinance açılış ve adet hacmi sağlamaktadır ancak işlem takvimi ve bazı geçmiş kayıtlarında tek başına güvenilir değildir. İki kaynağın birlikte kullanılması ilk sürüm için ücretsiz ve daha güvenilir bir veri yapısı sağlar.

THYAO örneğinde kaynakların fiyatları büyük ölçüde eşleşmiş; ancak iptal edilmiş işlem günü, eksik yarım işlem günü ve birkaç fiyat uyuşmazlığı tespit edilmiştir. Bu nedenle kaynaklardan biri tek başına kullanılmayacaktır.

**Etkilenen alanlar:**  
Veri toplama, veri birleştirme, label üretimi, feature engineering, veri kalite kontrolleri ve backtest.

**Tarih:**  
2026-07-25

### D018 — Tarihsel Veri Başlangıcı

**Karar:**  
İlk sürümde tarihsel piyasa verileri `2016-01-04` tarihinden itibaren toplanacaktır.

Bu tarih bütün hisseler için yapay bir başlangıç tarihi olarak uygulanmayacaktır:

- `2016-01-04` tarihinden sonra halka arz edilen hisseler kendi ilk geçerli işlem tarihlerinden başlayacaktır.
- Bir hissenin ilk işlem tarihinden önceki dönem geriye doğru doldurulmayacaktır.
- Eksik fiyat veya hacim geçmişi yapay değerlerle tamamlanmayacaktır.
- Model satırları, kullanılan feature’ların gerektirdiği en uzun geçmiş pencere tamamlandıktan sonra uygun hâle gelecektir.
- Veri toplama başlangıcı ile ilk walk-forward test tarihi ayrı ayarlar olarak tutulacaktır.
- İlk test dönemi, yeterli eğitim geçmişi bırakacak şekilde daha sonra kesinleştirilecektir.

**Gerekçe:**  
`2016-01-04`, BISTECH geçişi sonrasındaki ilk tam takvim yılının ilk işlem günüdür. Yaklaşık on yıllık veri; kur krizi, COVID dönemi, yüksek enflasyon ve farklı piyasa rejimlerini kapsarken daha eski piyasa yapılarından kaynaklanabilecek gereksiz veri karmaşıklığını sınırlar.

Veri başlangıcı ile test başlangıcını ayırmak, feature geçmişi ve model eğitimi için yeterli gözlem bırakılmasını sağlar.

**Etkilenen alanlar:**  
Veri toplama, veri saklama, feature başlangıçları, walk-forward validation, backtest ve merkezi config.

**Tarih:**  
2026-07-25

### D019 — İlk Sürüm Hisse Evreni

**Karar:**  
İlk sürümde hisse evreni, veri toplama ve model geliştirme çalışmasının başladığı tarihte Borsa İstanbul'da aktif olarak işlem gören paylardan oluşturulacaktır.

Bu güncel aktif hisse listesi, ilk sürümün bütün tarihsel veri dönemi boyunca sabit evren olarak kullanılacaktır.

Günümüzde kot dışı kalmış, devrolmuş, sona ermiş veya artık aktif olarak işlem görmeyen hisseler ilk sürüm evrenine dahil edilmeyecektir.

Bu yaklaşımın survivorship bias oluşturduğu açıkça kabul edilecek ve ilk sürüm sonuçları tam point-in-time tarihsel evren sonucu olarak sunulmayacaktır.

Güncel aktif bir hissenin geçmişte kod değiştirmiş olması halinde:

- Güncel kod ana kimlik olarak kullanılacaktır.
- Eski ve yeni kodlar resmi Borsa İstanbul veya KAP kod değişikliği kayıtlarıyla doğrulanacaktır.
- Doğrulanmış eski kodlar aynı sabit `security_id` altında güncel hisseyle eşleştirilecektir.
- Eski kod dönemindeki fiyat ve hacim verileri, ilgili geçerlilik tarihleri korunarak aynı menkul kıymetin geçmişine dahil edilecektir.
- Eski tarihlerin gerçek ticker bilgisi yeni kodla değiştirilmeden ayrıca saklanacaktır.

Yalnızca şirket adı benzerliği veya fiyat serisi benzerliği kod eşleştirmesi için yeterli kabul edilmeyecektir.

Birleşme, devir, bölünme veya yeni bir menkul kıymet oluşumu nedeniyle hukuki ve ekonomik devamlılık belirsizse geçmiş seriler otomatik olarak birleştirilmeyecektir. Bu kayıtlar manuel inceleme gerektiren istisnalar olarak işaretlenecektir.

İlk sürümde kullanılacak finansal araç kapsamı yalnızca Borsa İstanbul'da işlem gören şirket paylarıdır. ETF, yatırım fonu, varant, sertifika, rüçhan hakkı kuponu ve benzeri araçlar evrene dahil edilmeyecektir.

Point-in-time tarihsel evren oluşturulması sonraki bir geliştirme aşaması olarak korunacaktır. İleride point-in-time evrene geçildiğinde aynı model ve test dönemleriyle karşılaştırmalı bir deney yapılacaktır.

**Gerekçe:**  
Güncel aktif hisse listesinin kullanılması veri toplama, kod eşleştirme ve ilk model altyapısını sadeleştirir. Böylece fiyat toplama, veri temizleme, label üretimi ve walk-forward pipeline daha hızlı ve test edilebilir şekilde kurulabilir.

Bununla birlikte günümüzde aktif olmayan şirketlerin geçmiş veriden çıkarılması survivorship bias oluşturur. Bu nedenle karar bir doğruluk iddiası değil, bilinçli bir ilk sürüm kapsam daraltmasıdır.

Kod değiştiren güncel hisselerin eski kodlarının eşleştirilmesi, aktif evrende yer alan şirketlerin mevcut tarihsel verilerinin gereksiz yere kaybedilmesini önler.

**Etkilenen alanlar:**  
Veri toplama, hisse kimliği, veri temizleme, model eğitim evreni, walk-forward validation, backtest sonuçlarının yorumlanması ve ileride yapılacak point-in-time evren deneyi.

**Tarih:**  
2026-07-25

## Henüz Kesinleşmemiş Kararlar

- Likidite filtresi
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
