# PROJECT STATUS

**Son güncelleme:** 2026-07-26

## Mevcut Aşama

D022/D023 modüler piyasa verisi temizleme ve işlem uygunluğu altyapısı ile D026 resmî, tarih-etkin BİST pay fiyat adımı entegrasyonu tamamlandı.

İlk sürümde tüm OHLC fiyatları yFinance'tan alınacak ve split verileriyle dönemin nominal ölçeğine dönüştürülecek. İş Yatırım ana işlem takvimi, TL hacmi, endeks ve yardımcı veriler için kullanılmaya devam edecek. İki kaynağın ham verileri birbirinden bağımsız `raw` snapshot'larda; yFinance nominal OHLC ise kaynak snapshot kimliğine bağlı ayrı `derived` katmanda saklanır. Canonical checksum, atomik yazma, manifest doğrulaması ve revision fark raporu eski snapshot'ların üzerine yazılmasını önler.

`2026-07-26` dayanıklı gerçek veri kabul koşusu 10 hissenin gerekli İş Yatırım ve yFinance verilerini eksiksiz alarak `PASS` üretti. yFinance nominal OHLC iç tutarlılığı değerlendirilebilir satırlarda `%100`, geçersiz nominal OHLC sayısı `0` oldu. Kaynak kabul, snapshot/revision, D022/D023 temizleme ve D026 fiyat adımı aşamaları tamamlandı. Sıradaki görev temiz snapshot'lardan label üretim koduna geçilmesidir.

## Tamamlananlar

- Projenin amacı belirlendi.
- Ana model LightGBM Classifier olarak seçildi.
- Benchmark modeller, ensemble ve ayrı ranking modeli ilk sürümden çıkarıldı.
- Hisselerin LightGBM pozitif sınıf olasılığına göre sıralanmasına karar verildi.
- Random train-test split yerine walk-forward validation kullanılmasına karar verildi.
- İlk sürümde haber, KAP, sosyal medya ve derin öğrenme kullanılmamasına karar verildi.
- Tahmin zamanının `T` günü piyasa kapandıktan sonra olması kesinleştirildi.
- İşleme `T+1` açılış fiyatından girilmesi kesinleştirildi.
- Tahmin ufku `T+1`, `T+2` ve `T+3` olmak üzere üç işlem günü olarak belirlendi.
- `%5 yükseliş` hesabında günlük `high` kullanılması kesinleştirildi.
- Hedefe ulaşılırsa `%5` hedef fiyatından çıkılması kararlaştırıldı.
- Hedefe ulaşılamazsa `T+3` kapanışından çıkılması kararlaştırıldı.
- İlk sürümde stop-loss kullanılmaması kararlaştırıldı.
- Tavan fiyat, işlem görmeme ve eksik veri kuralları belirlendi.
- Label formülü örnek fiyat senaryolarıyla doğrulandı.
- Labelın brüt fiyat hareketini, backtestin ise komisyon ve slippage sonrası net sonucu ölçmesi kararlaştırıldı.
- Kesinleşen label ve işlem kararları `DECISIONS.md` dosyasına eklendi.
- GitHub reposu proje belgeleri için tek doğru kaynak olarak belirlendi; her kesin karar ve tamamlanan ana aşama sonrasında ilgili belgelerin doğrudan repoda güncellenmesi kararlaştırıldı.
- ChatGPT karar ve proje yönetimi, Codex ise kodlama, test ve GitHub güncellemeleri için kullanılacak şekilde iş bölümü kesinleştirildi.
- Her kesin karar veya gerekli belge güncellemesi sonrasında sohbetin otomatik olarak kopyalanabilir bir Codex devir talimatı vermesi zorunlu hale getirildi.
- Codex çalışma kurallarını repo düzeyinde tanımlayan `AGENTS.md` dosyası hazırlandı.
- Dört güncel yönetim dosyası (`PROJECT_BRIEF.md`, `PROJECT_STATUS.md`, `DECISIONS.md`, `AGENTS.md`) GitHub reposuna yüklendi.
- THYAO için aynı tarih aralığındaki İş Yatırım ve yFinance verileri karşılaştırıldı.
- D017'deki İş Yatırım ana/yFinance tamamlayıcı hibrit fiyat yaklaşımı D024 ile revize edildi.
- Ana işlem takviminin İş Yatırım verisinden oluşturulmasına karar verildi.
- Bütün open, high, low ve close fiyatlarının yFinance nominal serisinden alınmasına karar verildi.
- Kaynak uyuşmazlıklarının veri kalite kontrolüyle yönetilmesine karar verildi.
- İş Yatırım ve yFinance fiyatlarının aynı giriş, label, çıkış veya tavan hesabında karıştırılmamasına karar verildi.
- Sonradan halka arz edilen hisselerin kendi ilk işlem tarihlerinden başlayacağı kararlaştırıldı.
- Eksik geçmişin geriye doğru doldurulmamasına karar verildi.
- Veri toplama başlangıcı ile walk-forward test başlangıcının ayrı tutulmasına karar verildi.
- İlk sürümde güncel aktif BİST paylarından oluşan sabit hisse evreninin kullanılmasına karar verildi.
- Günümüzde aktif olmayan ve kot dışı kalmış hisselerin ilk sürüm evrenine dahil edilmemesine karar verildi.
- Bu yaklaşımın survivorship bias oluşturduğu ve sonuçların tam point-in-time backtest olarak sunulmayacağı açıkça kabul edildi.
- Güncel aktif hisselerin doğrulanmış eski işlem kodlarının aynı `security_id` altında birleştirilmesine karar verildi.
- Kod eşleştirmesinde resmi Borsa İstanbul veya KAP kayıtlarının kullanılmasına karar verildi.
- Birleşme, devir veya menkul kıymet devamlılığı belirsiz durumlarda fiyat serilerinin otomatik birleştirilmemesine karar verildi.
- ETF, fon, varant, sertifika ve rüçhan hakkı kuponlarının ilk sürüm evreninden çıkarılmasına karar verildi.
- Point-in-time tarihsel evrenin sonraki bir geliştirme ve karşılaştırma aşamasına bırakılmasına karar verildi.
- Tarihsel model dönemi başlangıcı `2020-03-13` olarak revize edildi.
- `2016-01-04` başlangıcı geçersiz kılındı.
- `2020-03-13` sonrasında normal adi paylar için `%10` fiyat marjının kullanılmasına karar verildi.
- Tavan açılışın sabit `%9,90` eşiğiyle değil, `%10` ham limitin fiyat adımına aşağı yuvarlanmasıyla tespit edilmesine karar verildi.
- Tavan açılan kayıtların işlem ve label evreninden `NA` olarak çıkarılacağı kesinleştirildi.
- İlk işlem günü, serbest marj ve kurumsal işlem gibi standart hesaplamaya uygun olmayan durumların özel incelemeye alınacağı belirlendi.
- `T+1` yFinance nominal açılış fiyatı bulunmayan kayıtların negatif label yerine `NA` bırakılmasına karar verildi.
- İş Yatırım TL hacmi ile yFinance adet hacminin birlikte sıfır olduğu günlerin işlem gerçekleşmemiş kabul edilmesine karar verildi.
- Hacim alanlarından en az biri pozitifse kaydın yalnızca hacim nedeniyle elenmemesine karar verildi.
- Hacimlerden biri pozitifken diğerinin sıfır veya eksik olmasının yalnızca veri kalite uyarısı oluşturmasına karar verildi.
- İlk sürümde düşük fakat pozitif hacim nedeniyle otomatik hisse elemesi yapılmamasına karar verildi.
- Likidite filtresinin temel giriş geçerliliğinden ayrılarak daha sonraki bir karar ve deney konusu olmasına karar verildi.
- Tavan açılış, ilk işlem günü, serbest marj ve kurumsal işlem şüphesi bulunan kayıtların `NA` veya özel inceleme durumuna alınması kesinleştirildi.
- İlk sürümde kurumsal işlem ve serbest marj kontrollerinde KAP kullanılmamasına karar verildi.
- Kurumsal işlem tespitinde yFinance action kayıtları ile İş Yatırım ham/düzeltilmiş fiyat oranı değişimlerinin kullanılmasına karar verildi.
- `T+1–T+3` penceresinde kurumsal işlem bulunan kayıtların `NA` bırakılması kesinleştirildi.
- Önceki geçerli yFinance nominal kapanışı bulunmayan kayıtların standart tavan hesabına alınmamasına karar verildi.
- Açılış veya gün içi en yüksek fiyat hesaplanan üst fiyat limitini aşıyorsa kaydın standart dışı işlem durumu olarak `NA` bırakılması kararlaştırıldı.
- İlk sürümde kapsamlı tarihsel serbest marj listesi oluşturulmamasına karar verildi.
- Yerel kaynak kabul testi 10 hissede ve dört test döneminde gerçek İş Yatırım/yFinance verisiyle teknik olarak tamamlandı; nihai kabul durumu `PARTIAL` olarak güncellendi.
- İş Yatırım'ın 31, yFinance'ın 8 gerçek kaynak sütunu doğrulandı ve `DATA_DICTIONARY.md` oluşturuldu.
- Başlangıç ve fiyat adımı çevresi dönemlerinde tarih eşleşmesi `%100`; beş hisselik `2020-03-13`–`2026-07-26` tam döneminde `7.942/7.945` (`%99,9622`) olarak ölçüldü.
- Beş hisselik tam dönemde 3 yFinance satırı/açılışı eksik, İş Yatırım TL hacmi eksik veya sıfır kayıt sayısı 0, yFinance adet hacmi eksik kayıt sayısı 3 ve sıfır kayıt sayısı 116 bulundu.
- İki hacmin birlikte sıfır veya birlikte eksik olduğu ve açılış mevcutken iki hacmin birlikte eksik olduğu kayıt sayısı test kapsamlarında 0 bulundu.
- Kurumsal işlem raporunda test dönemlerine giren 40 benzersiz olay satırının 39'unda iki kaynak aynı gün sinyal verdi; BIMAS `2020-10-14` temettüsü yalnız yFinance tarafından işaretlendi.
- İş Yatırım `adjusted_close/raw_close` değişim kontrolünde `rtol=0.0001`, `atol=0.00005` sayısal toleransıyla kaynak yuvarlama gürültüsü gerçek olaylardan ayrıldı.
- yFinance `auto_adjust=False` çağrısındaki geçmiş OHLC değerlerinin split ölçeğine geriye taşındığı; İş Yatırım `HG_*` ham fiyatlarının tarihindeki nominal ölçekte kaldığı ölçüldü. Beş hisselik tam dönemde değerlendirilebilen 7.942 hibrit OHLC satırının 3.542'si (`%44,60`) bu nedenle tutarsızdı.
- D022'nin açılış/hacim durum kontrolleri üretilebilir bulundu; ancak yFinance açılışı ile İş Yatırım ham `high/low/close` değerlerinin doğrudan birleştirilmesi split ölçeği sorunu çözülmeden uygulanabilir kabul edilmedi.
- D023, yFinance action alanları ile İş Yatırım düzeltme katsayısı sinyallerinin bilinen sınırlamaları korunarak uygulanabilir bulundu.
- yFinance sağlayıcı OHLC değerlerini dönemin nominal ölçeğine geri taşımak için `t` tarihinden kesinlikle sonra gerçekleşen split oranlarının ticker bazında kümülatif çarpımı test edildi; split gününün kendi oranı o güne uygulanmadı.
- Orijinal yFinance değerleri `yf_provider_*`, gelecekteki split çarpanı `yf_future_split_factor`, nominal karşılıklar `yf_nominal_*` alanlarında ayrı tutuldu.
- Split faktörü; splitsiz dönem, split öncesi/günü/sonrası, birden fazla split, geçersiz oran ve ticker izolasyonu senaryolarıyla unit test edildi.
- Beş hisselik tam dönemde açılışın İş Yatırım ham günlük aralığında olma oranı dönüşüm öncesi `%55,4017` iken nominal dönüşüm sonrasında `%96,4241` oldu; tutarsızlık `3.542` kayıttan `284` kayda indi.
- Split yaşamış BIMAS, TUPRS ve SASA'nın normal günlerinde geçerlilik `%27,6546` değerinden `%96,0312` değerine yükseldi; `3.239` satır düzeldi, hiçbir satır kötüleşmedi ve `188` tutarsızlık kaldı.
- Hisse bazında dönüşüm sonrası tam dönem geçerliliği BIMAS `%97,2310`, TUPRS `%97,0403`, SASA `%93,8955`, THYAO `%98,4257`, SISE `%95,5290` olarak ölçüldü.
- Beş hisselik tam dönemde temettü günleri, split günleri ve düzeltme katsayısı değişim günleri dönüşüm sonrasında `%100` aralık geçerliliği verdi; D023 uyarınca bu günler yine normal gün kabulüne dahil edilmedi.
- Kalan normal-gün uyuşmazlıklarında hem belirgin çok-kaynaklı tarih/fiyat farkları hem de sayısal/fiyat adımı ölçeğinde küçük sınır aşmaları gözlendi; bu görevde sabit kabul eşiği belirlenmedi.
- Kaynak kabulü, eksiksiz teknik koşuya rağmen split yaşamış hisselerin normal günlerinde 188 tutarsızlık ve kesinleşmemiş kabul toleransı bulunduğu için `PARTIAL` olarak sınıflandırıldı.
- Hibrit yFinance open + İş Yatırım OHLC yaklaşımından vazgeçildi.
- Tüm fiyat alanlarında yFinance nominal OHLC kullanılmasına karar verildi.
- yFinance sağlayıcı ve nominal fiyatlarının ayrı saklanması kesinleştirildi.
- `yf_nominal_price[t] = yf_provider_price[t] × t tarihinden sonraki geçerli split oranlarının kümülatif çarpımı` formülü kesinleştirildi; split gününün kendi oranı aynı güne uygulanmayacak.
- Tavan hesabında önceki geçerli yFinance nominal close kullanılmasına karar verildi.
- İş Yatırım fiyat uyuşmazlığının satırı dışlamayan `cross_source_price_warning` kalite uyarısı olarak tutulmasına karar verildi.
- Kaynak kabul testi yFinance nominal OHLC iç tutarlılığını ana kriter, İş Yatırım fiyat farkını yalnız kalite uyarısı olarak kullanacak şekilde düzenlendi.
- `NO_OPEN`, `NO_TRADE`, `INVALID_OHLC`, `SOURCE_VOLUME_CONFLICT` ve `CORPORATE_ACTION_WINDOW` durumları kabul testinde üretilebilir hale getirildi.
- Provider alanlarının korunması, nominal OHLC iç geçerliliği, çapraz kaynak uyarısının satırı dışlamaması ve split faktörünün feature listesinde olmaması dahil 17 birim test tamamlandı.
- Önceki gerçek veri kabul koşuları, kurulu istemcinin sabit 10 saniyelik timeout'u nedeniyle İş Yatırım okuma zaman aşımı üretmiş ve dürüstçe `FAIL` olarak raporlanmıştı; sahte veya elle oluşturulmuş veriyle başarı üretilmedi.
- Kurulu `site-packages` değiştirilmeden, `(connect=10, read=60)` timeout, sıralı istek, retry/backoff+jitter, `12→6→3` aylık uyarlamalı parçalama ve atomik yerel cache sağlayan repo içi İş Yatırım istemcisi oluşturuldu.
- Dayanıklı istemci timeout/retry, 6 ve 3 aylık parçalama, minimum parça hatası, kısmi başarı cache'i, cache hit/eksik aralık/bozuk cache, tekrar temizleme, HTTP 429/5xx, kalıcı şema hatası, sleep/jitter enjeksiyonu ve timeout aktarımı senaryolarıyla test edildi.
- İlk dayanıklı gerçek koşuda 70 yıllık İş Yatırım ağ isteğinin tamamı başarılı oldu; timeout, retry, alt parçalama ve tamamen başarısız parça sayısı `0` olarak ölçüldü.
- Operasyonel cache 70 veri ve 70 metadata parçasıyla dolduruldu. İkinci doğrulama koşusu 70 cache hit, `0` İş Yatırım ağ isteği ve aynı `PASS` sonucunu verdi.
- Eksiksiz gerçek koşuda beş hisselik tam dönemde `7.945` İş Yatırım gününün `7.942` tanesi yFinance ile eşleşti; 3 nominal open eksik, 0 nominal OHLC geçersiz ve değerlendirilebilir nominal OHLC geçerliliği `%100` ölçüldü.
- Tüm test dönemlerinde 7 eksik nominal OHLC satırı açık durumlarla dışlanabilir bulundu; 14.386 çapraz kaynak fiyat farkı yalnız kalite uyarısı olarak raporlandı ve kabul sonucunu etkilemedi.
- D022 uygulanabilir bulundu; açılış mevcutken iki hacmin birlikte eksik olduğu kayıt sayısı `0` kaldı. D023 uygulanabilir bulundu ve 213 tahmin satırı `CORPORATE_ACTION_WINDOW` ile işaretlenebilir ölçüldü.
- Dayanıklı tek fiyat kaynaklı kabul sonucu `PASS` oldu ve kaynak kabul aşaması tamamlandı.
- Model eğitimi ile günlük tahmin üretiminin bağımsız süreçler olmasına karar verildi.
- Eğitimin açık komutla, belirtilen `as_of_date` tarihindeki veriler ve yalnız tamamen sonuçlanmış üç işlem günlük label pencereleriyle çalıştırılması kesinleştirildi.
- Her eğitimde LightGBM'in sıfırdan eğitilmesi, incremental learning kullanılmaması ve eski sürümlerin üzerine yazılmadan değişmez model sürümü üretilmesi kararlaştırıldı.
- Tahmin sırasında modelin yeniden eğitilmemesi; seçilen veya aktif model sürümüyle en güncel kullanılabilir feature'ların değerlendirilmesi kararlaştırıldı.
- Model artifact'ı, metadata, sıralı feature şeması, config, veri snapshot/checksum bağları, kod commit SHA'sı ve metriklerin dosya tabanlı sürümlü kayıtta saklanması kesinleştirildi.
- Tahmin feature isim, sayı veya sıra uyuşmazlığında sessiz devam edilmeyip açık hata üretilmesine karar verildi.
- Veri toplama altyapısının değişmez ham veri ve sağlayıcı revizyon kaydına ek olarak model ile tahmin kayıtlarının kullandığı snapshot kimliklerini tekrarlanabilir biçimde sağlaması gerektiği belirlendi.
- Veri kökleri, ham/türetilmiş katman yolları, manifest/revision yolları, model başlangıcı, ayrı warm-up ayarı, timeout/retry değerleri, checksum algoritması ve snapshot durumları merkezi `MarketDataConfig` yapısına alındı.
- İş Yatırım'ın dayanıklı repo içi istemcisi ile yFinance `auto_adjust=False`, `actions=True` çağrısını kullanan ortak kolektör ve `scripts/collect_market_data.py` komutu oluşturuldu.
- yFinance sağlayıcı OHLC, adet hacmi, temettü ve split alanları değişmeden `raw`; D024 nominal OHLC ve normalizasyon denetim alanları kaynak snapshot bağıyla ayrı `derived` katmana yazılır hale getirildi.
- Snapshot içeriği kolon sırası, satır sırası, tarih, sayısal değer ve null gösterimi için canonical JSON Lines biçimine dönüştürülerek SHA-256 içerik ve şema checksum'larıyla kaydedilir hale getirildi.
- Aynı mantıksal istekte aynı içerik için idempotent sonuç; değişen içerik için yeni revision, önceki snapshot bağı, değişen satır/hücre/sütun ve eklenen/kaldırılan tarih raporu üretildi.
- Snapshot dizini ve JSONL manifestleri geçici dosya/dizin üzerinden atomik `replace` ile yazılır; yalnız manifestte bulunan ve fiziksel checksum doğrulamasından geçen `COMPLETE` snapshot'lar kullanılabilir kabul edilir.
- `FAILED`, `PARTIAL` ve `CORRUPT` durumları eğitim için kullanılamaz olarak ayrıldı; başarısız veya kısmi sağlayıcı sonuçlarının hata bilgisiyle denetlenebilir kaydı desteklenir hale getirildi.
- Snapshot kimlikleri, kaynak/checksum/config/kod SHA/provider sürümü ve `input_snapshot_ids` alanları D025'teki gelecekteki model ve tahmin metadata bağlarını destekleyecek biçimde kaydedildi.
- Snapshot/revision/izolasyon/atomik hata senaryoları ile sahte sağlayıcılı kolektör testleri eklendi; toplam 60 birim test ve mevcut gerçek kaynak kabul koşusu `PASS` tamamlandı.
- D022/D023 kuralları `src/data/cleaning.py`, tarih-etkin fiyat adımı ve tavan hesabı `src/data/price_limits.py`, doğrulanmış snapshot orkestrasyonu `src/data/cleaning_pipeline.py` içinde modülerleştirildi; kaynak kabul betiğindeki ortak OHLC, hacim, düzeltme faktörü ve kurumsal aksiyon kuralları bu modüllere bağlandı.
- Temizleme yalnız manifestteki, fiziksel checksum doğrulamasından geçen `COMPLETE` İş Yatırım raw, yFinance raw ve kaynak raw ID'sine bağlı yFinance nominal snapshot'larını kabul eder; ham snapshot'ları değiştirmeden yeni `derived/cleaning/market_data_eligibility` snapshot'ı üretir.
- OHLC için `NO_OPEN`/`INVALID_OHLC`; hacim için `NO_TRADE`, `SOURCE_VOLUME_CONFLICT` ve çözümsüz `BOTH_VOLUMES_MISSING_UNRESOLVED`; tavan için `NO_PREVIOUS_CLOSE`, `LIMIT_OPEN`, `SPECIAL_MARGIN_OR_CORPORATE_ACTION` ve `PRICE_STEP_UNAVAILABLE`; kurumsal aksiyon için `CORPORATE_ACTION_WINDOW` durumları deterministik ana neden ve tam neden listesiyle üretildi.
- `T+1–T+3` kurumsal aksiyon penceresi ticker satır sırasına göre değil, global İş Yatırım BİST takvimindeki ardışık günlere göre kuruldu; action ve gelecekteki split/audit alanlarının model feature'ı olmadığı kod ve sözlükte açıklandı.
- Borsa İstanbul'un `E-18454353-100.04.02-19412` sayılı resmî duyurusundaki eski/yeni pay fiyat adımı metinleri ve `2023-11-06` yürürlük tarihi PDF metni ile görsel tablo üzerinden doğrulandı; kaynak SHA-256 özetiyle birlikte `reference_data/bist_equity_tick_sizes_v1.csv` dosyasında sürümlendi.
- D026 ile `2020-03-13`–`2023-11-05` dört kademeli ve `2023-11-06` sonrası sekiz kademeli `EQUITY` rejimleri eklendi. İlk tarih resmî başlangıç iddiası değil, projenin model dönemi kapsam sınırıdır. Bantlar alt dahil/üst hariçtir; eksik, çakışan veya boşluklu referans veri yüklenmez.
- Tavan hesabı `previous_valid_yf_nominal_close × Decimal("1.10")`, `entry_date + EQUITY + raw_upper_limit` kural çözümü ve `Decimal` ile içeri/aşağı yuvarlama sırasına bağlandı. Çözülen kural kimliği, tarih aralığı, fiyat adımı, çözüm durumu ve resmî belge temiz snapshot'ta saklanır; kural yoksa mevcut açık inceleme davranışı korunur.
- Fiyat adımı sınırları, rejim geçişleri, boşluk/çakışma, bilinmeyen tarih/enstrüman, `Decimal` deterministikliği ve temizleme entegrasyonuyla birlikte toplam 153 birim test geçti. Yeniden çalıştırılan 10 hisselik gerçek kaynak kabulü `PASS` verdi.
- THYAO `2024-01-02`–`2024-01-12` üç kaynak snapshot seti D026 tarifesi ve `1c5c7a7` kod commit'iyle yeniden temizlendi. Yeni `COMPLETE` snapshot `snap_80ea98811d6a6f3a_r0001_0141392192f1` oldu: 6/6 fiyat adımı `BIST_EQUITY_FROM_20231106_V1` ile çözüldü, `PRICE_STEP_UNAVAILABLE=0`, `requires_review=0`, `entry_eligible=true` 6, diğer dışlama kodları 0 ve satırı dışlamayan çapraz kaynak uyarısı 6 ölçüldü. İçerik checksum'u `7350ad8a5c39f32942f616c4ea8ffd2193691e70982c099d604d6c8e7096d030` olarak kaydedildi.

## Kesinleşen Başlangıç Senaryosu

- Tahmin zamanı: `T` günü piyasa kapandıktan sonra
- Kullanılabilir bilgi: Yalnızca `T` ve önceki günlerin verileri
- Giriş zamanı: `T+1` işlem günü
- Giriş fiyatı: `open[T+1]`
- Maksimum pozisyon süresi: Üç Borsa İstanbul işlem günü
- Hedef fiyat: `open[T+1] × 1.05`
- Pozitif label: `T+1`–`T+3` dönemindeki maksimum `high` hedef fiyata eşit veya yüksekse `1`
- Negatif label: Hedef gerçekleşmezse `0`
- Hedef çıkışı: Hedef fiyat
- Süre sonu çıkışı: `close[T+3]`
- Stop-loss: İlk sürümde yok

## İlk Sürüm Hisse Evreni

- Evren referansı: Veri toplama başlangıcındaki güncel aktif BİST şirket payları
- Tarihsel kullanım: Aynı aktif liste bütün geçmiş veri dönemine uygulanacak
- Kot dışı ve günümüzde aktif olmayan hisseler: İlk sürüme dahil edilmeyecek
- Kod değiştiren aktif hisseler: Eski ve yeni kodlar aynı `security_id` altında eşleştirilecek
- Kod eşleştirme kaynağı: Borsa İstanbul ve gerektiğinde KAP
- Finansal araç kapsamı: Yalnızca şirket payları
- Bilinen sınırlama: Survivorship bias
- Sonuçların yorumu: Tam point-in-time backtest değildir
- Gelecek geliştirme: Point-in-time tarihsel evrenle karşılaştırmalı deney

## Belge Yönetimi ve Codex Devir Kuralı

- Ana kaynak: `https://github.com/enesmertturkoglu/bist-ml-model`
- Her kesin karar sonrasında `DECISIONS.md` güncellenir.
- Her tamamlanan ana aşama sonrasında `PROJECT_STATUS.md` güncellenir.
- Veri, feature veya deney içeriği netleştiğinde ilgili özel belge güncellenir.
- Teknik çalışmaya başlamadan önce GitHub'daki güncel dosyalar okunur.
- Sohbet içi ve geçici dosya kopyaları bağlayıcı değildir.
- Gerekli belge veya kod değişikliği doğduğunda sohbet, doğrudan Codex'e kopyalanabilir görev talimatı verir.
- Talimatta okunacak ve değiştirilecek dosyalar, kesin değişiklikler, korunacak içerikler, testler ve commit/PR kapsamı belirtilir.
- Codex görevi tamamlandıktan sonra sonuç GitHub'daki güncel dosyalardan doğrulanır.

## Sıradaki Görevler

1. Temiz ve uygunluk durumu kesinleşmiş snapshot'lardan label üretim kodunu ve testlerini oluştur.
2. Kod değiştiren hisselerin eşlemesini test et.

## Sonraki Ana Aşamalar

1. Veri toplama ve temizleme
2. Label üretim kodu ve testleri
3. Feature engineering
4. LightGBM eğitimi
5. Walk-forward test
6. Backtest
7. Kontrollü deneyler
8. Paper trading
9. Günlük raporlama sistemi

## Açık Sorular

- Likidite filtresi nasıl belirlenecek?
- Günlük kaç hisse seçilecek?
- Komisyon ve slippage varsayımları ne olacak?
- İlk walk-forward test tarihi ne olacak?
