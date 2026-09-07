from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.crypto import encrypt_secret
from app.database import get_db
from app.models.api_credential import ApiCredential
from app.models.user import User
from app.schemas.credentials import ConnectCredentialRequest, CredentialResponse
from app.services.binance_client import BinanceAPIError, get_api_restrictions

router = APIRouter()


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def connect_credential(
    payload: ConnectCredentialRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiCredential:
    try:
        restrictions = await get_api_restrictions(payload.api_key, payload.api_secret)
    except BinanceAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Binance API key doğrulanamadı: {exc.message}",
        ) from exc

    if restrictions.get("enableWithdrawals"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Bu API key'de para çekme (withdrawal) izni açık. Güvenlik nedeniyle sadece "
                "'Enable Reading' ve gerekirse 'Enable Spot & Margin/Futures Trading' izinleri "
                "açık olan bir API key kullanın; Binance panelinden withdrawal iznini kapatın."
            ),
        )

    credential = ApiCredential(
        user_id=current_user.id,
        label=payload.label,
        encrypted_api_key=encrypt_secret(payload.api_key),
        encrypted_api_secret=encrypt_secret(payload.api_secret),
        can_withdraw=bool(restrictions.get("enableWithdrawals")),
        permissions_verified_at=datetime.now(UTC),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)

    return credential


@router.get("", response_model=list[CredentialResponse])
def list_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApiCredential]:
    return (
        db.query(ApiCredential)
        .filter(ApiCredential.user_id == current_user.id)
        .order_by(ApiCredential.created_at.desc())
        .all()
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credential = (
        db.query(ApiCredential)
        .filter(ApiCredential.id == credential_id, ApiCredential.user_id == current_user.id)
        .first()
    )
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bağlı hesap bulunamadı")

    db.delete(credential)
    db.commit()
