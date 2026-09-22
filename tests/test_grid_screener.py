import random

import pytest

from app.backtest.engine import Candle
from app.grid_trading.screener import ScreenerCriteria, evaluate_symbol, run_screener


def _candles(highs: list[float], lows: list[float], closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i * 60_000, open=c, high=h, low=lo, close=c)
        for i, (h, lo, c) in enumerate(zip(highs, lows, closes))
    ]


def _random_walk_candles(n: int, seed: int, amplitude: float, drift: float = 0.0) -> list[Candle]:
    # ADX/RSI/%B (Bollinger içindeki konum) ÖLÇEKTEN BAĞIMSIZDIR -- aynı seed
    # farklı amplitude'lerle bu üçünü DEĞİŞTİRMEDEN sadece ATR%'yi ve bant
    # genişliğini ölçekler. Bu yüzden aynı seed'i farklı amplitude'lerle
    # kullanmak volatiliteyi diğer kriterlerden bağımsız izole etmenin
    # güvenilir bir yolu (bkz. _low_volatility_candles/_high_volatility_candles).
    rng = random.Random(seed)
    price = 100.0
    closes = [price]
    for _ in range(1, n):
        price += rng.uniform(-amplitude, amplitude) + drift
        closes.append(price)
    highs = [c + abs(rng.uniform(0.5 * amplitude / 3, 1.5 * amplitude / 3)) for c in closes]
    lows = [c - abs(rng.uniform(0.5 * amplitude / 3, 1.5 * amplitude / 3)) for c in closes]
    return _candles(highs, lows, closes)


def _flat_candles(n: int = 60, price: float = 100.0) -> list[Candle]:
    return _candles([price + 0.02] * n, [price - 0.02] * n, [price] * n)


def _ideal_grid_candles() -> list[Candle]:
    # Doğrulanmış: ATR%=%2.74, ADX=8.48, RSI=49.78, Bollinger %B=0.469,
    # bant genişliği=%8.57 -- dördü de rahat marjinle geçen 'ideal grid
    # piyasası' senaryosu.
    return _random_walk_candles(200, seed=417, amplitude=2.0)


def _low_volatility_candles() -> list[Candle]:
    # _ideal_grid_candles ile AYNI desen, SADECE genliği küçültülmüş --
    # ADX/RSI/%B değişmez (ölçekten bağımsız), ATR% ise ~%0.16'ya düşüp
    # SADECE volatilite kriterinin ALT sınırından eler.
    return _random_walk_candles(200, seed=0, amplitude=0.2)


def _high_volatility_candles() -> list[Candle]:
    # _ideal_grid_candles ile AYNI seed (417), SADECE genliği büyütülmüş --
    # ADX/RSI/%B yine değişmez, ATR% ~%9'a çıkıp SADECE volatilite
    # kriterinin ÜST sınırından eler.
    return _random_walk_candles(200, seed=417, amplitude=4.0)


def _rsi_out_of_range_candles() -> list[Candle]:
    # Hafif ama tutarlı yukarı drift: ADX'i (~10.4) eşiğin altında tutacak
    # kadar yumuşak, ama RSI'ı (~66.2) üst sınırın dışına itecek kadar
    # tutarlı -- ADX(14) uzun vadeli/yumuşatılmış, RSI(14) son barlara daha
    # duyarlı olduğu için ayrışabiliyorlar.
    return _random_walk_candles(120, seed=248, amplitude=2.0, drift=0.2)


def _bollinger_confirmation_fails_candles() -> list[Candle]:
    # ATR%'yi (~%3.0) aralıkta tutan ama son kapanışı alt bandın da altına
    # iten (%B=-0.037) VE bandı sıkışmamış (genişlik ~%15.1) bırakan bir
    # seri.
    return _random_walk_candles(120, seed=744, amplitude=2.5)


def _strong_trend_candles(n: int = 29, base: float = 100.0, step: float = 8.0) -> list[Candle]:
    # Tek yönlü sabit artış -> ADX 100'e oturur, RSI 100'e oturur (hiç kayıp
    # yok), fiyat üst bandın dışına taşar; step, ATR%'nin %1.5-%4.5 bandının
    # İÇİNDE kalması için ayarlandı ki bu senaryo volatiliteden değil
    # SADECE trend/RSI/Bollinger'dan düşsün.
    highs = [base + step * i + 0.3 for i in range(n)]
    lows = [base + step * i - 0.3 for i in range(n)]
    closes = [base + step * i for i in range(n)]
    return _candles(highs, lows, closes)


def test_evaluate_symbol_passes_when_all_criteria_met():
    candles = _ideal_grid_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, candles, candles)

    assert result.passes is True
    assert result.failed_reasons == []
    assert result.atr_pct is not None
    assert result.adx_value is not None
    assert result.rsi_value is not None
    assert result.bollinger_percent_b is not None
    assert result.last_price == pytest.approx(candles[-1].close)


def test_evaluate_symbol_fails_on_low_futures_volume():
    candles = _ideal_grid_candles()

    result = evaluate_symbol("BTCUSDT", 10_000_000.0, candles, candles)

    assert result.passes is False
    assert result.failed_reasons == ["futures_volume"]


def test_evaluate_symbol_fails_on_volatility_too_low():
    candles = _low_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, candles, candles)

    assert result.passes is False
    assert result.failed_reasons == ["volatility"]
    assert result.atr_pct < ScreenerCriteria().atr_pct_min


def test_evaluate_symbol_fails_on_volatility_too_high():
    candles = _high_volatility_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, candles, candles)

    assert result.passes is False
    assert result.failed_reasons == ["volatility"]
    assert result.atr_pct > ScreenerCriteria().atr_pct_max


def test_evaluate_symbol_fails_on_rsi_out_of_range():
    # Günlük seri ('ideal') temiz, 4h seri bozuk -- SADECE rsi elemeli; ADX'in
    # aynı (bozuk) 4h seriden geçtiğini de doğrular.
    daily = _ideal_grid_candles()
    intraday = _rsi_out_of_range_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, daily, intraday)

    assert result.passes is False
    assert result.failed_reasons == ["rsi"]
    assert result.rsi_value > ScreenerCriteria().rsi_max
    assert result.adx_value < ScreenerCriteria().adx_max


def test_evaluate_symbol_fails_on_bollinger_confirmation():
    # Günlük seri bandın dışına taşmış (ve sıkışmamış), 4h seri ('ideal')
    # temiz -- SADECE bollinger elemeli; ATR%'nin aralıkta kaldığını da
    # doğrular.
    daily = _bollinger_confirmation_fails_candles()
    intraday = _ideal_grid_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, daily, intraday)

    assert result.passes is False
    assert result.failed_reasons == ["bollinger"]
    criteria = ScreenerCriteria()
    assert criteria.atr_pct_min <= result.atr_pct <= criteria.atr_pct_max
    assert result.bollinger_percent_b < criteria.bollinger_percent_b_min
    assert result.bollinger_bandwidth > criteria.bollinger_bandwidth_squeeze_max


def test_evaluate_symbol_fails_on_strong_trend():
    candles = _strong_trend_candles()
    criteria = ScreenerCriteria()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, candles, candles, criteria)

    assert result.passes is False
    # Güçlü, tek yönlü bir trend sadece ADX'i değil, RSI'ı (aşırı alım) ve
    # Bollinger'ı (fiyat üst bandın dışında) da tetikler -- bu üç kriter
    # kasıtlı olarak birbirini doğrulayan/örtüşen sinyallerdir.
    assert set(result.failed_reasons) == {"trend", "rsi", "bollinger"}
    assert criteria.atr_pct_min <= result.atr_pct <= criteria.atr_pct_max
    assert result.adx_value == pytest.approx(100.0)
    assert result.rsi_value == pytest.approx(100.0)


def test_evaluate_symbol_atr_and_adx_are_computed_from_independent_series():
    # ATR/Bollinger (günlük kural) düz bir seriden, ADX/RSI (4h varsayılan)
    # ise güçlü trendli AYRI bir seriden gelsin -- ikisi karıştırılmamalı,
    # her biri KENDİ serisinden değerlendirilmeli.
    flat = _flat_candles()
    trending = _strong_trend_candles()

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, flat, trending)

    assert result.adx_value == pytest.approx(100.0)  # trending serisinden
    assert result.atr_pct < ScreenerCriteria().atr_pct_min  # flat serisinden, çok düşük
    # Sabit (değişmeyen) kapanışlı flat seri için bant genişliği tam sıfırdır
    # -- %B/bant genişliği tanımsız (None) kalır ve 'bollinger' de düşer.
    assert set(result.failed_reasons) == {"volatility", "bollinger", "trend", "rsi"}


def test_evaluate_symbol_volume_failure_does_not_claim_other_criteria_checked():
    # Hacim zaten elediği ve run_screener bu durumda kline hiç çekmediği için
    # (candles=[]), diğer kriterler 'başarısız' değil 'değerlendirilmedi'
    # sayılmalı -- sadece hacim nedeni raporlanır.
    result = evaluate_symbol("BTCUSDT", 1_000_000.0, [], [])

    assert result.passes is False
    assert result.failed_reasons == ["futures_volume"]
    assert result.atr_pct is None
    assert result.adx_value is None
    assert result.rsi_value is None
    assert result.bollinger_percent_b is None


def test_evaluate_symbol_missing_candle_data_after_volume_pass_fails_all_indicator_checks():
    # Hacim geçti ama (ör. ağ hatasıyla) mum verisi hiç gelmedi -- bu durumda
    # sessizce 'geçti' sayılmamalı, veri eksikliği TÜM indikatör
    # kriterlerinde başarısızlık olarak sayılmalı.
    result = evaluate_symbol("BTCUSDT", 250_000_000.0, [], [])

    assert result.passes is False
    assert set(result.failed_reasons) == {"volatility", "bollinger", "trend", "rsi"}


def test_evaluate_symbol_uses_custom_criteria():
    daily = _ideal_grid_candles()
    intraday = _rsi_out_of_range_candles()
    lenient = ScreenerCriteria(rsi_min=0.0, rsi_max=100.0)  # RSI kriterini fiilen devre dışı bırakır

    result = evaluate_symbol("BTCUSDT", 250_000_000.0, daily, intraday, lenient)

    assert result.passes is True


def test_run_screener_orchestrates_volume_prefilter_and_candle_fetch(monkeypatch):
    ideal = _ideal_grid_candles()
    low_vol = _low_volatility_candles()

    monkeypatch.setattr(
        "app.grid_trading.screener.get_futures_24h_tickers",
        lambda: [
            {"symbol": "AAAUSDT", "quoteVolume": "50000000"},  # hacim geçer (>=30M)
            {"symbol": "BBBUSDT", "quoteVolume": "50000000"},  # hacim geçer, ama volatilite düşük
            {"symbol": "CCCUSDT", "quoteVolume": "1000"},  # futures hacmi elenir
        ],
    )
    monkeypatch.setattr(
        "app.grid_trading.screener.get_futures_perpetual_symbols",
        lambda: ["AAAUSDT", "BBBUSDT", "CCCUSDT"],
    )

    fetch_calls = []

    def fake_fetch(symbols, interval, lookback_candles):
        assert set(symbols) == {"AAAUSDT", "BBBUSDT"}  # CCCUSDT hacimde elendiği için kline istenmemeli
        fetch_calls.append(interval)
        return {"AAAUSDT": ideal, "BBBUSDT": low_vol}

    monkeypatch.setattr("app.grid_trading.screener._fetch_candles_for_symbols", fake_fetch)

    results = run_screener()

    # varsayılanlar farklı (atr='1d', adx='4h') -> İKİ AYRI çekim yapılmalı, sadece bir kez değil.
    assert sorted(fetch_calls) == ["1d", "4h"]

    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["AAAUSDT"].passes is True
    assert by_symbol["BBBUSDT"].passes is False
    assert by_symbol["BBBUSDT"].failed_reasons == ["volatility"]
    assert by_symbol["CCCUSDT"].passes is False
    assert "futures_volume" in by_symbol["CCCUSDT"].failed_reasons
    assert by_symbol["CCCUSDT"].atr_pct is None  # kline hiç çekilmedi


def test_run_screener_reuses_single_fetch_when_atr_and_adx_intervals_match(monkeypatch):
    ideal = _ideal_grid_candles()

    monkeypatch.setattr(
        "app.grid_trading.screener.get_futures_24h_tickers",
        lambda: [{"symbol": "AAAUSDT", "quoteVolume": "50000000"}],
    )
    monkeypatch.setattr("app.grid_trading.screener.get_futures_perpetual_symbols", lambda: ["AAAUSDT"])

    call_count = 0

    def fake_fetch(symbols, interval, lookback_candles):
        nonlocal call_count
        call_count += 1
        return {"AAAUSDT": ideal}

    monkeypatch.setattr("app.grid_trading.screener._fetch_candles_for_symbols", fake_fetch)

    run_screener(adx_interval="1d", atr_interval="1d")

    assert call_count == 1  # aynı zaman dilimiyse veri tekrar çekilmemeli
