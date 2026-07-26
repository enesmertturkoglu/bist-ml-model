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

**Revizyon notu:** D017'nin hibrit fiyat kaynağı görev dağılımı D024 ile revize edilmiştir; karar geçmişi korunmuştur.

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

### D020 — Tarihsel Veri Başlangıcının Revizyonu

**Karar:**  
İlk sürümde model eğitimi, label üretimi ve backtest için kullanılacak ana tarihsel dönem `2020-03-13` tarihinde başlayacaktır.

Daha önce belirlenen `2016-01-04` başlangıç tarihi bu kararla geçersiz kılınmıştır.

Uygulama kuralları:

- `2020-03-13` öncesindeki kayıtlar eğitim örneği, label veya backtest işlemi olarak kullanılmayacaktır.
- Feature hesaplarının gerektirdiği geçmiş için `2020-03-13` öncesinden sınırlı warm-up verisi çekilebilir.
- Warm-up kayıtları eğitim, label veya backtest evrenine dahil edilmeyecektir.
- Sonradan halka arz edilen hisseler kendi ilk geçerli işlem tarihlerinden başlayacaktır.
- Eksik geçmiş yapay olarak doldurulmayacaktır.
- Veri toplama başlangıcı, model örneği başlangıcı ve walk-forward test başlangıcı ayrı ayarlar olarak tutulacaktır.
- Walk-forward test başlangıcı daha sonra ayrıca kesinleştirilecektir.

**Gerekçe:**  
`2020-03-13` öncesindeki fiyat marjlarının ve tarihsel işlem esaslarının yeniden oluşturulması ilk sürüm için gereksiz veri mühendisliği karmaşıklığı yaratmaktadır. `2020-03-13` başlangıcı tavan açılış kontrolünün sade ve denetlenebilir biçimde uygulanmasını sağlar.

**Etkilenen alanlar:**  
Veri toplama, feature engineering, label, walk-forward validation, backtest ve merkezi config.

**Tarih:**  
2026-07-26

### D021 — Tahmini Tavan Fiyatı ve Tavan Açılış Tespiti

**Karar:**  
`2020-03-13` ve sonrasındaki model evreninde bulunan normal BİST adi payları için günlük fiyat marjı `%10` kabul edilecektir.

Tavan açılış tespitinde sabit `%9,90`, `%9,95` veya benzeri bir getiri eşiği kullanılmayacaktır.

Tahmini üst fiyat limiti aşağıdaki yöntemle hesaplanacaktır:

```text
base_price = önceki geçerli işlem gününün İş Yatırım ham kapanış fiyatı
raw_upper_limit = base_price × 1.10
estimated_upper_limit = raw_upper_limit değerinin ilgili tarihte ve fiyat seviyesinde geçerli fiyat adımına aşağı yuvarlanmış hâli
```

Tavan açılış koşulu:

```text
is_limit_open = yFinance ham açılış fiyatı estimated_upper_limit değerine eşitse
```

Tavan hesabında düzeltilmiş fiyatlar kullanılmayacaktır.

Ondalık kayan nokta hataları nedeniyle eşitlik kontrolünde yalnızca küçük bir sayısal tolerans kullanılacaktır. Bir tam fiyat adımı büyüklüğünde tolerans kullanılmayacaktır.

Bu yaklaşım nedeniyle gerçekleşen yüzdesel artışın `%10`dan veya `%9,90`dan düşük görünmesi, kaydın tavan olmadığı anlamına gelmez.

Örnek:

```text
base_price = 1,03
raw_upper_limit = 1,03 × 1,10 = 1,133
fiyat_adımı = 0,01
estimated_upper_limit = 1,13
gerçekleşen oran ≈ %9,71
```

Bu açılış tavan kabul edilecektir.

Tavan açıldığı belirlenen kayıt için:

- Pozisyona girilmiş kabul edilmeyecektir.
- Kayıt negatif label yapılmayacaktır.
- D013 uyarınca işlem ve label evreninde `NA` olarak dışarıda bırakılacaktır.
- Günlük hacim bulunması veya açılış fiyatında işlem gerçekleşmiş olması, alışın gerçekleştirilebilir olduğunu kanıtlamayacaktır.

Aşağıdaki durumlarda standart tavan hesabı uygulanmayacak ve kayıt `NA` veya özel inceleme durumuna alınacaktır:

- Önceki geçerli ham kapanış bulunmuyorsa
- İlk işlem günü ise
- Serbest marj uygulanıyorsa
- Normal adi pay dışında bir araçsa
- Kurumsal işlem nedeniyle önceki kapanış doğrudan baz fiyat olarak kullanılamıyorsa
- Kaynaklar arasında baz fiyat veya açılış için önemli uyuşmazlık varsa
- İlgili tarihte geçerli fiyat adımı güvenilir biçimde belirlenemiyorsa

Fiyat adımı kuralları tarih etkili biçimde merkezi bir tabloda tutulacaktır. Bu görevde söz konusu tablo veya hesaplama kodu oluşturulmayacaktır.

**Gerekçe:**  
Üst fiyat limiti, `%10` hesaplamasının geçerli fiyat adımına aşağı yuvarlanmasıyla oluşur. Bu nedenle gerçek tavan getirisi fiyat seviyesine göre `%10`un altında görünebilir. Sabit bir yüzdesel tolerans düşük fiyatlı hisselerde gerçek tavanları kaçırabilir veya tavan olmayan açılışları yanlış sınıflandırabilir.

Hesaplanan fiyat seviyesine göre tavan tespiti yapmak hem sade hem de sabit `%9,90` eşiğinden daha doğrudur.

**Etkilenen alanlar:**  
Veri temizleme, tavan fiyatı hesaplama, işlem yapılabilirlik, label, backtest ve veri kalite kontrolleri.

**Tarih:**  
2026-07-26

**Revizyon notu:** D021'in İş Yatırım ham kapanışını baz fiyat ve yFinance sağlayıcı açılışını karşılaştırma fiyatı olarak kullanan bölümleri D024 ile revize edilmiştir; karar geçmişi korunmuştur.

### D022 — T+1 Temel İşlem Yapılabilirlik ve Hacim Kontrolü

**Karar:**  
`T+1` açılışında giriş yapılabilirliği değerlendirilirken aşağıdaki sade ve kapsayıcı kurallar uygulanacaktır:

- yFinance ham açılış fiyatı bulunmuyorsa veya geçerli pozitif bir değer değilse pozisyona girilmeyecek; kayıt negatif label yapılmadan `NA` bırakılacaktır.
- İş Yatırım TL işlem hacmi ile yFinance işlem gören pay adedi birlikte sıfırsa ilgili gün işlem gerçekleşmemiş kabul edilecek ve kayıt `NA` bırakılacaktır.
- İki hacim alanından en az biri pozitifse kayıt yalnızca hacim nedeniyle elenmeyecektir.
- Hacim alanlarından biri pozitif, diğeri sıfır veya eksikse kayıt işlem evreninde tutulacak; yalnızca veri kalite uyarısı ile işaretlenecektir.
- Pozitif fakat düşük hacim ilk sürümde otomatik eleme nedeni olmayacaktır.
- Likidite eşiği bu kararın parçası değildir; daha sonra ayrı bir karar ve kontrollü deney olarak değerlendirilecektir.
- D021’e göre tavan açıldığı belirlenen kayıtlar `NA` bırakılacaktır.
- İlk işlem günü, serbest marj uygulaması veya kurumsal işlem nedeniyle standart `%10` tavan hesabının güvenilir olmadığı kayıtlar `NA` veya özel inceleme durumuna alınacaktır.
- Hacim uyuşmazlıkları model feature’ı olarak kullanılmayacak; yalnızca veri kalite kontrolü ve raporlama amacıyla saklanacaktır.

Her kayıt için mümkün olduğunca aşağıdaki durum alanları ayrı tutulacaktır:

```text
entry_eligible
entry_exclusion_reason
volume_quality_flag
```

Önerilen neden kodları:

```text
NO_OPEN
NO_TRADE
LIMIT_OPEN
FIRST_TRADING_DAY
SPECIAL_MARGIN
CORPORATE_ACTION_SUSPECTED
INVALID_OHLC
SOURCE_VOLUME_CONFLICT
```

İki hacim alanının da eksik olduğu ancak açılış fiyatının bulunduğu durum için bu aşamada yeni bir kesin kural oluşturulmayacaktır. Bu durum veri kabul testinde ölçülerek açık soru olarak korunacaktır.

**Gerekçe:**
Hacim verilerindeki tek kaynaklı eksiklikler nedeniyle gereksiz sayıda hisse ve eğitim örneği kaybetmemek amaçlanmaktadır. Günlük hacmin düşük olması tek başına girişin gerçekleşmediğini göstermez ve uygulanabilir minimum hacim, portföy ile emir büyüklüğüne bağlıdır. Bu nedenle ilk sürümde hacim kontrolü katı bir likidite filtresi değil, temel işlem gerçekleşme ve veri kalite kontrolü olarak kullanılacaktır.

Gerçekten işlem gerçekleşmediğini güçlü biçimde gösteren açılış eksikliği veya iki hacim değerinin birlikte sıfır olması ise `NA` için yeterli kabul edilecektir.

**Etkilenen alanlar:**
Veri temizleme, işlem yapılabilirlik, label üretimi, backtest, veri kalite raporları ve ilerideki likidite filtresi deneyleri.

**Tarih:**
2026-07-26

**Revizyon notu:** D022'de geçen yFinance ham açılış fiyatı referansları D024 sonrasında `yf_nominal_open` olarak uygulanır. Hacim ve işlem yapılabilirlik kuralları değişmemiştir.

### D023 — Özel İşlem Durumlarının KAP Olmadan Ele Alınması

**Karar:**  
İlk sürümde kurumsal işlem, ilk işlem günü ve serbest marj istisnalarının tespitinde KAP verisi kullanılmayacaktır.

Kurumsal işlem tespitinde aşağıdaki ücretsiz mevcut kaynaklar kullanılacaktır:

- yFinance temettü kayıtları
- yFinance bölünme ve diğer action kayıtları
- İş Yatırım ham ve düzeltilmiş fiyat serileri arasındaki düzeltme katsayısının değişimi

`T+1`, `T+2` veya `T+3` günlerinden herhangi birinde kaynaklardan en az biri temettü, bölünme, bedelli, bedelsiz veya benzeri fiyat düzeltmesine yol açan kurumsal işlem işareti gösteriyorsa ilgili tahmin kaydı:

- Negatif label yapılmayacaktır.
- Model eğitim evreninden çıkarılacaktır.
- Backtestte gerçekleşmiş işlem sayılmayacaktır.
- `CORPORATE_ACTION_WINDOW` nedeni ile `NA` bırakılacaktır.

Önceki geçerli İş Yatırım ham kapanış fiyatı bulunmuyorsa standart `%10` tavan hesabı uygulanmayacak ve kayıt `NO_PREVIOUS_CLOSE` veya `FIRST_TRADING_DAY_OR_NO_HISTORY` nedeniyle `NA` bırakılacaktır.

Aşağıdaki durumlardan biri oluşursa kayıt standart dışı işlem durumu olarak kabul edilerek `NA` bırakılacaktır:

- Ham açılış fiyatının hesaplanan üst fiyat limitinden yüksek olması
- Günlük ham en yüksek fiyatın hesaplanan üst fiyat limitinden yüksek olması
- Standart `%10` tavan hesabının güvenilir biçimde uygulanamaması

Bu kayıtlar `SPECIAL_MARGIN_OR_CORPORATE_ACTION` durumuyla işaretlenecektir.

İlk sürümde kapsamlı tarihsel serbest marj listesi oluşturulmayacaktır. Standart `%10` aralığında kalan ve mevcut iki kaynakla tespit edilemeyen serbest marj durumları bilinen veri sınırlaması olarak kabul edilecektir.

KAP veya başka bir resmî metin kaynağı ilk sürümün zorunlu veri kaynağı olmayacaktır. KAP doğrulaması ancak daha sonraki geliştirme veya sorunlu kayıt inceleme aşamasında değerlendirilebilir.

**Gerekçe:**  
İlk sürümün sade, ücretsiz ve tekrarlanabilir kalması amaçlanmaktadır. İş Yatırım ile yFinance kurumsal işlemlerin önemli bölümünü tespit etmek için yeterli başlangıç sinyalleri sağlamaktadır.

Belirsiz kayıtları normal işlem olarak kullanmak yerine `NA` bırakmak, kurumsal işlemlerden kaynaklanan yapay fiyat hareketlerinin label ve backtest sonuçlarını bozmasını sınırlar.

**Etkilenen alanlar:**  
Veri temizleme, kurumsal işlem tespiti, tavan hesabı, label üretimi, backtest ve veri kalite raporları.

**Tarih:**  
2026-07-26

**Revizyon notu:** D023'te fiyat hesapları için geçen önceki İş Yatırım ham kapanışı, ham açılış ve ham en yüksek fiyat referansları D024 sonrasında sırasıyla `yf_nominal_close`, `yf_nominal_open` ve `yf_nominal_high` olarak uygulanır. İş Yatırım ham/düzeltilmiş fiyatları yalnız kurumsal işlem sinyali, çapraz kaynak kalite kontrolü ve denetim amacıyla kullanılır.

### D024 — Tek Fiyat Kaynağı ve yFinance Nominal Fiyat Normalizasyonu

**Karar:**
İlk sürümde giriş, label, çıkış ve tavan fiyatı hesaplarında kullanılan open, high, low ve close değerlerinin tamamı yFinance'tan alınacaktır.

yFinance tarafından sağlanan geçmiş OHLC değerleri splitler nedeniyle güncel fiyat ölçeğine taşınabildiği için orijinal sağlayıcı fiyatları değişmeden saklanacak ve tarihsel nominal fiyatlar yFinance `Stock Splits` verileriyle ayrıca oluşturulacaktır.

Nominal fiyat dönüşümü:

```text
yf_nominal_price[t]
    =
yf_provider_price[t]
    ×
t tarihinden sonra gerçekleşen geçerli split oranlarının kümülatif çarpımı
```

Split gününün kendi oranı aynı günün fiyatına uygulanmayacaktır.

Ana fiyat alanları:

```text
yf_nominal_open
yf_nominal_high
yf_nominal_low
yf_nominal_close
```

Bu alanlar şu işlemlerde kullanılacaktır:

- `T+1` giriş fiyatı
- `T+1–T+3` high değerleriyle label hesabı
- `T+3` kapanış çıkışı
- Önceki kapanıştan tavan fiyatı hesabı
- Tavan açılış kontrolü
- OHLC tutarlılık kontrolü

Tavan hesabında önceki geçerli işlem gününün `yf_nominal_close` değeri baz fiyat olacak; `yf_nominal_open`, fiyat adımına aşağı yuvarlanan `%10` tahmini üst limite yalnız küçük kayan nokta toleransıyla karşılaştırılacaktır. Bir tam fiyat adımı toleransı kullanılmayacaktır.

İş Yatırım fiyatları ana fiyat hesabında kullanılmayacaktır. İş Yatırım ana işlem takvimi, TL işlem hacmi, endeks, ağırlıklı ortalama fiyat, piyasa değeri, halka açık piyasa değeri ve veri kalite çapraz kontrolü için kullanılmaya devam edecektir.

İş Yatırım ile yFinance fiyat uyuşmazlıkları label veya backtest satırını otomatik dışlamayacak; `cross_source_price_warning` veri kalite uyarısı olarak saklanacaktır.

Split normalizasyonunda gelecekte gerçekleşen split oranlarının kullanılması yalnız geçmiş fiyat birimini dönemin nominal ölçeğine geri kurmak içindir. Bu oranlar:

- Model feature'ı yapılmayacaktır.
- LightGBM'e verilmeyecektir.
- Tahmin olasılığını etkilemeyecektir.
- Alım satım sinyali olarak kullanılmayacaktır.
- Yalnız veri normalizasyonu amacıyla kullanılacaktır.

Aynı split faktörü open, high, low ve close alanlarının tamamına uygulanacaktır. D023 gereği `T+1–T+3` penceresinde kurumsal işlem bulunan satırlar `CORPORATE_ACTION_WINDOW` ile `NA` bırakılacaktır.

Ham yFinance yanıtları ve normalizasyonda kullanılan split verileri sürümlenerek saklanacaktır. Sağlayıcının geçmiş verileri daha sonra değiştirmesi halinde geçmiş deneylerin tekrarlanabilirliği korunacaktır.

Bu karar D017'deki fiyat kaynağı görev dağılımını ve D021'deki tavan baz fiyatı kaynağını revize eder. D022'deki açılış kontrolleri yFinance nominal açılışıyla uygulanır; D023'ün kurumsal işlem penceresi kuralları korunur.

**Gerekçe:**
Kaynak kabul testinde yFinance open ile İş Yatırım ham high, low ve close fiyatlarının split öncesi dönemlerde farklı fiyat ölçeklerinde bulunduğu görülmüştür.

Tüm OHLC alanlarının aynı kaynaktan alınması giriş, label ve çıkış fiyatlarının aynı ölçekte kalmasını sağlar. İş Yatırım'ın açılış fiyatı sağlamaması nedeniyle tüm fiyat alanları için İş Yatırım'ın tek kaynak olarak kullanılması mümkün değildir.

**Etkilenen alanlar:**
Veri toplama, fiyat normalizasyonu, tavan hesabı, işlem yapılabilirlik, label üretimi, backtest, veri kalite kontrolü ve tekrarlanabilirlik.

**Tarih:**
2026-07-26

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
