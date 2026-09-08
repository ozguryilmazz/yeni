# Binance Cüzdan Yöneticisi (Masaüstü)

Binance hesabına bağlanıp Spot / Futures (USDⓈ-M) / Funding cüzdan bakiyelerini gösteren
ve cüzdanlar arası coin transferi yapılabilen, **PySide6 tabanlı Python masaüstü
uygulaması**. Genel yol haritası için bkz. [PLAN.md](./PLAN.md).

> Bu bir web uygulaması değildir — tarayıcı veya sunucu gerekmez. `python -m app.main`
> ile çalıştırılan tek bir masaüstü programıdır; tüm veriler kendi bilgisayarınızdaki
> local bir SQLite dosyasında tutulur.

## Özellikler

- Üç sekmeli ana pencere: **Piyasa** (herkese açık futures verisi), **Transferler**
  (hesap bağlama, bakiyeler, cüzdanlar arası transfer) ve **Tuzak Skoru** (whale
  trap & likidite takibi)
- **Piyasa** sekmesi: USDT-M perpetual futures'ta işlem gören tüm coinleri seçilen dönemdeki
  (son 1 saat / 4 saat / 24 saat) anlık fiyatı, işlem hacmi, hacim değişim yüzdesi ve fiyat
  değişim yüzdesiyle birlikte listeler; sütun başlıklarına tıklayarak sıralama
  değiştirilebilir. Binance hesabı bağlamaya gerek yok (public veri); tek bir sembolün
  isteği başarısız olursa (ağ hatası/zaman aşımı) o sembol atlanır, tüm liste beklemez.
  Bir satıra sağ tıklayıp **Sembolü Kopyala** ile coin çiftini panoya kopyalayıp Tuzak
  Skoru sekmesindeki sembol alanına (Ctrl+V veya **Yapıştır** butonuyla) yapıştırabilirsiniz.
- **Tuzak Skoru** sekmesi: tek bir sembol için (ör. BTCUSDT) teknik indikatör (RSI/MACD/MA)
  kullanmadan, tamamen piyasa yapıcı davranışına dayalı canlı bir "Whale Trap & Liquidity
  Tracker" izleyicisi:
  - **Open Interest & Hacim Diverjansı** — fiyat yatayken (canlı mark price'a göre 1s
    değişim < %0.5) OI'nin >%5 artması "sıkışma/birikim" olarak işaretlenir. OI ayrı,
    hızlı (5sn) bir REST döngüsüyle tazelenir (Binance'ta OI için resmi bir WebSocket
    push akışı yoktur — `GET /fapi/v1/openInterest`)
  - **Funding Rate Anomalisi** — funding rate < -%0.03 ise LONG squeeze ihtimali,
    > +%0.05 ise SHORT squeeze ihtimali. `<symbol>@markPrice@1s` WebSocket akışından
    ~1 saniyede bir güncellenir (15sn'lik REST poll'u beklemez — squeeze anındaki
    REST/WS gecikme farkını azaltır)
  - **Anlık Likidasyon Dinleyici** — son 60 saniyede likidasyon hacmi eşiği aşarsa,
    likide olan yönün TERSİNE bir tetik sinyali üretir
    (`wss://fstream.binance.com/ws/!forceOrder@arr`). Eşik sabit değildir: sembolün
    24s hacminin %0.5'i (min. 1.000.000 USDT taban) olarak dinamik hesaplanır — BTC
    için sıradan olan bir tutar, hacmi düşük bir altcoin için devasa olabilir. Ayrıca
    şelale (cascading liquidation) hâlâ hızlanıyorsa sinyal ERTELENİR — "bıçağı tutma"
    riskine karşı önce hızın kesilmesi beklenir
  - **Emir Defteri Dengesizliği** — bid/ask hacim oranı > 2.5 yukarı baskı, < 0.4 aşağı
    baskı sinyali üretir (`wss://fstream.binance.com/ws/<symbol>@depth20@100ms`).
    Spoofing (sahte duvar) filtresi: oran, ardışık 3 güncellemenin TAMAMINDA eşiği
    aşarsa tetiklenir — anlık bir sahte duvar bu ~300ms içinde genelde geri çekilir
  - Tüm modüller + hacim patlaması verisi bir **Tuzak Skoru** (Trap Scorer) ile 0-100
    arası tek bir skora ve yöne (LONG/SHORT) indirgenir. Likidasyon modülü tetiklendiğinde
    skor motoru otomatik olarak "kriz ağırlıklarına" geçer (emir defteri ağırlığı düşer,
    OI/likidasyon ağırlığı artar — bir likidasyon patlaması sırasında emir defteri
    güvenilirliğini kaybeder). Sadece bilgi amaçlıdır, otomatik işlem açmaz
- Aynı bilgisayarda birden fazla profil/hesap için basit bir giriş sistemi (local, şifreler bcrypt ile hash'lenir)
- Binance API key/secret'ı local SQLite'ta Fernet ile şifreli saklama; ana şifreleme
  anahtarı işletim sisteminin güvenli kimlik bilgisi deposunda tutulur (Windows Credential
  Manager / macOS Keychain / Linux Secret Service — kullanılamıyorsa izinleri kısıtlı bir
  local dosyaya düşülür)
- Bağlama sırasında Binance'ın gerçek API key izinleri (`apiRestrictions`) sorgulanır;
  **withdrawal (para çekme) izni açık key'ler otomatik reddedilir**
- Spot / Futures / Funding bakiyelerini tek pencerede görüntüleme
- Cüzdanlar arası (Spot ⇄ Futures ⇄ Funding) coin transferi + transfer geçmişi
- Uygulama Binance **mainnet** ile çalışır — işlem (trading) özellikleri henüz yok, ilerleyen bir etapta eklenecek

## Kurulum ve Çalıştırma

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

Uygulama ilk açılışta local veri dizininde (`~/.local/share/BinanceWalletManager` /
macOS'ta `~/Library/Application Support/BinanceWalletManager` / Windows'ta
`%APPDATA%\BinanceWalletManager`) bir SQLite dosyası (`app.db`) oluşturur.

## Kullanım

1. Açılan pencerede **Kayıt Ol** sekmesinden bir profil oluşturun (e-posta + şifre, en az 8 karakter).
2. Ana pencerede **Piyasa** sekmesi hemen açılır — Binance hesabı bağlamadan futures
   coinlerini hacme göre inceleyebilirsiniz.
3. **Transferler** sekmesine geçip **Binance Hesabı Bağla** ile bir API key/secret girin.

   ⚠️ **Önemli:** Binance hesabınızda yeni bir API key oluştururken:
   - Sadece **Enable Reading** (+ istersen Spot/Futures trading) izni açın
   - Cüzdanlar arası transfer yapacaksanız **Permits Universal Transfer** iznini de açın
     (bu izin kapalıyken transfer "not authorized" hatası verir)
   - **Enable Withdrawals'ı kesinlikle açmayın** — uygulama böyle key'leri zaten
     otomatik reddediyor, ama önlem olarak siz de kapalı tutun
   - Mümkünse IP whitelist ekleyin

4. Bağlandıktan sonra Spot/Futures/Funding bakiyelerinizi **Yenile** butonuyla görün.
5. **Cüzdanlar Arası Transfer** bölümünden küçük bir miktarla (ör. 1 USDT) deneme yapın —
   bu gerçek bir fon hareketi yaratır.
6. **Tuzak Skoru** sekmesinde bir sembol girip (ör. BTCUSDT) **İzlemeyi Başlat**'a
   basın; Binance hesabı bağlamaya gerek yoktur (sadece public REST/WebSocket veri
   kullanılır). Skor ve modül detayları canlı güncellenir, **Durdur** ile
   bağlantılar kapatılır. Bu sekme bilgi amaçlıdır ve otomatik işlem açmaz.

## Proje Yapısı

```
app/
  main.py             # Giriş noktası (QApplication)
  config.py           # Local veri dizini / DB yolu
  database.py         # SQLAlchemy engine + session (SQLite)
  models.py           # User, ApiCredential, Transfer
  security.py         # Parola hash/doğrulama (bcrypt)
  crypto.py           # API secret şifreleme (Fernet + OS keyring)
  binance_client.py   # İmzalı Binance REST istekleri (senkron) + public piyasa verisi
  transfer_types.py   # Cüzdan tipleri ve Binance transfer tip eşlemesi
  repository.py       # İş mantığı (auth, credential, wallet, transfer, piyasa verisi)
  workers.py          # Ağ çağrılarını arayüzü kilitlemeden çalıştıran QThread'ler
  whale_tracker/      # "Tuzak Skoru": OI/funding/likidasyon/orderbook modülleri + scorer
    models.py           # ModuleSignal / TrapScoreResult veri sınıfları
    open_interest.py    # Modül A: OI & hacim diverjansı
    funding_rate.py      # Modül B: funding rate anomalisi
    liquidation.py       # Modül C: !forceOrder@arr likidasyon dinleyici
    orderbook.py          # Modül D: emir defteri dengesizliği
    volume_surge.py        # Hacim patlaması modülü
    scorer.py                # TrapScorer: modülleri 0-100 tek skora indirger
    rest_client.py             # Async Binance Futures REST çağrıları (OI/funding/klines)
    engine.py                    # WhaleTrapEngine: REST polling + WS dinleyicileri orkestre eder
    qt_bridge.py                  # WhaleTrackerThread: asyncio döngüsünü Qt sinyallerine bağlar
  ui/
    login_window.py   # Giriş / kayıt ekranı
    main_window.py     # Ana pencere: sekmeler (Piyasa, Transferler, Tuzak Skoru) + üst bilgi
    market_tab.py       # Piyasa sekmesi: futures hacim tablosu (1s/4s/24s, sıralanabilir)
    transfers_tab.py    # Transferler sekmesi: bağlı hesaplar, bakiyeler, transfer
    whale_tracker_tab.py # Tuzak Skoru sekmesi: canlı skor, modül detayları, olay günlüğü
tests/                # pytest paketi (Binance çağrıları mock'lanarak)
```

## Testler

```bash
pip install -r requirements-dev.txt
pytest
```

80 test: auth (kayıt/giriş), credential bağlama (withdrawal reddi, şifreleme, silme),
bakiye normalize etme, transfer (yön eşlemesi, başarı/başarısızlık loglama, geçmiş),
piyasa verisi (sembol filtreleme, anlık fiyat/hacim/hacim değişimi hesaplama, sıralama,
panoya kopyalama), sekme yapısı ve Tuzak Skoru modülleri (OI/funding/likidasyon/orderbook
mantığı, dinamik likidasyon eşiği, şelale hızlanma tespiti, spoof filtresi, dinamik
ağırlıklandırma, WebSocket mesaj ayrıştırma, engine orkestrasyonu — hepsi mock'lu,
gerçek ağ/WebSocket bağlantısı gerektirmez).

## Güvenlik

- API key/secret'lar local DB'de Fernet ile şifreli saklanır, hiçbir log'da plaintext görünmez.
- Ana şifreleme anahtarı OS'in güvenli kimlik bilgisi deposunda tutulur (mümkün olduğunda).
- Bağlama isteğinde Binance'dan gerçek API key izinleri sorgulanır; withdrawal izni açık
  key'ler reddedilir.
- Uygulama Binance **mainnet** ile çalışır; transfer öncesi tutarı ve yönü dikkatlice kontrol edin.
