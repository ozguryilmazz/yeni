from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.credential_lookup import get_user_credential
from app.api.deps import get_current_user
from app.core.crypto import decrypt_secret
from app.database import get_db
from app.models.user import User
from app.schemas.wallet import AssetBalance, FuturesBalance, WalletSummary
from app.services.binance_client import (
    BinanceAPIError,
    get_funding_wallet,
    get_futures_account,
    get_spot_account,
)

router = APIRouter()


@router.get("/balances", response_model=WalletSummary)
async def get_balances(
    credential_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WalletSummary:
    credential = get_user_credential(db, current_user, credential_id)
    api_key = decrypt_secret(credential.encrypted_api_key)
    api_secret = decrypt_secret(credential.encrypted_api_secret)

    try:
        spot_account = await get_spot_account(api_key, api_secret)
        futures_account = await get_futures_account(api_key, api_secret)
        funding_wallet = await get_funding_wallet(api_key, api_secret)
    except BinanceAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance'dan bakiye alınamadı: {exc.message}",
        ) from exc

    spot = [
        AssetBalance(asset=b["asset"], free=float(b["free"]), locked=float(b["locked"]))
        for b in spot_account.get("balances", [])
        if float(b["free"]) > 0 or float(b["locked"]) > 0
    ]

    futures = [
        FuturesBalance(
            asset=a["asset"],
            wallet_balance=float(a["walletBalance"]),
            available_balance=float(a["availableBalance"]),
            unrealized_profit=float(a.get("unrealizedProfit", 0)),
        )
        for a in futures_account.get("assets", [])
        if float(a["walletBalance"]) != 0
    ]

    funding = [
        AssetBalance(asset=f["asset"], free=float(f["free"]), locked=float(f.get("locked", 0)))
        for f in funding_wallet
        if float(f["free"]) > 0 or float(f.get("locked", 0)) > 0
    ]

    return WalletSummary(
        credential_id=str(credential.id),
        credential_label=credential.label,
        spot=spot,
        futures=futures,
        funding=funding,
    )
