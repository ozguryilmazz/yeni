from pydantic import BaseModel


class AssetBalance(BaseModel):
    asset: str
    free: float
    locked: float = 0.0


class FuturesBalance(BaseModel):
    asset: str
    wallet_balance: float
    available_balance: float
    unrealized_profit: float = 0.0


class WalletSummary(BaseModel):
    credential_id: str
    credential_label: str
    spot: list[AssetBalance]
    futures: list[FuturesBalance]
    funding: list[AssetBalance]
