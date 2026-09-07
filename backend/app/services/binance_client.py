import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from app.config import get_settings

settings = get_settings()


class BinanceAPIError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _sign(params: dict, api_secret: str) -> dict:
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return {**params, "signature": signature}


async def _signed_get(base_url: str, path: str, api_key: str, api_secret: str) -> dict:
    params = _sign({"timestamp": int(time.time() * 1000), "recvWindow": 5000}, api_secret)
    headers = {"X-MBX-APIKEY": api_key}

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        response = await client.get(path, params=params, headers=headers)

    if response.status_code != 200:
        try:
            data = response.json()
        except ValueError:
            data = {}
        raise BinanceAPIError(data.get("msg", "Binance API isteği başarısız oldu"), data.get("code"))

    return response.json()


async def get_api_restrictions(api_key: str, api_secret: str) -> dict:
    """GET /sapi/v1/account/apiRestrictions — API key'in gerçek izinlerini döner
    (enableReading, enableSpotAndMarginTrading, enableFutures, enableWithdrawals, ...).
    """
    return await _signed_get(settings.binance_base_url, "/sapi/v1/account/apiRestrictions", api_key, api_secret)


async def get_spot_account(api_key: str, api_secret: str) -> dict:
    return await _signed_get(settings.binance_base_url, "/api/v3/account", api_key, api_secret)


async def get_futures_account(api_key: str, api_secret: str) -> dict:
    return await _signed_get(settings.binance_futures_base_url, "/fapi/v2/account", api_key, api_secret)
