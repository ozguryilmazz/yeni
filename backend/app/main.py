from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import auth, credentials, health, transfers, wallet
from app.config import get_settings
from app.core.rate_limit import limiter

settings = get_settings()

app = FastAPI(title="Binance Wallet & Transfer API")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["credentials"])
app.include_router(wallet.router, prefix="/api/wallet", tags=["wallet"])
app.include_router(transfers.router, prefix="/api/transfers", tags=["transfers"])
