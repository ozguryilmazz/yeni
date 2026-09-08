from enum import Enum


class WalletType(str, Enum):
    SPOT = "SPOT"
    USDM_FUTURES = "USDM_FUTURES"
    FUNDING = "FUNDING"


# Binance universal transfer (/sapi/v1/asset/transfer) tip kodları.
# https://binance-docs.github.io/apidocs/spot/en/#user-universal-transfer
TRANSFER_TYPE_MAP: dict[tuple[WalletType, WalletType], str] = {
    (WalletType.SPOT, WalletType.USDM_FUTURES): "MAIN_UMFUTURE",
    (WalletType.USDM_FUTURES, WalletType.SPOT): "UMFUTURE_MAIN",
    (WalletType.SPOT, WalletType.FUNDING): "MAIN_FUNDING",
    (WalletType.FUNDING, WalletType.SPOT): "FUNDING_MAIN",
    (WalletType.USDM_FUTURES, WalletType.FUNDING): "UMFUTURE_FUNDING",
    (WalletType.FUNDING, WalletType.USDM_FUTURES): "FUNDING_UMFUTURE",
}
