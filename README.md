# Binance Spot ⇄ Futures Cüzdan & Transfer Uygulaması

Genel plan için bkz. [PLAN.md](./PLAN.md).

## Bu Etapta Yapılanlar (Faz 0 + Faz 1)

- FastAPI backend iskeleti (`backend/`)
- React + TypeScript frontend iskeleti (`frontend/`)
- PostgreSQL + Alembic migration altyapısı
- Kullanıcı kayıt / giriş / JWT (access + refresh token) auth akışı

Henüz Binance API bağlantısı, bakiye görüntüleme ve transfer özellikleri **eklenmedi** — bunlar sıradaki fazlar.

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
- `ENCRYPTION_MASTER_KEY`: Binance API secret'larını DB'de şifrelemek için kullanılacak (ileriki fazda). `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` ile üretin.

## Güvenlik

- Binance API key'leri asla plaintext saklanmaz/loglanmaz (bir sonraki fazda eklenecek).
- Withdrawal (para çekme) izni olan API key'lerin bağlanması engellenecek.
