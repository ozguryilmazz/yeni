import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import httpx

BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"


class BinanceAPIError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _sign(params: dict, api_secret: str) -> dict:
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return {**params, "signature": signature}


def _raise_for_error(response: httpx.Response) -> None:
    if response.status_code != 200:
        try:
            data = response.json()
        except ValueError:
            data = {}
        raise BinanceAPIError(data.get("msg", "Binance API isteği başarısız oldu"), data.get("code"))


def _signed_get(base_url: str, path: str, api_key: str, api_secret: str) -> dict:
    params = _sign({"timestamp": int(time.time() * 1000), "recvWindow": 5000}, api_secret)
    headers = {"X-MBX-APIKEY": api_key}

    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.get(path, params=params, headers=headers)

    _raise_for_error(response)
    return response.json()


def _signed_post(
    base_url: str, path: str, api_key: str, api_secret: str, extra_params: dict | None = None
) -> list | dict:
    base_params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000, **(extra_params or {})}
    params = _sign(base_params, api_secret)
    headers = {"X-MBX-APIKEY": api_key}

    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(path, params=params, headers=headers)

    _raise_for_error(response)
    return response.json()


def get_api_restrictions(api_key: str, api_secret: str) -> dict:
    """GET /sapi/v1/account/apiRestrictions — API key'in gerçek izinlerini döner
    (enableReading, enableSpotAndMarginTrading, enableFutures, enableWithdrawals, ...).
    """
    return _signed_get(BINANCE_BASE_URL, "/sapi/v1/account/apiRestrictions", api_key, api_secret)


def get_spot_account(api_key: str, api_secret: str) -> dict:
    return _signed_get(BINANCE_BASE_URL, "/api/v3/account", api_key, api_secret)


def get_futures_account(api_key: str, api_secret: str) -> dict:
    return _signed_get(BINANCE_FUTURES_BASE_URL, "/fapi/v2/account", api_key, api_secret)


def get_funding_wallet(api_key: str, api_secret: str) -> list[dict]:
    result = _signed_post(BINANCE_BASE_URL, "/sapi/v1/asset/get-funding-asset", api_key, api_secret)
    return result if isinstance(result, list) else []


def create_universal_transfer(api_key: str, api_secret: str, transfer_type: str, asset: str, amount: str) -> dict:
    """POST /sapi/v1/asset/transfer — cüzdanlar arası (spot/futures/funding) coin transferi."""
    extra_params = {"type": transfer_type, "asset": asset, "amount": amount}
    result = _signed_post(BINANCE_BASE_URL, "/sapi/v1/asset/transfer", api_key, api_secret, extra_params)
    return result if isinstance(result, dict) else {}


# ---- Piyasa verisi (public, API key gerekmez) -----------------------------


def _public_get(path: str, params: dict | None = None, timeout: float = 10) -> dict | list:
    with httpx.Client(base_url=BINANCE_FUTURES_BASE_URL, timeout=timeout) as client:
        response = client.get(path, params=params)
    _raise_for_error(response)
    return response.json()


def get_futures_perpetual_symbols() -> list[str]:
    """GET /fapi/v1/exchangeInfo — şu an işlem gören USDT-M perpetual futures sembolleri."""
    data = _public_get("/fapi/v1/exchangeInfo")
    return [
        s["symbol"]
        for s in data.get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"
    ]


def get_futures_24h_tickers() -> list[dict]:
    """GET /fapi/v1/ticker/24hr (sembolsüz) — tüm futures sembolleri için tek istekte 24s istatistik."""
    result = _public_get("/fapi/v1/ticker/24hr")
    return result if isinstance(result, list) else []


def get_futures_kline_stats(symbol: str, interval: str, client: httpx.Client | None = None) -> dict:
    """Verilen sembol/aralık için son mumun quote (USDT) hacmini ve o mumun açılış/kapanışına
    göre yüzde fiyat değişimini döner. `client` verilirse (toplu çağrılarda) o paylaşılan
    bağlantı havuzu kullanılır; verilmezse tek seferlik bir istemci açılır."""
    params = {"symbol": symbol, "interval": interval, "limit": 1}
    if client is not None:
        response = client.get("/fapi/v1/klines", params=params)
        _raise_for_error(response)
        result = response.json()
    else:
        result = _public_get("/fapi/v1/klines", params, timeout=5)

    if not result:
        return {"quote_volume": 0.0, "price_change_percent": 0.0}

    open_price = float(result[0][1])
    close_price = float(result[0][4])
    quote_volume = float(result[0][7])
    price_change_percent = ((close_price - open_price) / open_price * 100) if open_price else 0.0
    return {"quote_volume": quote_volume, "price_change_percent": price_change_percent}


def get_futures_market_overview(period: str) -> list[dict]:
    """USDT-M perpetual futures sembolleri için verilen dönemdeki toplam işlem hacmini (USDT)
    ve yüzde fiyat değişimini döner.

    period: '1h', '4h' veya '24h'. 24h için Binance'ın tek istekte tüm sembolleri döndüren
    ticker'ı kullanılır; 1h/4h için her sembol için ayrı bir kline isteği gerektiğinden
    (yüzlerce sembol) istekler paylaşılan bir bağlantı havuzu üzerinden thread havuzunda
    paralel çalıştırılır. Tek bir sembolün isteği başarısız/zaman aşımına uğrarsa o sembol
    atlanır — tüm listeyi etkilemesi veya beklemeyi uzatması engellenir.
    """
    symbols = set(get_futures_perpetual_symbols())

    if period == "24h":
        tickers = get_futures_24h_tickers()
        return [
            {
                "symbol": t["symbol"],
                "quote_volume": float(t["quoteVolume"]),
                "price_change_percent": float(t["priceChangePercent"]),
            }
            for t in tickers
            if t.get("symbol") in symbols
        ]

    if period not in ("1h", "4h"):
        raise ValueError(f"Desteklenmeyen dönem: {period}")

    overview: list[dict] = []
    with httpx.Client(base_url=BINANCE_FUTURES_BASE_URL, timeout=5) as client:
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_symbol = {
                executor.submit(get_futures_kline_stats, symbol, period, client): symbol for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    stats = future.result()
                except Exception:  # noqa: BLE001 - ağ hatası/zaman aşımı olan tek bir sembol atlanır
                    continue
                overview.append({"symbol": symbol, **stats})

    return overview
