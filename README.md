# Binance Cüzdan Yöneticisi (Masaüstü)

Binance hesabına bağlanıp Spot / Futures (USDⓈ-M) / Funding cüzdan bakiyelerini gösteren
ve cüzdanlar arası coin transferi yapılabilen, **PySide6 tabanlı Python masaüstü
uygulaması**. Genel yol haritası için bkz. [PLAN.md](./PLAN.md).

> Bu bir web uygulaması değildir — tarayıcı veya sunucu gerekmez. `python -m app.main`
> ile çalıştırılan tek bir masaüstü programıdır; tüm veriler kendi bilgisayarınızdaki
> local bir SQLite dosyasında tutulur.

## Özellikler

- İki sekmeli ana pencere: **Piyasa** (herkese açık futures verisi) ve **Transferler**
  (hesap bağlama, bakiyeler, cüzdanlar arası transfer)
- **Piyasa** sekmesi: USDT-M perpetual futures'ta işlem gören tüm coinleri seçilen dönemdeki
  (son 1 saat / 4 saat / 24 saat) işlem hacmine ve fiyat değişim yüzdesine göre listeler;
  sütun başlıklarına tıklayarak sıralama değiştirilebilir. Binance hesabı bağlamaya gerek yok
  (public veri); tek bir sembolün isteği başarısız olursa (ağ hatası/zaman aşımı) o sembol
  atlanır, tüm liste beklemez
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
  ui/
    login_window.py   # Giriş / kayıt ekranı
    main_window.py     # Ana pencere: sekmeler (Piyasa, Transferler) + üst bilgi
    market_tab.py       # Piyasa sekmesi: futures hacim tablosu (1s/4s/24s, sıralanabilir)
    transfers_tab.py    # Transferler sekmesi: bağlı hesaplar, bakiyeler, transfer
tests/                # pytest paketi (Binance çağrıları mock'lanarak)
```

## Testler

```bash
pip install -r requirements-dev.txt
pytest
```

37 test: auth (kayıt/giriş), credential bağlama (withdrawal reddi, şifreleme, silme),
bakiye normalize etme, transfer (yön eşlemesi, başarı/başarısızlık loglama, geçmiş),
piyasa verisi (sembol filtreleme, hacim hesaplama, sıralama) ve sekme yapısı.

## Güvenlik

- API key/secret'lar local DB'de Fernet ile şifreli saklanır, hiçbir log'da plaintext görünmez.
- Ana şifreleme anahtarı OS'in güvenli kimlik bilgisi deposunda tutulur (mümkün olduğunda).
- Bağlama isteğinde Binance'dan gerçek API key izinleri sorgulanır; withdrawal izni açık
  key'ler reddedilir.
- Uygulama Binance **mainnet** ile çalışır; transfer öncesi tutarı ve yönü dikkatlice kontrol edin.
