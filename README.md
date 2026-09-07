# Binance Cüzdan Yöneticisi (Masaüstü)

Binance hesabına bağlanıp Spot / Futures (USDⓈ-M) / Funding cüzdan bakiyelerini gösteren
ve cüzdanlar arası coin transferi yapılabilen, **PySide6 tabanlı Python masaüstü
uygulaması**. Genel yol haritası için bkz. [PLAN.md](./PLAN.md).

> Bu bir web uygulaması değildir — tarayıcı veya sunucu gerekmez. `python -m app.main`
> ile çalıştırılan tek bir masaüstü programıdır; tüm veriler kendi bilgisayarınızdaki
> local bir SQLite dosyasında tutulur.

## Özellikler

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
2. **Binance Hesabı Bağla** ile bir API key/secret girin.

   ⚠️ **Önemli:** Binance hesabınızda yeni bir API key oluştururken:
   - Sadece **Enable Reading** (+ istersen Spot/Futures trading) izni açın
   - **Enable Withdrawals'ı kesinlikle açmayın** — uygulama böyle key'leri zaten
     otomatik reddediyor, ama önlem olarak siz de kapalı tutun
   - Mümkünse IP whitelist ekleyin

3. Bağlandıktan sonra Spot/Futures/Funding bakiyelerinizi **Yenile** butonuyla görün.
4. **Cüzdanlar Arası Transfer** bölümünden küçük bir miktarla (ör. 1 USDT) deneme yapın —
   bu gerçek bir fon hareketi yaratır.

## Proje Yapısı

```
app/
  main.py             # Giriş noktası (QApplication)
  config.py           # Local veri dizini / DB yolu
  database.py         # SQLAlchemy engine + session (SQLite)
  models.py           # User, ApiCredential, Transfer
  security.py         # Parola hash/doğrulama (bcrypt)
  crypto.py           # API secret şifreleme (Fernet + OS keyring)
  binance_client.py   # İmzalı Binance REST istekleri (senkron)
  transfer_types.py   # Cüzdan tipleri ve Binance transfer tip eşlemesi
  repository.py       # İş mantığı (auth, credential, wallet, transfer)
  workers.py          # Ağ çağrılarını arayüzü kilitlemeden çalıştıran QThread'ler
  ui/
    login_window.py   # Giriş / kayıt ekranı
    main_window.py     # Ana pencere: bağlı hesaplar, bakiyeler, transfer
tests/                # pytest paketi (Binance çağrıları mock'lanarak)
```

## Testler

```bash
pip install -r requirements-dev.txt
pytest
```

19 test: auth (kayıt/giriş), credential bağlama (withdrawal reddi, şifreleme, silme),
bakiye normalize etme, transfer (yön eşlemesi, başarı/başarısızlık loglama, geçmiş).

## Güvenlik

- API key/secret'lar local DB'de Fernet ile şifreli saklanır, hiçbir log'da plaintext görünmez.
- Ana şifreleme anahtarı OS'in güvenli kimlik bilgisi deposunda tutulur (mümkün olduğunda).
- Bağlama isteğinde Binance'dan gerçek API key izinleri sorgulanır; withdrawal izni açık
  key'ler reddedilir.
- Uygulama Binance **mainnet** ile çalışır; transfer öncesi tutarı ve yönü dikkatlice kontrol edin.
