import random

import pytest

from app.backtest.engine import Candle
from app.grid_trading.screener import ScreenerCriteria, evaluate_symbol, run_screener


def _candles(highs: list[float], lows: list[float], closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i * 60_000, open=c, high=h, low=lo, close=c)
        for i, (h, lo, c) in enumerate(zip(highs, lows, closes))
    ]


def _flat_low_volatility_candles(n: int = 60, price: float = 100.0) -> list[Candle]:
    return _candles([price + 0.02] * n, [price - 0.02] * n, [price] * n)


def _choppy_high_volatility_candles(n: int = 60, base: float = 100.0, amplitude: float = 15.0) -> list[Candle]:
    # Her mumda yön değiştiren büyük sıçrama: geniş aralık (yüksek ATR) ama net
    # bir trend yönü yok (düşük ADX) -- bkz. tests/test_backtest_indicators.py
    # ADX testlerindeki tek yönlü artışın tam tersi.
    closes = [base]
    for i in range(1, n):
        closes.append(closes[-1] + (amplitude if i % 2 else -amplitude))
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return _candles(highs, lows, closes)


def _strong_trend_moderate_volatility_candles(n: int = 29, base: float = 100.0, step: float = 8.0) -> list[Candle]:
    # Tek yönlü sabit artış -> ADX 100'e oturur (bkz. test_adx_strong_uptrend_approaches_100);
    # step, ATR%'nin %2-%6 bandının İÇİNDE kalması için ayarlandı ki bu senaryo
    # SADECE trend kriterinden düşsün, volatiliteden değil.
    highs = [base + step * i + 0.3 for i in range(n)]
    lows = [base + step * i - 0.3 for i in range(n)]
    closes = [base + step * i for i in range(n)]
    return _candles(highs, lows, closes)


def _ranging_moderate_volatility_candles(n: int = 200, seed: int = 7) -> list[Candle]:
    # Sürüklenmesiz (driftsiz) rastgele yürüyüş: ne fiyat yatay kalır (ATR% ~%4.5,
    # bant içinde) ne de belirgin bir trend oluşur (ADX ~15, eşiğin altında) --
    # yani her iki kriteri de geçen 'ideal grid piyasası' senaryosu.
    rng = random.Random(seed)
    price = 100.0
    closes = [price]
    for _ in range(1, n):
        price += rng.uniform(-3.0, 3.0)
        closes.append(price)
    highs = [c + abs(rng.uniform(0.5, 1.5)) for c in closes]
    lows = [c - abs(rng.uniform(0.5, 1.5)) for c in closes]
    return _candles(highs, lows, closes)


def test_evaluate_symbol_passes_when_all_criteria_met():
    candles = _ranging_moderate_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, candles)

    assert result.passes is True
    assert result.failed_reasons == []
    assert result.atr_pct is not None
    assert result.adx_value is not None
    assert result.last_price == pytest.approx(candles[-1].close)


def test_evaluate_symbol_fails_on_low_spot_volume():
    candles = _ranging_moderate_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 10_000_000.0, 250_000_000.0, candles)

    assert result.passes is False
    assert "spot_volume" in result.failed_reasons
    assert "futures_volume" not in result.failed_reasons


def test_evaluate_symbol_fails_on_low_futures_volume():
    candles = _ranging_moderate_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 50_000_000.0, candles)

    assert result.passes is False
    assert "futures_volume" in result.failed_reasons
    assert "spot_volume" not in result.failed_reasons


def test_evaluate_symbol_fails_on_volatility_too_low():
    candles = _flat_low_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, candles)

    assert result.passes is False
    assert result.failed_reasons == ["volatility"]
    assert result.adx_value == pytest.approx(0.0)


def test_evaluate_symbol_fails_on_volatility_too_high():
    candles = _choppy_high_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, candles)

    assert result.passes is False
    assert result.failed_reasons == ["volatility"]
    assert result.atr_pct > ScreenerCriteria().atr_pct_max
    assert result.adx_value < ScreenerCriteria().adx_max


def test_evaluate_symbol_fails_on_strong_trend():
    candles = _strong_trend_moderate_volatility_candles()
    criteria = ScreenerCriteria()

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, candles, criteria)

    assert result.passes is False
    assert result.failed_reasons == ["trend"]
    assert criteria.atr_pct_min <= result.atr_pct <= criteria.atr_pct_max
    assert result.adx_value == pytest.approx(100.0)


def test_evaluate_symbol_volume_failure_does_not_claim_volatility_trend_checked():
    # Hacim zaten elediği ve run_screener bu durumda kline hiç çekmediği için
    # (candles=[]), volatilite/trend 'başarısız' değil 'değerlendirilmedi'
    # sayılmalı -- sadece hacim nedenleri raporlanır.
    result = evaluate_symbol("BTCUSDT", 1_000_000.0, 1_000_000.0, [])

    assert result.passes is False
    assert set(result.failed_reasons) == {"spot_volume", "futures_volume"}
    assert result.atr_pct is None
    assert result.adx_value is None


def test_evaluate_symbol_missing_candle_data_after_volume_pass_fails_volatility_and_trend():
    # Hacim geçti ama (ör. ağ hatasıyla) mum verisi hiç gelmedi -- bu durumda
    # sessizce 'geçti' sayılmamalı, veri eksikliği başarısızlık olarak sayılmalı.
    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, [])

    assert result.passes is False
    assert set(result.failed_reasons) == {"volatility", "trend"}


def test_evaluate_symbol_uses_custom_criteria():
    candles = _strong_trend_moderate_volatility_candles()
    lenient = ScreenerCriteria(adx_max=101.0)  # ADX teorik tavanı zaten 100 -> pratikte devre dışı bırakır

    result = evaluate_symbol("BTCUSDT", 60_000_000.0, 250_000_000.0, candles, lenient)

    assert result.passes is True


def test_run_screener_orchestrates_volume_prefilter_and_candle_fetch(monkeypatch):
    ranging = _ranging_moderate_volatility_candles()
    flat = _flat_low_volatility_candles()

    monkeypatch.setattr(
        "app.grid_trading.screener.get_futures_24h_tickers",
        lambda: [
            {"symbol": "AAAUSDT", "quoteVolume": "300000000"},  # hacim geçer
            {"symbol": "BBBUSDT", "quoteVolume": "300000000"},  # hacim geçer, ama volatilite düşük
            {"symbol": "CCCUSDT", "quoteVolume": "1000"},  # futures hacmi elenir
        ],
    )
    monkeypatch.setattr(
        "app.grid_trading.screener.get_spot_24h_tickers",
        lambda: [
            {"symbol": "AAAUSDT", "quoteVolume": "80000000"},
            {"symbol": "BBBUSDT", "quoteVolume": "80000000"},
            {"symbol": "CCCUSDT", "quoteVolume": "80000000"},
        ],
    )
    monkeypatch.setattr(
        "app.grid_trading.screener.get_futures_perpetual_symbols",
        lambda: ["AAAUSDT", "BBBUSDT", "CCCUSDT"],
    )

    def fake_fetch(symbols, interval, lookback_candles):
        assert set(symbols) == {"AAAUSDT", "BBBUSDT"}  # CCCUSDT hacimde elendiği için kline istenmemeli
        return {"AAAUSDT": ranging, "BBBUSDT": flat}

    monkeypatch.setattr("app.grid_trading.screener._fetch_candles_for_symbols", fake_fetch)

    results = run_screener()

    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["AAAUSDT"].passes is True
    assert by_symbol["BBBUSDT"].passes is False
    assert by_symbol["BBBUSDT"].failed_reasons == ["volatility"]
    assert by_symbol["CCCUSDT"].passes is False
    assert "futures_volume" in by_symbol["CCCUSDT"].failed_reasons
    assert by_symbol["CCCUSDT"].atr_pct is None  # kline hiç çekilmedi
