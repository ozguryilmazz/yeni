import httpx

FUTURES_BASE_URL = "https://fapi.binance.com"


async def fetch_open_interest(client: httpx.AsyncClient, symbol: str) -> float:
    """GET /fapi/v1/openInterest — sembolün anlık toplam açık pozisyon (Open Interest)
    miktarı (coin cinsinden). API key gerekmez (public)."""
    response = await client.get("/fapi/v1/openInterest", params={"symbol": symbol})
    response.raise_for_status()
    return float(response.json()["openInterest"])


async def fetch_funding_rate(client: httpx.AsyncClient, symbol: str) -> float:
    """GET /fapi/v1/premiumIndex — sembolün bir sonraki fonlamada uygulanacak anlık
    tahmini Funding Rate değeri (ondalık, örn. 0.0001 = %0.01). API key gerekmez."""
    response = await client.get("/fapi/v1/premiumIndex", params={"symbol": symbol})
    response.raise_for_status()
    return float(response.json()["lastFundingRate"])


async def fetch_recent_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[list]:
    """GET /fapi/v1/klines — ham mum verisi; hacim baseline'ı (ortalama) ve o periyodun
    açılış/kapanış fiyatını hesaplamak için kullanılır. API key gerekmez."""
    response = await client.get(
        "/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": limit}
    )
    response.raise_for_status()
    return response.json()
