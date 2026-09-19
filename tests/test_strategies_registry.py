import pytest

from app.strategies.registry import DEFAULT_STRATEGY_NAME, STRATEGIES, get_strategy


def test_default_strategy_is_registered():
    assert DEFAULT_STRATEGY_NAME in STRATEGIES


def test_get_strategy_returns_registered_strategy_by_name():
    strategy = get_strategy(DEFAULT_STRATEGY_NAME)

    assert strategy.name == DEFAULT_STRATEGY_NAME
    assert callable(strategy.compute_signals)
    assert strategy.warmup_candles > 0


def test_get_strategy_raises_for_unknown_name():
    with pytest.raises(ValueError):
        get_strategy("olmayan strateji")
