from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.transfer_types import WalletType


class TransferRequest(BaseModel):
    credential_id: UUID | None = None
    asset: str = Field(min_length=1, max_length=20)
    amount: Decimal = Field(gt=0)
    from_wallet: WalletType
    to_wallet: WalletType


class TransferResponse(BaseModel):
    id: UUID
    asset: str
    amount: Decimal
    from_wallet: str
    to_wallet: str
    binance_tran_id: str | None
    status: str
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
