# Binance Spot ⇄ Futures Cüzdan & Transfer Uygulaması

Genel plan için bkz. [PLAN.md](./PLAN.md).

## Bu Etapta Yapılanlar (Faz 0-4 tamamlandı)

- FastAPI backend iskeleti (`backend/`)
- React + TypeScript frontend iskeleti (`frontend/`)
- PostgreSQL + Alembic migration altyapısı
- Kullanıcı kayıt / giriş / JWT (access + refresh token) auth akışı
- Binance API key/secret'ı DB'de Fernet ile şifreli saklama (`ApiCredential`)
- Bağlama sırasında Binance `/sapi/v1/account/apiRestrictions` ile izin doğrulaması:
  **withdrawal izni açık key'ler otomatik reddedilir**
- Bağlı hesapları listeleme / kaldırma; Dashboard'da bağlama formu
- `GET /api/wallet/balances`: Spot, Futures (USDⓈ-M) ve Funding cüzdan bakiyelerini
  Binance'dan çekip normalize eder (sıfır bakiyeler filtrelenir)
- Dashboard'da Spot/Futures/Funding kartları + yenile butonu
- `POST /api/transfers`: Spot ⇄ Futures ⇄ Funding arasında coin transferi
  (Binance universal transfer API, `transfers` tablosunda geçmiş kaydı)
- `GET /api/transfers`: transfer geçmişi; Dashboard'da transfer formu + geçmiş tablosu

Bu, planın (bkz. PLAN.md) Faz 1 hedefini tamamlıyor: bakiye görüntüleme + cüzdanlar
arası transfer. **İşlem (trading) özellikleri henüz eklenmedi** — sıradaki faz (Faz 6).

## Geliştirme Ortamını Ayağa Kaldırma

### Docker Compose ile (önerilen)

```bash
cp backend/.env.example backend/.env
# backend/.env içindeki JWT_SECRET_KEY ve ENCRYPTION_MASTER_KEY değerlerini değiştirin

docker compose up --build
```

- Backend: http://localhost:8000 (Swagger: http://localhost:8000/docs)
- Frontend: http://localhost:5173

### Manuel (Docker'sız)

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # ve DATABASE_URL'i lokal Postgres'inize göre düzenleyin
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Ortam Değişkenleri

`backend/.env.example` dosyasına bakın. Özellikle:

- `JWT_SECRET_KEY`: `openssl rand -hex 32` ile üretin.
- `ENCRYPTION_MASTER_KEY`: Binance API secret'larını DB'de şifrelemek için kullanılır (herhangi bir uzunlukta rastgele string olabilir, `openssl rand -hex 32` ile üretin — Fernet key'e otomatik türetilir).

## Güvenlik

- Binance API key/secret'ları DB'de Fernet (AES-128-CBC + HMAC) ile şifreli saklanır, hiçbir response/log'da plaintext dönmez.
- Bağlama isteğinde Binance'dan gerçek API key izinleri sorgulanır (`apiRestrictions`); withdrawal izni açık olan key'ler **reddedilir**.
- Kullanıcıya Binance panelinden IP whitelist kullanması önerilir.
- Uygulama Binance **mainnet** ile çalışır; her transfer gerçek fon hareketi yaratır.
