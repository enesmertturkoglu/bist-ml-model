# PROJECT STATUS

**Son güncelleme:** 2026-07-25

## Mevcut Aşama

Veri kaynakları kesinleştirildi. Mevcut görev tarihsel veri başlangıcının ve point-in-time hisse evreninin belirlenmesidir.

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

1. Tarihsel veri başlangıcını belirlemek.
2. Survivorship bias oluşturmayan point-in-time hisse evrenini belirlemek.
3. Seçilen kaynaklardan küçük bir OHLCV örneği indirmek.
4. Açılış, high, kapanış, işlem görmeme ve düzeltilmiş fiyat alanlarının yeterliliğini kontrol etmek.
5. Gerçek sütunlara göre `DATA_DICTIONARY.md` oluşturmak.
6. Label üretim fonksiyonunu örnek veri üzerinde uygulamak ve birim testlerini yazmak.
7. Veri kullanılabilirliği netleşince `FEATURE_CATALOG.md` oluşturmak.
8. İlk model deneyi başladığında `EXPERIMENT_LOG.md` oluşturmak.

## Sonraki Ana Aşamalar

1. Tarihsel veri başlangıcı ve point-in-time hisse evreni
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

- Tarihsel veri başlangıcı ne olacak?
- Survivorship bias oluşturmayan tarihsel hisse evreni nasıl oluşturulacak?
- Tarihsel tavan fiyatı nasıl belirlenecek?
- İşlem durumu verisi gerekli olacak mı?
- Likidite filtresi nasıl belirlenecek?
- Günlük kaç hisse seçilecek?
- Komisyon ve slippage varsayımları ne olacak?
