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


PERIOD_KLINE_INTERVAL = {"1h": "1h", "4h": "4h", "24h": "1d"}
"""Piyasa sekmesindeki dönem seçimini Binance kline interval'ine eşler. 24h için takvim
günü mumu ('1d') kullanılır; bu da hem anlık fiyatı hem de bir önceki güne göre hacim
değişimini tek bir kline isteğinden hesaplamayı mümkün kılar."""


def get_futures_kline_stats(symbol: str, interval: str, client: httpx.Client | None = None) -> dict:
    """Verilen sembol/aralık için son iki mumu çeker: anlık fiyatı (son mumun kapanışı),
    o mumun açılış/kapanışına göre yüzde fiyat değişimini, quote (USDT) hacmini ve bir
    önceki muma göre yüzde hacim değişimini döner. `client` verilirse (toplu çağrılarda)
    o paylaşılan bağlantı havuzu kullanılır; verilmezse tek seferlik bir istemci açılır."""
    params = {"symbol": symbol, "interval": interval, "limit": 2}
    if client is not None:
        response = client.get("/fapi/v1/klines", params=params)
        _raise_for_error(response)
        result = response.json()
    else:
        result = _public_get("/fapi/v1/klines", params, timeout=5)

    if not result:
        return {"last_price": 0.0, "quote_volume": 0.0, "price_change_percent": 0.0, "volume_change_percent": 0.0}

    current = result[-1]
    open_price = float(current[1])
    close_price = float(current[4])
    quote_volume = float(current[7])
    price_change_percent = ((close_price - open_price) / open_price * 100) if open_price else 0.0

    volume_change_percent = 0.0
    if len(result) >= 2:
        previous_volume = float(result[-2][7])
        if previous_volume:
            volume_change_percent = (quote_volume - previous_volume) / previous_volume * 100

    return {
        "last_price": close_price,
        "quote_volume": quote_volume,
        "price_change_percent": price_change_percent,
        "volume_change_percent": volume_change_percent,
    }


INTERVAL_MS_MAP = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def get_futures_historical_klines(
    symbol: str, interval: str, start_ms: int, end_ms: int, client: httpx.Client | None = None
) -> list[list]:
    """GET /fapi/v1/klines — [start_ms, end_ms] aralığındaki TÜM mumları sayfalayarak
    çeker (tek istek en fazla 1500 mum döner). Backtest için geçmiş veri toplarken
    kullanılır; `get_futures_kline_stats`'in aksine sınırsız uzunlukta bir aralığı
    kapsayabilir."""
    interval_ms = INTERVAL_MS_MAP[interval]
    limit = 1500
    owns_client = client is None
    if owns_client:
        client = httpx.Client(base_url=BINANCE_FUTURES_BASE_URL, timeout=15)

    all_klines: list[list] = []
    try:
        cursor = start_ms
        while cursor <= end_ms:
            params = {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": limit}
            response = client.get("/fapi/v1/klines", params=params)
            _raise_for_error(response)
            batch = response.json()
            if not batch:
                break
            all_klines.extend(batch)
            cursor = int(batch[-1][0]) + interval_ms
            if len(batch) < limit:
                break
    finally:
        if owns_client:
            client.close()

    return all_klines


def get_futures_market_overview(period: str) -> list[dict]:
    """USDT-M perpetual futures sembolleri için verilen dönemdeki anlık fiyatı, toplam işlem
    hacmini (USDT), yüzde fiyat değişimini ve bir önceki eşit uzunluktaki döneme göre yüzde
    hacim değişimini döner.

    period: '1h', '4h' veya '24h'. Her sembol için ayrı bir kline isteği gerektiğinden
    (yüzlerce sembol) istekler paylaşılan bir bağlantı havuzu üzerinden thread havuzunda
    paralel çalıştırılır. Tek bir sembolün isteği başarısız/zaman aşımına uğrarsa o sembol
    atlanır — tüm listeyi etkilemesi veya beklemeyi uzatması engellenir.
    """
    if period not in PERIOD_KLINE_INTERVAL:
        raise ValueError(f"Desteklenmeyen dönem: {period}")

    interval = PERIOD_KLINE_INTERVAL[period]
    symbols = set(get_futures_perpetual_symbols())

    overview: list[dict] = []
    with httpx.Client(base_url=BINANCE_FUTURES_BASE_URL, timeout=5) as client:
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_symbol = {
                executor.submit(get_futures_kline_stats, symbol, interval, client): symbol for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    stats = future.result()
                except Exception:  # noqa: BLE001 - ağ hatası/zaman aşımı olan tek bir sembol atlanır
                    continue
                overview.append({"symbol": symbol, **stats})

    return overview
