from app.strategies import liquidity_sweep_1m, scalp_5d
from app.strategies.base import Strategy

# Yeni bir sinyal yöntemi eklendiğinde, o modülün STRATEGY nesnesi buraya
# eklenir — Backtest ve Canlı İşlem sekmeleri bu listeden isimle seçim yapar.
_ALL_STRATEGIES: list[Strategy] = [
    scalp_5d.STRATEGY,
    liquidity_sweep_1m.STRATEGY,
]

STRATEGIES: dict[str, Strategy] = {strategy.name: strategy for strategy in _ALL_STRATEGIES}
DEFAULT_STRATEGY_NAME: str = scalp_5d.STRATEGY.name


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Bilinmeyen strateji: {name}") from None
