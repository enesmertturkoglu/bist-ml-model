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

### D025 — Model Eğitimi ve Günlük Tahmin Süreçlerinin Ayrılması

**Karar:**
İlk sürümde model eğitimi ile günlük tahmin üretimi birbirinden bağımsız iki süreç olacaktır.

Eğitim süreci kullanıcı tarafından açık bir eğitim komutuyla çalıştırılacaktır. Her eğitimde:

- Yalnız belirtilen `as_of_date` tarihinde mevcut olan veriler kullanılacaktır.
- Üç işlem günlük label penceresi tamamen sonuçlanmış kayıtlar eğitime alınacaktır.
- LightGBM modeli sıfırdan eğitilecektir.
- Incremental learning kullanılmayacaktır.
- Yeni ve değişmez bir model sürümü oluşturulacaktır; eski model sürümleri silinmeyecek veya sessizce üzerine yazılmayacaktır.
- Model dosyası, metadata, sıralı feature listesi, config snapshot'ı ve eğitim/doğrulama metrikleri birlikte saklanacaktır.

Tahmin süreci, seçilen işlem günü için daha önce eğitilmiş bir model sürümünü kullanacaktır. Tahmin sırasında:

- Tahmin tarihinde mevcut en güncel veri ve feature'lar kullanılacaktır.
- Model yeniden eğitilmeyecektir.
- Kullanıcı belirli bir model sürümünü seçebilecek veya aktif model sürümünü kullanabilecektir.
- Hisseler LightGBM pozitif sınıf olasılığına göre sıralanacaktır.
- `as_of_date`, `model_version`, kullanılan veri snapshot kimlikleri ve tahmin üretim zamanı sonuçla birlikte kaydedilecektir.

Her model sürümünde en az aşağıdaki bilgiler tutulacaktır:

```text
model_version
training_timestamp
training_start_date
training_end_date
latest_available_label_date
data_snapshot_ids
data_snapshot_checksums
feature_names_in_order
lightgbm_parameters
random_seed
label_decision_version
code_commit_sha
training_row_count
positive_class_rate
training_metrics
validation_metrics
```

Tahmin sırasında üretilen feature isimleri, sayısı ve sırası model metadata'sıyla tam eşleşmelidir. Herhangi bir uyuşmazlıkta sessizce tahmin yapılmayacak ve açık hata üretilecektir.

İlk sürümde MLflow veya benzeri ek bir model yönetim sistemi kullanılmayacaktır. Model kayıtları sade, dosya tabanlı, sürümlü ve değişmez bir yapıda tutulacaktır.

**Gerekçe:**
Eğitimi günlük tahminden ayırmak, aynı model sürümüyle tekrarlanabilir tahmin üretmeyi; model, veri ve kod sürümleri arasındaki bağı denetlenebilir biçimde kaydetmeyi sağlar. Label penceresi tamamlanmamış kayıtların eğitime alınmaması veri sızıntısını önler. Değişmez model sürümleri ise yeni eğitimin geçmiş sonuçları sessizce değiştirmesini engeller.

**Etkilenen alanlar:**
Veri snapshot ve checksum yapısı, merkezi config, label uygunluğu, feature şeması, LightGBM eğitimi, model kayıt yapısı, günlük tahmin, sonuç raporlama ve tekrarlanabilirlik.

**Tarih:**
2026-07-26

### D026 — Tarih-Etkin BİST Pay Piyasası Fiyat Adımı Tarifeleri

**Karar:**
Standart şirket paylarının fiyat adımı, repoda sürümlenen ve resmî Borsa İstanbul kaynağına bağlanan `reference_data/bist_equity_tick_sizes_v1.csv` tablosundan `entry_date`, `instrument_type=EQUITY` ve fiyat adımına yuvarlanmamış üst limit fiyatı ile çözümlenecektir.

Kaynak, Borsa İstanbul'un `28.08.2023` tarihli ve `E-18454353-100.04.02-19412` sayılı “Pay Piyasası ve Vadeli İşlem ve Opsiyon Piyasası İşleyiş Esaslarında Yapılan Değişiklikler” duyurusudur. Duyurunun “ESKİ METİN” tablosu önceki dört kademeyi, “YENİ METİN” tablosu sekiz kademeyi ve duyuru metni yeni tarifenin `06.11.2023` yürürlük tarihini doğrular. İndirilen resmî PDF'nin SHA-256 özeti `cb0a1e0091d799186e9ae67b7badc8483f2166d9b66ed03c7bd55e205a0702d3` olarak kaydedilmiştir.

Proje kapsamındaki tarih-etkin rejimler:

| Rejim | Geçerlilik | Fiyat bandı (alt dahil, üst hariç) | Fiyat adımı |
| --- | --- | --- | --- |
| `BIST_EQUITY_PRE_20231106_V1` | `2020-03-13`–`2023-11-05` | `[0.01, 20)` | `0.01 TRY` |
|  |  | `[20, 50)` | `0.02 TRY` |
|  |  | `[50, 100)` | `0.05 TRY` |
|  |  | `[100, ∞)` | `0.10 TRY` |
| `BIST_EQUITY_FROM_20231106_V1` | `2023-11-06` ve sonrası | `[0.01, 20)` | `0.01 TRY` |
|  |  | `[20, 50)` | `0.02 TRY` |
|  |  | `[50, 100)` | `0.05 TRY` |
|  |  | `[100, 250)` | `0.10 TRY` |
|  |  | `[250, 500)` | `0.25 TRY` |
|  |  | `[500, 1000)` | `0.50 TRY` |
|  |  | `[1000, 2500)` | `1.00 TRY` |
|  |  | `[2500, ∞)` | `2.50 TRY` |

İlk rejimin `2020-03-13` başlangıcı tarifenin ilk kez yürürlüğe girdiği tarih iddiası değildir; projenin D020 ile kesinleşmiş model dönemi başlangıcıdır. Resmî 2023 belgesi dört kademeyi değişiklik öncesindeki “eski metin” olarak doğrular. Bu kapsam ayrımı referans tablosunun `notes` alanında da korunacaktır.

Standart üst limit hesabı aşağıdaki sırayla yapılacaktır:

```text
base_price = previous_valid_yf_nominal_close
raw_upper_limit = base_price × Decimal("1.10")
tick_rule = tariff.resolve(entry_date, "EQUITY", raw_upper_limit)
estimated_upper_limit = floor(raw_upper_limit / tick_size) × tick_size
```

Para ve fiyat adımı hesaplarında ikili kayan nokta aritmetiği kullanılmayacaktır. Sağlayıcı değerleri `Decimal(str(value))` ile hesap sınırında dönüştürülecek; `raw_upper_limit`, fiyat bandı seçimi ve içeri/aşağı yuvarlama `Decimal` ile yapılacaktır. Kayan nokta yalnız sağlayıcı/çıktı sınırında ve mevcut küçük karşılaştırma toleranslarında kullanılabilir; bir tam fiyat adımı tolerans değildir.

Tablo; kural seti, enstrüman türü, tarih aralığı, alt/üst fiyat sınırları, fiyat adımı, para birimi, resmî kurum/belge/tarih/yürürlük/URL, kaynak checksum'u ve açıklama alanlarını taşır. Her rejimde fiyat bantları boşluksuz ve çakışmasız, rejimler arasında tarihler ardışık olmalıdır. Gelecekteki değişiklikler mevcut satırların üzerine yazılmadan yeni `rule_set_id` ve tarih aralığıyla eklenecektir.

Tarih, fiyat veya enstrüman türü için tek bir kural çözülemiyorsa tarife tahmin edilmeyecek; `price_step_resolution_status=UNAVAILABLE`, `PRICE_STEP_UNAVAILABLE`, `requires_review=true` ve uygun olduğunda `entry_eligible=NA` davranışı korunacaktır. Pay dışındaki araçlar bu `EQUITY` tarifesini kullanamaz.

İş Yatırım fiyatları tavan hesabına alınmayacaktır. Baz fiyat yalnız önceki geçerli `yf_nominal_close`; karşılaştırılan açılış ve yüksek değerleri yalnız yFinance nominal OHLC olacaktır. Fiyat adımı ve tavan alanları işlem uygunluğu/denetim alanıdır, model feature'ı değildir.

**Gerekçe:**
Tarih-etkin, kaynak kimliği ve checksum'u kaydedilmiş bir tarife; üst limit hesabını tekrar üretilebilir kılar, 2023 değişikliğini doğru günde uygular ve doğrulanmamış sabit fiyat adımı kullanımını önler. `Decimal` kullanımı sınır değerlerinde ikili kayan noktanın yanlış fiyat bandı veya yanlış aşağı yuvarlama üretmesi riskini kaldırır.

**Etkilenen alanlar:**
Referans veri, merkezi config, tavan hesabı, D022 işlem uygunluğu temizlemesi, snapshot provenance alanları, durum raporları, veri sözlüğü ve birim testleri. Label, feature, model, tahmin ve backtest kapsamı değiştirilmemiştir.

**Tarih:**
2026-07-26

### D027 — Sade BİST Security Kimliği ve Tarih-Etkin Ticker Mapping

**Karar:**
Projenin kalıcı şirket payı kimliği `security_id` olacaktır. Resmî kaynaktan doğrulanıp `reference_data/bist_security_ticker_map_v1.csv` dosyasına açıkça eklenen eski ve yeni ticker'lar, dahil başlangıç ve dahil bitiş tarihleriyle aynı `security_id` altında birleştirilebilir. Şirket adı veya fiyat serisi benzerliğinden otomatik eşleme üretilmeyecektir.

Mapping'de bulunmayan güncel ticker yeni bir security kabul edilecek ve `SEC_<SHA256("BIST:EQUITY:" + NORMALIZED_TICKER) ilk 12 hex>` kuralıyla deterministik kimlik alacaktır. Normalizasyonda boşluklar temizlenir, ticker büyük harfe çevrilir ve `.IS` sağlayıcı uzantısı kaldırılır. Bu durum `AUTO_NEW_TICKER` olarak denetlenir; veri toplama veya model eğitimi için dışlama ya da durdurma nedeni değildir. Yeni halka arzlar da aynı davranışla sisteme girer.

Mapping güncel değilken kod değiştiren bir payın eski ve yeni ticker'ı geçici olarak iki security'ye ayrılabilir; bu risk bilinçli olarak kabul edilmiştir. Mapping daha sonra resmî kaynak ve geçiş tarihleriyle güncellendiğinde açık `security_id` otomatik kimliğin önüne geçer, seri yeniden hazırlanır ve sonraki model eğitimi yeni mapping sürümüyle yapılır. Kod kendi başına KAP veya Borsa İstanbul'dan eşleme kararı üretmez.

Provider sorguları her mapped ticker için yalnız geçerli tarih aralığına kırpılır. Kaynaktaki ticker `observed_ticker` olarak korunur; geçmiş ticker güncel ticker ile değiştirilmez. Aynı `security_id + trade_date` için mükerrer sağlayıcı satırında tarih-etkin açık mapping kaydı tercih edilir. Mapping sürümü ve checksum'u derived snapshot metadata'sına taşınır; mapping değişikliği eski snapshot'ı değiştirmeden yeni derived çıktı üretir.

İlk sürüm kimlik çözümünde ISIN kullanılmayacaktır; referans veriye, doğrulamaya veya pipeline'a eklenmeyecektir.

**Gerekçe:**
Sade, deterministik ve elle doğrulanan tarih-etkin mapping; ticker değişiklikleri boyunca serileri birleştirirken yeni halka arzların ve henüz eşlenmemiş ticker'ların veri akışını durdurmamasını sağlar. Otomatik benzerlik eşlemesinin reddedilmesi yanlış şirket birleşimi riskini sınırlar.

**Etkilenen alanlar:**
Aktif ticker evreni, provider sorgu planı, nominal security birleştirmesi, clean/label snapshot kimliği ve provenance alanları, ilerideki feature gruplaması, merkezi config, veri sözlüğü ve birim testleri.

**Tarih:**
2026-07-27

### D028 — baseline_v1 Feature Kataloğu ve Leakage Sözleşmesi

**Karar:**

`baseline_v1`, aşağıdaki gruplara dağılan tam 32 model feature'ından oluşacaktır:

- 6 fiyat getirisi ve momentum
- 4 trend ve fiyat konumu
- 5 volatilite ve fiyat aralığı
- 5 hacim ve likidite
- 3 mum/gün içi yapı
- 1 sınırlı teknik gösterge (`rsi_14_sma`)
- 4 piyasa/endeks ve relatif güç
- 4 kesitsel rank

Feature satırının tekil anahtarı `security_id + prediction_date` olacaktır. `security_id`, zorunlu kimlik ve rolling anahtarıdır; model feature'ı değildir. Feature girdisinde `security_id` bulunmuyorsa ticker tabanlı fallback yapılmayacak ve girdi açık hatayla reddedilecektir. Rolling hesaplar yalnız `security_id` içinde izole edilecektir.

Tahmin `T` seansı kapandıktan sonra üretildiği için T gününün tamamlanmış günlük verileri feature hesaplarına dahil edilebilir; `T+1` ve sonrasındaki fiyat, hacim, işlem uygunluğu, action ve label alanları yasaktır. Rolling pencereler global İş Yatırım BİST işlem takvimindeki ardışık oturumlara göre kurulacaktır. Eksik security oturumları son mevcut satırlara doğru sıkıştırılmayacak, forward-fill/back-fill veya sentetik satırla doldurulmayacaktır.

Fiyat feature'ları yalnız ölçekten bağımsız formüllerle `yf_provider_open`, `yf_provider_high`, `yf_provider_low` ve `yf_provider_close` alanlarından üretilecektir. Mutlak provider fiyat seviyesi model feature'ı değildir. `yf_nominal_*` alanları yalnız giriş, label, çıkış ve tavan işlemlerinde kalacak; `yf_future_split_factor`, split/action alanları ve bunların tarihleri modele girmeyecektir. Provider ve nominal OHLC aynı feature formülünde karıştırılmayacaktır.

Baseline hacim kaynağı İş Yatırım `is_tl_volume` alanıdır. Farklı birimdeki `yf_share_volume` baseline model feature'ı değildir. Eksik değer imputasyonu, tüm dönem standardizasyonu ve winsorization baseline feature üretiminde yapılmayacaktır.

Piyasa ve relatif güç feature'ları yalnız ayrı, sürümlü, fiziksel olarak doğrulanmış ve aynı `prediction_date` oturumuyla birebir eşleşen XU100/BIST 100 kapanış snapshot'ından üretilecektir. Bu bağımlılık hazır değilse sessiz fallback yapılmayacak ve pipeline açık hata verecektir.

Kesitsel feature'lar yalnız aynı `prediction_date` içinde, label veya T+1 işlem uygunluğu bağlantısından önce hesaplanacaktır. Rank tie yöntemi `average`, asgari geçerli security sayısı `MIN_CS_SECURITIES = 20` olacaktır. `entry_eligible`, `requires_review`, `target_hit`, `label` ve diğer gelecek-sonuç alanları rank evrenini belirleyemez.

Tarih-etkin sektör ve turnover adayları gerekli point-in-time veriler doğrulanana kadar `DEFER`; beta, idiosyncratic return, downside volatility ve breakout adayları `EXPERIMENT_LATER` durumundadır. Elle etkileşim feature'ları, isimlendirilmiş mum deseni ailesi, ek osilatör ailesi ve tavan yakınlığı `REJECT` durumundadır. `feature_fraction` bir feature kararı değildir ve feature grubu deneylerinden sonraki LightGBM parametre optimizasyonu aşamasına ertelenmiştir.

Tam feature listesi, formüller, kaynak sütunları, minimum geçmiş, missing/warm-up davranışı, canlı üretilebilirlik, aday durumları, kontrollü ablation sırası ve snapshot kabul kriterleri `FEATURE_CATALOG.md` içinde bağlayıcı olarak tanımlanmıştır.

**Gerekçe:**

Sınırlı ve açık bir baseline; model karmaşıklığını kontrol eder, her feature'ın canlı sistemde aynı hesapla yeniden üretilebilmesini sağlar ve feature gruplarının katkısını kontrollü ablation ile ölçmeyi mümkün kılar. Ölçekten bağımsız provider OHLC formülleri split sonrası sağlayıcı yeniden ölçeklemesinden sinyal türetilmesini engeller. Global BİST takvimi, zorunlu `security_id`, T+1 denylist'i, tarih-içi kesitsel hesaplama ve doğrulanmış snapshot koşulları zaman sızıntısı ile kimlik karışması riskini sınırlar.

**Etkilenen alanlar:**

Feature engineering, snapshot şeması, veri sızıntısı testleri, walk-forward deney tasarımı, model feature şeması ve günlük tahmin.

**Tarih:**

2026-07-27

### D029 — Güvenli XU100, Global BİST Takvimi ve baseline_v1 Feature Snapshot'ı

**Karar:**

Ana benchmark serisi, İş Yatırım'ın hisse endpoint'indeki `END_*` yan alanlarından veya yFinance'tan türetilmeyecek; bağımsız `ChartData.aspx/IndexHistoricalAll` endpoint'inden tam `XU100` koduyla alınacaktır. Ham snapshot `index_code`, `source_timestamp_ms` ve `source_value` alanlarını değiştirmeden korur. Epoch milisaniye değeri önce UTC-aware yorumlanır, ardından `Europe/Istanbul` saat dilimine çevrilerek `prediction_date` elde edilir. Naive tarih dönüşümü veya sabit `+1 gün` ana yöntem olamaz. `utc_calendar_date` ve `legacy_plus_one_date` yalnız karşılaştırmalı denetim alanlarıdır.

İstanbul tarih çözümü; tam XU100 kimliği, pozitif/sonlu değer, tekil timestamp ve tarih, İstanbul yerel gece yarısı, doğrulanmış global BİST seansı eşleşmesi ve UTC adayından üstün takvim kanıtı koşullarının tamamı sağlanırsa kabul edilir. Belirsizlikte pipeline fail-closed davranır. `END_*` en az 20 hisse üzerinde, yFinance ise yalnız `XU100.IS` ile tanısal çapraz kontroldür; ikisi de fallback kaynak değildir ve `^XU100` kullanılmaz.

Global takvim yalnız fiziksel checksum doğrulamasından geçen `COMPLETE` İş Yatırım hisse snapshot'larında gerçekten gözlenen `HGDG_TARIH` oturumlarının birleşiminden kurulur. Sentetik hafta içi günleri eklenmez ve tek bir hissedeki eksik gün global seansı düşürmez. `session_date` tekil ve artan, `session_index` deterministiktir.

`baseline_v1` feature snapshot'ı, D028'deki tam sıralı 32 feature'ı `security_id + prediction_date` anahtarıyla üretir. Provider OHLC yalnız raw yFinance snapshot'ından, TL hacmi raw İş Yatırım snapshot'ından, kimlik tarih-etkin identity snapshot'ından ve benchmark doğrulanmış XU100 snapshot'ından allowlist ile alınır. Global takvim ızgarasındaki eksik security oturumları rolling/shift hesabında korunur; çıktı yalnız gerçek provider satırlarını içerir. Doldurma, sentetik gözlem, ticker fallback'i, nominal/provider fiyat karışımı ve label/T+1 alanları yasaktır. Kesitsel ranklar yalnız aynı `prediction_date` içinde, en az 20 geçerli security ile ve label bağlantısından önce hesaplanır.

Snapshot revizyon kimliği içerik ve şema checksum'larına ek olarak `revision_context_checksum` ile provenance bağlamına bağlanır. Aynı içerik ve aynı bağlam idempotenttir; input/XU100/takvim/mapping/katalog/config/kod SHA bağlamlarından biri değişirse çıktı değerleri aynı kalsa bile yeni revision oluşur ve eski snapshot korunur. Feature metadata'sı sıralı feature listesini, `FEATURE_CATALOG.md` SHA-256 özetini, kalite özetini ve bütün doğrudan kaynak snapshot ID/checksum'larını taşır.

**Gerekçe:**

Sağlayıcı epoch timestamp'ini açık saat dilimi kanıtıyla çözmek tarih kaymasını; bağımsız benchmark ve gözlenen global takvim kullanmak yanlış endeks/oturum eşleşmesini; provenance-duyarlı revision ise aynı görünen çıktının farklı kaynak bağlamında sessizce yeniden kullanılmasını engeller. Allowlist, tam oturum ızgarası ve label öncesi kesitsel hesaplama D028 leakage sözleşmesini çalıştırılabilir ve denetlenebilir hale getirir.

**Etkilenen alanlar:**

İş Yatırım XU100 istemcisi, global takvim, snapshot metadata/revision kimliği, merkezi feature config, feature input birleştirme, 32 feature hesabı, kalite raporu, CLI akışı, veri sözlüğü, durum belgesi ve leakage testleri.

**Tarih:**

2026-07-27

### D030 — Prediction Universe ve Eğitim Dataset Sözleşmesi

**Karar:**

Bir `security_id + prediction_date` satırı yalnız ana aktif BİST şirket payı evreninde bulunuyorsa, T tarihinde gerçek gözlemi ve geçerli yFinance nominal OHLC'si varsa, T günü pozitif İş Yatırım TL hacmi veya yFinance pay hacmiyle işlem kanıtlanıyorsa, en az 21 global BİST oturumluk geçmişi varsa, tekil `baseline_v1` feature satırı ve doğrulanmış XU100 oturumu bulunuyorsa ve bütün bağlı snapshot/veri bütünlüğü kontrolleri geçiyorsa `prediction_eligible=true` olabilir. Çıktı `prediction_eligible` ve `prediction_exclusion_reason` alanlarını taşır; desteklenen nedenler `NOT_IN_MASTER_UNIVERSE`, `NO_T_OBSERVATION`, `INVALID_T_OHLC`, `NO_TRADE_ON_T`, `MISSING_TRADE_EVIDENCE`, `INSUFFICIENT_HISTORY`, `MISSING_FEATURE_ROW`, `MISSING_XU100_SESSION` ve `DUPLICATE_FEATURE_ROW` olacaktır. Duplicate feature anahtarı satır düşürmeyle giderilmez; koşu açık hatayla durur.

Evren yalnız T kapanışında mevcut T ve geçmiş bilgisinden oluşturulur. T+1 open/volume, `entry_eligible`, `entry_exclusion_reason`, `LIMIT_OPEN`, `CORPORATE_ACTION_WINDOW`, `target_hit`, `label`, `exit_price`, `yf_future_split_factor` ve diğer T+1–T+3 sonuç/action alanları evreni belirleyemez.

Feature ve label yalnız `security_id + prediction_date` anahtarıyla ve one-to-one doğrulamayla birleştirilir. Eğitime yalnız eligible, `label_status` geçerli, `label in {0,1}`, `label_available_date <= as_of_date` ve şeması tam `baseline_v1` olan satırlar alınır. Model matrisi katalog/metadata sırasındaki tam 32 feature'dan oluşur; kimlik, ticker, tarih, mapping, snapshot, audit, label, entry, hedef, çıkış ve horizon alanları modele giremez. Eksik feature değerleri imputasyon yapılmadan `NaN` kalır.

**Gerekçe:**

Prediction ile sonradan gözlenen işlem/label uygunluğunu ayırmak canlı zamanda yeniden üretilebilir bir skor evreni sağlar. Tekil tarih-security anahtarı, exact feature allowlist'i ve fail-closed bütünlük kontrolleri hem yanlış birleşimi hem gelecek bilgisinin sessizce modele girmesini önler.

**Etkilenen alanlar:**

Aktif pay evreni, nominal OHLC ve hacim girdileri, feature/label join'i, eğitim dataset'i, leakage kontrolleri ve günlük skorlanacak satırlar.

**Tarih:**

2026-07-28

### D031 — Global Takvim Tabanlı Label Availability ve Expanding Walk-Forward

**Karar:**

`label_available_date`, `prediction_date` sonrasındaki üçüncü D029 global BİST oturumudur; ticker içi satır `shift(3)` kullanılamaz. Her foldda `fit_row.label_available_date < validation_start_date` ve `validation_row.label_available_date < test_start_date` purge koşulları zorunludur.

Fold metadata'sı takvim penceresiyle label kullanılabilirliğini ayrı taşır. Fit için `fit_calendar_session_count`, `fit_labeled_session_count`, `fit_purged_session_count`; validation için `validation_calendar_session_count`, `validation_labeled_session_count`, `validation_purged_session_count` kaydedilir. `training_start_date`, 21 oturumluk feature warm-up tamamlandıktan sonraki ilk skorlanabilir oturumdur. Bağlayıcı 60 oturumluk validation penceresinde üç oturumluk availability purge nedeniyle 57 labeled oturum kullanılabilir; 60 oturumluk takvim penceresi 57 gibi raporlanamaz.

Walk-forward penceresi expanding training, 60 global oturum validation ve 20 global oturum test olarak uygulanır; her test bloğu başında model yeniden eğitilir. Validation eğitim geçmişinin zaman sıralı son bölümüdür. Aynı `prediction_date` içindeki bütün securities tek bir train, validation veya test grubunda kalır. Random split yasaktır ve test verisi early stopping veya parametre seçimi için kullanılamaz.

İlk gerçek test tarihi bu kararla sabitlenmemiştir. Tam aktif BİST snapshot'ları üretildikten sonra 21 oturum warm-up, en az 252 purged fit oturumu, 60 validation oturumu, iki sınıf ve pozitif örnek dağılımını gösteren fold feasibility raporu hazırlanacak; tarih ayrı kararla kesinleşecektir.

**Gerekçe:**

Global takvim ve sıkı availability sınırları, üç oturumluk label sonucu henüz bilinmeyen satırların fit/validation'a sızmasını engeller. Tarih gruplarını bölmemek kesitsel gözlemlerin aynı bilgi anında kalmasını sağlar.

**Etkilenen alanlar:**

Label availability, eğitim satırı seçimi, fold üretimi, early stopping, OOS değerlendirme ve ilk gerçek deney hazırlığı.

**Tarih:**

2026-07-28

### D032 — LightGBM Baseline, Olasılık, Sıralama ve Metrikler

**Karar:**

İlk baseline yalnız `LGBMClassifier` kullanır. Merkezi parametreler `objective=binary`, `boosting_type=gbdt`, `learning_rate=0.05`, `num_leaves=31`, `max_depth=6`, `min_data_in_leaf=100`, `n_estimators=1000`, `random_state=42`, `verbosity=-1`, `deterministic=true`, `force_col_wise=true`, `n_jobs=1`, `feature_fraction=1.0`, `bagging_fraction=1.0`, `bagging_freq=0`, `scale_pos_weight=1.0`, `is_unbalance=false` olacaktır. Early stopping yalnız validation üzerinde, `binary_logloss` ve 100 turla çalışır; varsayılan sınıflandırma eşiği `0.50`'dir. İlk baseline'da class weighting, grid search, Optuna, feature seçimi, ayrı calibration modeli veya threshold optimizasyonu yoktur.

Ham pozitif sınıf skoru `predict_proba(X)[:,1]` ile üretilip `probability_up_5pct` olarak saklanır; kalibre edilmiş gerçek olasılık olduğu iddia edilmez. Günlük rank `probability_up_5pct DESC, security_id ASC` ile deterministiktir.

Her fold ve birleşik OOS için Accuracy, Precision, Recall, F1, ROC-AUC, PR-AUC, confusion matrix, gerçek/tahmin pozitif oranı, Brier score, 10 quantile calibration bin ve ağırlıklı mutlak calibration farkı hesaplanır. Tek sınıfta tanımsız metrik `NA` olur. Daily Precision@5/@10 önce tüm eligible satırları sıralar; seçilen labelı `NA` satırın yerine alttan başka security almaz. Tarih çıktısı `requested_k`, `effective_k`, `selected_count`, `valid_label_count`, `positive_count`, `precision_at_k`, `label_coverage_at_k` alanlarını; ana özet tarihlerin macro ortalamasını ve ayrıca pooled sonucu taşır.

OOS çıktı en az security/ticker/tarih, model/fold sürümü, ham skor, varsayılan sınıf, günlük rank, prediction eligibility/nedeni, label/durumu ve feature/label snapshot ID'lerini saklar. Test dönemindeki bütün eligible satırlar skorlanır; labelı geçersiz satır çıktıdan silinmez, yalnız metrikten çıkarılır.

**Gerekçe:**

Tek ve sabit baseline, model katkısını parametre araması veya kalibrasyon etkisiyle karıştırmadan ölçer. Tarih-bazlı ranking ve coverage-aware Precision@K, günlük karar kullanımını dürüst biçimde raporlar.

**Etkilenen alanlar:**

Merkezi config, LightGBM eğitimi, early stopping, OOS skor şeması, calibration ve performans raporları.

**Tarih:**

2026-07-28

### D033 — Değişmez LightGBM Artifact Registry

**Karar:**

MLflow eklenmeyecek. Her deney `models/lightgbm/<experiment_id>/` altında metadata, effective config, feature schema, fold tanımları/metrikleri, birleşik OOS metrik/tahminleri ve her fold için ayrı `model.txt` ile fold metadata'sı taşıyan dosya tabanlı değişmez artifact olarak saklanacaktır. Fold model sürümü `<experiment_id>_fold_NNN` olur ve eski klasörlerin üzerine yazılmaz.

Training fingerprint; kod commit SHA, config checksum, feature snapshot checksum, label snapshot checksum, feature katalog checksum, fold tanımları ve random seed'e deterministik olarak bağlanır. Aynı fingerprint'e ait tamamlanmış artifact varsa yeni klasör oluşturulmadan mevcut experiment idempotent döndürülür. Metadata; model/experiment sürümü ve zamanı, as-of ve dönem sınırları, son kullanılabilir label tarihi, snapshot ID/checksum'ları, sıralı feature adları, LightGBM parametreleri, seed, kod SHA, satır/sınıf dağılımı, fold tanımları, train/validation/OOS metrikleri ve fingerprint'i taşır.

Sentetik ve küçük snapshot kabul koşuları gerçek model deneyi değildir; `EXPERIMENT_LOG.md` ilk gerçek walk-forward çalıştırılmadan hemen önce oluşturulacaktır.

**Gerekçe:**

Atomik ve immutable kayıt, aynı veri/config/kod bağlamını yeniden üretilebilir kılar; yarım veya aynı içerikli mükerrer model klasörlerinin sonuç geçmişini değiştirmesini engeller.

**Etkilenen alanlar:**

Model registry, artifact dosya yapısı, provenance, tekrar çalıştırma/idempotency ve deney kayıt süreci.

**Tarih:**

2026-07-28

## Henüz Kesinleşmemiş Kararlar

- Likidite filtresi
- Günlük seçilecek hisse sayısı
- Komisyon ve slippage varsayımları
- İlk walk-forward test tarihi

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
