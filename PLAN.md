# Binance Cüzdan Yöneticisi — İş Akış Planı

## 1. Amaç

Binance hesabını API key ile bağlayıp:

- **Faz 1 (bu etap):** Spot, Futures (USDⓈ-M) ve Funding cüzdan bakiyelerini tek ekranda görüntülemek, cüzdanlar arası coin transferi yapmak.
- **Faz 2 (ilerleyen etap):** Spot/Futures üzerinde emir (işlem) verme.

**Not:** İlk sürüm web uygulaması olarak planlanmış ve öyle uygulanmıştı; kullanıcı tercihiyle
**Python masaüstü GUI (PySide6)** uygulamasına dönüştürüldü. Tarayıcı veya sunucuya gerek yok —
tek bir Python programı, veriler local SQLite'ta.

## 2. Teknoloji Yığını

| Katman | Seçim |
|---|---|
| Uygulama | Python 3.11+, tek masaüstü program (sunucu yok) |
| UI | PySide6 (Qt for Python, LGPL — PyQt6'nın aksine dağıtımda lisans sorunu çıkarmaz) |
| Veritabanı | Local SQLite (kullanıcının kendi bilgisayarında, `app.db`) |
| ORM | SQLAlchemy 2.0 |
| Kullanıcı/profil | Local login sistemi (bcrypt ile parola hash), aynı bilgisayarda birden fazla profil |
| Şifreleme | API secret'lar AES-256 (Fernet) ile local DB'de şifreli; ana anahtar OS keyring'de (Windows Credential Manager / macOS Keychain / Linux Secret Service), yoksa izinleri kısıtlı local dosyada |
| Binance entegrasyonu | REST API, HMAC-SHA256 imzalama, senkron `httpx.Client` (QThread worker'larda çalışır, UI'yı kilitlemez) |
| Test | pytest (Binance çağrıları mock'lanarak) |

## 3. Mimari Akış

```
PySide6 UI (login_window / main_window)
   → QThread worker'lar (ConnectCredentialWorker, LoadBalancesWorker, CreateTransferWorker)
      → repository.py (iş mantığı: auth, credential, wallet, transfer)
         → binance_client.py (imzalı REST istekleri) → Binance REST API (mainnet)
         → SQLAlchemy session → local SQLite (app.db)
```

Ağ çağrısı gerektiren işlemler (credential doğrulama, bakiye çekme, transfer) arayüzü
kilitlememesi için QThread'lerde çalışır; sonuçlar Qt sinyalleriyle ana thread'e döner.

## 4. Fazlar

### Faz 0 — Proje Altyapısı ✅
- `app/` paketi: config (local veri dizini), database (SQLite engine/session), models
- `requirements.txt` / `requirements-dev.txt`

### Faz 1 — Kullanıcı/Profil Yönetimi ✅
- `users` tablosu (email, password_hash, created_at)
- Local login/register ekranı (PySide6), bcrypt ile parola doğrulama
- Oturum durumu bellekte tutulur (JWT/token gerekmez — ağ isteği yok)

### Faz 2 — Binance Hesabı Bağlama ✅
- `api_credentials` tablosu (user_id, label, encrypted_api_key, encrypted_api_secret, created_at)
- Fernet şifreleme servisi (`crypto.py`), ana anahtar OS keyring'den
- "Binance Hesabı Bağla" dialog'u (API key + secret)
- Bağlantı testi: `/sapi/v1/account/apiRestrictions` ile gerçek izin doğrulaması
- **Zorunlu kontrol:** withdrawal (para çekme) yetkisi olan key'ler reddedilir

### Faz 3 — Bakiye Görüntüleme ✅
- `repository.get_wallet_summary`: Spot (`/api/v3/account`), Futures (`/fapi/v2/account`),
  Funding (`/sapi/v1/asset/get-funding-asset`) bakiyelerini normalize eder (sıfır bakiyeler filtrelenir)
- Ana pencerede Spot / Futures / Funding tabloları + Yenile butonu

### Faz 4 — Spot ⇄ Futures ⇄ Funding Transfer ✅
- `repository.create_transfer`: Binance universal transfer API (`/sapi/v1/asset/transfer`)
  entegrasyonu (6 yönlü tip eşlemesi: `transfer_types.py`)
- Ön validasyon: aynı cüzdan reddi, desteklenmeyen yön reddi
- `transfers` tablosunda işlem geçmişi (asset, miktar, yön, Binance tranId, durum, hata mesajı, tarih)
- Ana pencerede transfer formu + geçmiş tablosu

### Faz 5 — Kalite ✅
- pytest paketi: auth, credential (withdrawal reddi/şifreleme/silme), wallet (normalize etme,
  hata durumları), transfer (yön eşlemesi, başarı/başarısızlık loglama, geçmiş sıralaması)
- PySide6 UI'ın headless (offscreen) modda uçtan uca (kayıt→bağlama→bakiye→transfer) çalıştığı doğrulandı

### Faz 6 — İleride: İşlem (Trading)
- Spot / Futures market-limit emir verme, kaldıraç ayarlama
- Açık emir/pozisyon görüntüleme, emir iptali
- WebSocket ile canlı fiyat/pozisyon akışı

## 5. Veri Modeli (özet)

```
users(id, email, password_hash, created_at)
api_credentials(id, user_id, label, encrypted_api_key, encrypted_api_secret,
                 can_withdraw, permissions_verified_at, created_at)
transfers(id, user_id, credential_id, asset, amount, from_wallet, to_wallet,
          binance_tran_id, status, error_message, created_at)
```

## 6. Güvenlik Notları

- API secret hiçbir zaman log/hata mesajı içinde plaintext görünmez; DB'de Fernet ile şifrelenir.
- Kullanıcıya Binance tarafında IP whitelist kullanması önerilir.
- Withdrawal izni olan key'lerin bağlanması engellenir.
- Mainnet ile çalışıldığı için transfer öncesi tutar/coin/yön doğrulaması sıkı tutulur.

## 7. Sıradaki Adım

Faz 0-5 tamamlandı. Sıradaki adım Faz 6 — trading özellikleri (kullanıcı onayı ile başlanacak).
