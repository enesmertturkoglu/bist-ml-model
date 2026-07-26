# PROJECT STATUS

**Son güncelleme:** 2026-07-26

## Mevcut Aşama

Kaynak kabul testinde tespit edilen hibrit fiyat ölçeği sorunu için tek fiyat kaynağı yaklaşımı kesinleştirildi.

İlk sürümde tüm OHLC fiyatları yFinance'tan alınacak ve split verileriyle dönemin nominal ölçeğine dönüştürülecek. İş Yatırım ana işlem takvimi, TL hacmi, endeks ve yardımcı veriler için kullanılmaya devam edecek. Tek kaynaklı kabul kodu ve birim testleri tamamlandı.

`2026-07-26` gerçek veri kabul koşusu, İş Yatırım yıllık isteklerindeki yaygın okuma zaman aşımları nedeniyle `FAIL` üretti; bu sonuç yFinance nominal OHLC iç tutarlılığına ilişkin bir başarısızlık değildir. Sağlayıcı koşusu eksiksiz tamamlanmadan kaynak kabulü verilmedi. Sıradaki görev İş Yatırım erişimi kararlı olduğunda kabul testini yeniden çalıştırmak ve ardından veri toplama/temizleme altyapısına geçmektir.

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
- Gerçek veri kabul koşusu iki kez ağ erişimiyle denendi; İş Yatırım okuma zaman aşımları nedeniyle eksiksiz kaynak koşulu sağlanamadı ve raporlar `FAIL` olarak yeniden üretildi. Sahte veya önbelleğe alınmış veriyle başarı üretilmedi.

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

1. İş Yatırım erişimi kararlı olduğunda tek kaynaklı yFinance nominal OHLC kabul testini yeniden çalıştır.
2. Eksiksiz gerçek veri koşusunda yFinance nominal OHLC'nin kendi iç tutarlılığını doğrula.
3. D022 ve D023 durum kodlarını modüler veri temizleme kodunda uygula.
4. Veri toplama ve ham veri sürümleme altyapısını oluştur.
5. Kod değiştiren hisselerin eşlemesini test et.
6. Label üretim koduna geç.

## Sonraki Ana Aşamalar

1. Kaynak kabul testi ve gerçek veri sütunlarının doğrulanması
2. Veri toplama ve temizleme
3. Label üretim kodu ve testleri
4. Feature engineering
5. LightGBM eğitimi
6. Walk-forward test
7. Backtest
8. Kontrollü deneyler
9. Paper trading
10. Günlük raporlama sistemi

## Açık Sorular

- Açılış mevcutken iki hacim alanının da eksik olduğu kayıtlar nasıl ele alınacak?
- İş Yatırım düzeltme katsayısı ile eşleşmeyen yFinance action kayıtları nasıl sınıflandırılacak?
- Likidite filtresi nasıl belirlenecek?
- Günlük kaç hisse seçilecek?
- Komisyon ve slippage varsayımları ne olacak?
- İlk walk-forward test tarihi ne olacak?
