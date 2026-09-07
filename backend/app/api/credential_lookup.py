from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.api_credential import ApiCredential
from app.models.user import User


def get_user_credential(db: Session, current_user: User, credential_id: UUID | None) -> ApiCredential:
    query = db.query(ApiCredential).filter(ApiCredential.user_id == current_user.id)
    credential = (
        query.filter(ApiCredential.id == credential_id).first()
        if credential_id is not None
        else query.order_by(ApiCredential.created_at.desc()).first()
    )

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bağlı bir Binance hesabı bulunamadı. Önce bir API key bağlayın.",
        )
    return credential
