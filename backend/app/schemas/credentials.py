from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectCredentialRequest(BaseModel):
    label: str = Field(default="default", max_length=100)
    api_key: str = Field(min_length=10, max_length=256)
    api_secret: str = Field(min_length=10, max_length=256)


class CredentialResponse(BaseModel):
    id: UUID
    label: str
    can_withdraw: bool
    permissions_verified_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
