import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiCredential(Base):
    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    can_withdraw: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permissions_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Python tarafında (mikrosaniye hassasiyetinde) üretilir; DB'nin CURRENT_TIMESTAMP'i
    # (özellikle SQLite'ta) saniye çözünürlüğünde olduğundan aynı saniyede bağlanan
    # hesapların sıralamasını belirsizleştirebiliyor.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
