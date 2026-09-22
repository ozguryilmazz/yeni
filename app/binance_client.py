import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import ROUND_DOWN, Decimal
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


def _signed_get(
    base_url: str, path: str, api_key: str, api_secret: str, extra_params: dict | None = None
) -> list | dict:
    base_params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000, **(extra_params or {})}
    params = _sign(base_params, api_secret)
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


def _signed_delete(
    base_url: str, path: str, api_key: str, api_secret: str, extra_params: dict | None = None
) -> list | dict:
    base_params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000, **(extra_params or {})}
    params = _sign(base_params, api_secret)
    headers = {"X-MBX-APIKEY": api_key}

    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.delete(path, params=params, headers=headers)

    _raise_for_error(response)
    return response.json()


def get_api_restrictions(api_key: str, api_secret: str) -> dict:
    """GET /sapi/v1/account/apiRestrictions — API key'in gerçek izinlerini döner
    (enableReading, enableSpotAndMarginTrading, enableFutures, enableWithdrawals, ...).
    """
    return _signed_get(BINANCE_BASE_URL, "/sapi/v1/account/apiRestrictions", api_key, api_secret)


def has_futures_trading_permission(api_restrictions: dict) -> bool:
    """`get_api_restrictions()` sonucundan API key'in Futures işlem izni olup
    olmadığını döner. Canlı işlem motoru başlamadan önce bu kontrol yapılabilir."""
    return bool(api_restrictions.get("enableFutures"))


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


def _public_get(
    path: str, params: dict | None = None, timeout: float = 10, base_url: str = BINANCE_FUTURES_BASE_URL
) -> dict | list:
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
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


def get_futures_24h_tickers() -> list[dict]:
    """GET /fapi/v1/ticker/24hr (sembol verilmeden) — TÜM USDT-M futures
    sembolleri için 24 saatlik istatistikleri (quoteVolume dahil) TEK istekte
    döner. Coin tarama (screener, bkz. app.grid_trading.screener) gibi tüm
    sembollerin sadece 24s hacmine ihtiyaç duyan kullanımlar için
    get_futures_market_overview'dan çok daha ucuzdur (o fonksiyon sembol
    başına ayrı kline isteği atar; bunun tek bir toplu isteği var)."""
    data = _public_get("/fapi/v1/ticker/24hr", timeout=15)
    return data if isinstance(data, list) else []


# ---- Futures gerçek işlem (canlı) ------------------------------------------
#
# Bu fonksiyonlar Binance Futures MAINNET'ine (BINANCE_FUTURES_BASE_URL) gerçek
# para ile emir gönderir. Hiçbiri kendiliğinden çağrılmaz — yalnızca kullanıcının
# açıkça başlattığı canlı işlem motoru (app.live_trading) tarafından kullanılır.


def get_futures_symbol_info(symbol: str) -> dict:
    """GET /fapi/v1/exchangeInfo — verilen sembolün emir filtrelerini (LOT_SIZE,
    PRICE_FILTER, MIN_NOTIONAL vb.) döner. Emir miktarı/fiyatını borsanın kabul
    ettiği hassasiyete yuvarlamak için kullanılır (bkz. round_quantity_to_lot_size,
    round_price_to_tick_size) — yanlış hassasiyetle gönderilen emirler Binance
    tarafından reddedilir."""
    data = _public_get("/fapi/v1/exchangeInfo")
    for s in data.get("symbols", []):
        if s["symbol"] == symbol:
            return s
    raise ValueError(f"Sembol bulunamadı: {symbol}")


def _round_step(value: float, step_size: str) -> float:
    """Binance'in stepSize/tickSize'ına (ondalık string, ör. '0.001') göre
    değeri AŞAĞI yuvarlar — yukarı yuvarlama borsanın izin verdiği miktarı/
    fiyatı aşıp emri reddettirebilir. `Decimal` kullanılır ki ondalık
    basamaklarda ikili (float) yuvarlama hatası oluşmasın."""
    step_decimal = Decimal(step_size)
    value_decimal = Decimal(str(value))
    steps = (value_decimal / step_decimal).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * step_decimal)


def round_quantity_to_lot_size(symbol_info: dict, quantity: float) -> float:
    lot_size_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
    return _round_step(quantity, lot_size_filter["stepSize"])


def round_price_to_tick_size(symbol_info: dict, price: float) -> float:
    price_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER")
    return _round_step(price, price_filter["tickSize"])


def set_futures_leverage(api_key: str, api_secret: str, symbol: str, leverage: int) -> dict:
    """POST /fapi/v1/leverage — sembolün kaldıracını ayarlar (1 ile sembole göre
    değişen bir üst sınır arasında)."""
    return _signed_post(
        BINANCE_FUTURES_BASE_URL,
        "/fapi/v1/leverage",
        api_key,
        api_secret,
        {"symbol": symbol, "leverage": leverage},
    )


def set_futures_margin_type(api_key: str, api_secret: str, symbol: str, margin_type: str = "ISOLATED") -> dict:
    """POST /fapi/v1/marginType — margin modunu (ISOLATED/CROSSED) ayarlar.
    Sembol zaten o moddaysa Binance -4046 hata kodunu döner; bu bir hata değil
    "zaten istenen durumda" anlamına geldiğinden burada yutulup normal bir
    sonuç gibi ele alınır."""
    try:
        return _signed_post(
            BINANCE_FUTURES_BASE_URL,
            "/fapi/v1/marginType",
            api_key,
            api_secret,
            {"symbol": symbol, "marginType": margin_type},
        )
    except BinanceAPIError as exc:
        if exc.code == -4046:
            return {"msg": "no need to change margin type"}
        raise


def place_futures_market_order(
    api_key: str, api_secret: str, symbol: str, side: str, quantity: float, reduce_only: bool = False
) -> dict:
    """POST /fapi/v1/order — MARKET emriyle pozisyon açar/kapatır (tek yönlü
    pozisyon modu varsayılır). `side`: 'BUY' (LONG aç / SHORT kapat) veya
    'SELL' (SHORT aç / LONG kapat). `quantity`, çağıran tarafından zaten
    round_quantity_to_lot_size ile yuvarlanmış olmalı."""
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity}
    if reduce_only:
        params["reduceOnly"] = "true"
    return _signed_post(BINANCE_FUTURES_BASE_URL, "/fapi/v1/order", api_key, api_secret, params)


def place_futures_stop_loss_order(api_key: str, api_secret: str, symbol: str, side: str, stop_price: float) -> dict:
    """POST /fapi/v1/order — STOP_MARKET, closePosition=true: fiyat stop_price'a
    değince o semboldeki TÜM açık pozisyonu piyasa fiyatından kapatır (miktar
    belirtilmez, borsa pozisyonun tamamını kapatır). `side`, kapanış yönüdür:
    LONG pozisyon için 'SELL', SHORT pozisyon için 'BUY'. `stop_price`,
    çağıran tarafından round_price_to_tick_size ile yuvarlanmış olmalı."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": "STOP_MARKET",
        "stopPrice": stop_price,
        "closePosition": "true",
    }
    return _signed_post(BINANCE_FUTURES_BASE_URL, "/fapi/v1/order", api_key, api_secret, params)


def place_futures_take_profit_order(
    api_key: str, api_secret: str, symbol: str, side: str, stop_price: float
) -> dict:
    """POST /fapi/v1/order — TAKE_PROFIT_MARKET, closePosition=true (bkz.
    place_futures_stop_loss_order — aynı mantık, ters yönde tetiklenir)."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": stop_price,
        "closePosition": "true",
    }
    return _signed_post(BINANCE_FUTURES_BASE_URL, "/fapi/v1/order", api_key, api_secret, params)


def cancel_futures_order(api_key: str, api_secret: str, symbol: str, order_id: int) -> dict:
    """DELETE /fapi/v1/order — açık bir emri iptal eder (ör. TP vurulup
    pozisyon kapandığında borsada asılı kalan SL emrini temizlemek için)."""
    return _signed_delete(
        BINANCE_FUTURES_BASE_URL,
        "/fapi/v1/order",
        api_key,
        api_secret,
        {"symbol": symbol, "orderId": order_id},
    )


def cancel_all_futures_open_orders(api_key: str, api_secret: str, symbol: str) -> dict:
    """DELETE /fapi/v1/allOpenOrders — sembolün tüm açık emirlerini (SL/TP
    dahil) tek seferde iptal eder."""
    return _signed_delete(BINANCE_FUTURES_BASE_URL, "/fapi/v1/allOpenOrders", api_key, api_secret, {"symbol": symbol})


def get_futures_open_orders(api_key: str, api_secret: str, symbol: str) -> list[dict]:
    """GET /fapi/v1/openOrders — sembolün açık (henüz gerçekleşmemiş/tetiklenmemiş)
    emirlerini döner."""
    result = _signed_get(BINANCE_FUTURES_BASE_URL, "/fapi/v1/openOrders", api_key, api_secret, {"symbol": symbol})
    return result if isinstance(result, list) else []


def get_futures_position_risk(api_key: str, api_secret: str, symbol: str) -> list[dict]:
    """GET /fapi/v2/positionRisk — sembolün açık pozisyon(lar)ını (miktar, giriş
    fiyatı, anlık kâr/zarar, kaldıraç, likidasyon fiyatı) döner. Tek yönlü
    pozisyon modunda tek bir kayıt döner; positionAmt=0 ise açık pozisyon yoktur."""
    result = _signed_get(BINANCE_FUTURES_BASE_URL, "/fapi/v2/positionRisk", api_key, api_secret, {"symbol": symbol})
    return result if isinstance(result, list) else []
