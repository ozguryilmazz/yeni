from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.credential_lookup import get_user_credential
from app.api.deps import get_current_user
from app.core.crypto import decrypt_secret
from app.database import get_db
from app.models.transfer import Transfer
from app.models.user import User
from app.schemas.transfers import TransferRequest, TransferResponse
from app.services.binance_client import BinanceAPIError, create_universal_transfer
from app.services.transfer_types import TRANSFER_TYPE_MAP

router = APIRouter()


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transfer:
    if payload.from_wallet == payload.to_wallet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Kaynak ve hedef cüzdan aynı olamaz"
        )

    transfer_type = TRANSFER_TYPE_MAP.get((payload.from_wallet, payload.to_wallet))
    if transfer_type is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Desteklenmeyen transfer yönü")

    credential = get_user_credential(db, current_user, payload.credential_id)
    api_key = decrypt_secret(credential.encrypted_api_key)
    api_secret = decrypt_secret(credential.encrypted_api_secret)

    asset = payload.asset.upper()
    transfer = Transfer(
        user_id=current_user.id,
        credential_id=credential.id,
        asset=asset,
        amount=payload.amount,
        from_wallet=payload.from_wallet.value,
        to_wallet=payload.to_wallet.value,
        status="PENDING",
    )
    db.add(transfer)
    db.flush()

    try:
        result = await create_universal_transfer(api_key, api_secret, transfer_type, asset, str(payload.amount))
    except BinanceAPIError as exc:
        transfer.status = "FAILED"
        transfer.error_message = exc.message
        db.commit()
        db.refresh(transfer)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Transfer başarısız: {exc.message}"
        ) from exc

    transfer.status = "SUCCESS"
    tran_id = result.get("tranId")
    transfer.binance_tran_id = str(tran_id) if tran_id is not None else None
    db.commit()
    db.refresh(transfer)

    return transfer


@router.get("", response_model=list[TransferResponse])
def list_transfers(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Transfer]:
    return (
        db.query(Transfer)
        .filter(Transfer.user_id == current_user.id)
        .order_by(Transfer.created_at.desc())
        .limit(limit)
        .all()
    )
