# Binance Spot ⇄ Futures Transfer Uygulaması — İş Akış Planı

## 1. Amaç

Kullanıcıların kendi Binance hesaplarını API key ile bağlayıp:

- **Faz 1 (bu etap):** Spot, Futures (USDⓈ-M) ve Funding cüzdan bakiyelerini tek ekranda görüntülemek, cüzdanlar arası coin transferi yapmak.
- **Faz 2 (ilerleyen etap):** Spot/Futures üzerinde emir (işlem) verme.

## 2. Teknoloji Yığını

| Katman | Seçim |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Frontend | React + TypeScript (Vite) |
| Veritabanı | PostgreSQL |
| ORM / Migration | SQLAlchemy + Alembic |
| Auth | JWT (access + refresh token), bcrypt ile parola hash |
| Şifreleme | API secret'lar AES-256 (Fernet) ile DB'de şifreli; master key ortam değişkeninden |
| Binance entegrasyonu | REST API, HMAC-SHA256 imzalama (python-binance veya doğrudan `httpx`) |
| Deployment | Docker Compose (backend, frontend, postgres) |

## 3. Mimari Akış

```
React SPA → FastAPI Backend → PostgreSQL (kullanıcı + şifreli API key + transfer logları)
                            → Binance REST API (mainnet, kullanıcı adına imzalı istek)
```

Frontend hiçbir zaman API secret görmez; tüm imzalama backend'de yapılır.

## 4. Fazlar

### Faz 0 — Proje Altyapısı
- Repo yapısı: `backend/`, `frontend/`, `docker-compose.yml`
- FastAPI iskeleti + `/health` endpoint
- React (Vite+TS) iskeleti
- PostgreSQL + Alembic migration altyapısı
- `.env` / secrets yönetimi

### Faz 1 — Kullanıcı Yönetimi & Auth
- `users` tablosu (email, password_hash, created_at)
- Kayıt / Login / refresh-token endpoint'leri
- Frontend: Login / Register sayfaları, korumalı route'lar

### Faz 2 — Binance Hesabı Bağlama
- `api_credentials` tablosu (user_id, label, encrypted_api_key, encrypted_api_secret, created_at)
- Şifreleme servisi (Fernet/AES-256-GCM)
- "Binance Hesabı Bağla" formu (API key + secret)
- Bağlantı testi: `/api/v3/account` (spot) ve `/fapi/v2/account` (futures) ile read-only doğrulama
- **Zorunlu kontrol:** girilen key'de withdrawal (para çekme) yetkisi olmamalı; UI'da uyarı gösterilir

### Faz 3 — Bakiye Görüntüleme
- `GET /api/wallet/spot`, `GET /api/wallet/futures`, `GET /api/wallet/funding`
- Dashboard: Spot / Futures / Funding kartları, coin bazlı tablo, toplam USD karşılığı
- Manuel yenile + kısa süreli backend cache (Binance rate-limit/weight yönetimi)

### Faz 4 — Spot ⇄ Futures ⇄ Funding Transfer
- `POST /api/transfer` (from_wallet, to_wallet, asset, amount)
- Binance `/sapi/v1/asset/transfer` entegrasyonu (MAIN_UMFUTURE, UMFUTURE_MAIN, MAIN_FUNDING, FUNDING_MAIN, ...)
- Ön validasyon: yeterli bakiye, min/max limit
- `transfers` tablosunda işlem geçmişi (asset, miktar, yön, Binance tranId, durum, tarih)
- Frontend: transfer formu + geçmiş tablosu
- Binance hata kodlarının kullanıcı dostu mesaja çevrilmesi

### Faz 5 — Güvenlik & Kalite
- Login brute-force koruması / rate limiting
- Audit log (kim, ne zaman, ne transfer etti)
- pytest (Binance client mock'lanarak) + Playwright E2E (login → bağla → bakiye → transfer)

### Faz 6 — İleride: İşlem (Trading)
- Spot / Futures market-limit emir verme, kaldıraç ayarlama
- Açık emir/pozisyon görüntüleme, emir iptali
- WebSocket ile canlı fiyat/pozisyon akışı

## 5. Veri Modeli (özet)

```
users(id, email, password_hash, created_at)
api_credentials(id, user_id, label, encrypted_api_key, encrypted_api_secret,
                 permissions_verified_at, created_at)
transfers(id, user_id, asset, amount, from_wallet, to_wallet,
          binance_tran_id, status, created_at)
```

## 6. Güvenlik Notları

- API secret hiçbir zaman log/hata mesajı/response içinde plaintext dönmez.
- Kullanıcıya Binance tarafında IP whitelist kullanması önerilir.
- Withdrawal izni olan key'lerin bağlanması engellenir/uyarılır.
- Mainnet ile başlandığı için transfer öncesi tutar/coin/adres doğrulaması sıkı tutulur.

## 7. Sıradaki Adım

Faz 0 + Faz 1 (proje iskeleti + kullanıcı auth) ile implementasyona başlanabilir.
