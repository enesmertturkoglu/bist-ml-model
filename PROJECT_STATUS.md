# PROJECT STATUS

**Son güncelleme:** 2026-07-25

## Mevcut Aşama

İlk sürüm hisse evreni kesinleştirildi. Sıradaki aşama tarihsel tavan fiyatı ve işlem yapılabilirlik yaklaşımının belirlenmesidir.

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
- İş Yatırım ana, yFinance tamamlayıcı kaynak olarak seçildi.
- Ana işlem takviminin İş Yatırım verisinden oluşturulmasına karar verildi.
- Açılış ve adet hacminin yFinance’den alınmasına karar verildi.
- Kaynak uyuşmazlıklarının veri kalite kontrolüyle yönetilmesine karar verildi.
- Yalnızca yFinance veya yalnızca İş Yatırım kullanılmamasına karar verildi.
- Tarihsel veri başlangıcı `2016-01-04` olarak kesinleştirildi.
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

1. Tarihsel tavan fiyatı ve işlem yapılabilirlik yaklaşımını kesinleştir.
2. İşlem durumu verisinin gerekli olup olmadığını belirle.
3. Güncel aktif hisse listesinin alınacağı resmi kaynağı kesinleştir.
4. Aktif hisselerin eski kodlarını eşleştirme yöntemini veri kabul testiyle doğrula.
5. Kaynak kabul testini tamamla.
6. Gerçek veri sütunlarına göre `DATA_DICTIONARY.md` oluştur.
7. Veri toplama koduna geç.

## Sonraki Ana Aşamalar

1. Tarihsel tavan fiyatı ve işlem yapılabilirlik yaklaşımı
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

- Tarihsel tavan fiyatı nasıl belirlenecek?
- İşlem durumu verisi gerekli olacak mı?
- Likidite filtresi nasıl belirlenecek?
- Günlük kaç hisse seçilecek?
- Komisyon ve slippage varsayımları ne olacak?
- Güncel aktif hisse listesinin resmi ve tekrarlanabilir kaynağı hangisi olacak?
- Aktif hisselerin eski kodlarını toplu olarak hangi Borsa İstanbul veya KAP verisiyle eşleştireceğiz?
- Point-in-time tarihsel evren hangi proje aşamasında yeniden ele alınacak?
