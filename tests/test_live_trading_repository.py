import uuid

import pytest

from app.live_trading.repository import (
    LiveTradeNotFoundError,
    list_live_trades,
    record_trade_closed,
    record_trade_failed,
    record_trade_opened,
)


def _open_trade(db, user, **overrides):
    params = {
        "user_id": user.id,
        "credential_id": None,
        "strategy_name": "Esnetilmiş 5D Scalp (EMA9/21/100 + ATR14)",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "mode": "auto",
        "side": "LONG",
        "margin_usd": 2.0,
        "leverage": 5,
        "sl_fee_mult": 10.0,
        "tp_fee_mult": 20.0,
        "entry_price": 60000.0,
        "stop_loss_price": 59400.0,
        "take_profit_price": 61200.0,
        "quantity": 0.001,
        "entry_order_id": 111,
        "sl_order_id": 222,
        "tp_order_id": 333,
    }
    params.update(overrides)
    return record_trade_opened(db, **params)


def test_record_trade_opened_persists_expected_fields(db, user):
    trade = _open_trade(db, user)

    assert trade.status == "OPEN"
    assert trade.side == "LONG"
    assert trade.symbol == "BTCUSDT"
    assert float(trade.entry_price) == pytest.approx(60000.0)
    assert trade.entry_order_id == "111"
    assert trade.opened_at is not None
    assert trade.closed_at is None


def test_record_trade_closed_updates_status_and_closed_at(db, user):
    trade = _open_trade(db, user)

    closed = record_trade_closed(db, trade.id, "TP")

    assert closed.status == "CLOSED_TP"
    assert closed.closed_at is not None


def test_record_trade_closed_raises_for_unknown_id(db, user):
    with pytest.raises(LiveTradeNotFoundError):
        record_trade_closed(db, uuid.uuid4(), "TP")


def test_record_trade_failed_sets_error_message(db, user):
    trade = _open_trade(db, user)

    failed = record_trade_failed(db, trade.id, "Bakiye yetersiz")

    assert failed.status == "FAILED"
    assert failed.error_message == "Bakiye yetersiz"
    assert failed.closed_at is not None


def test_list_live_trades_returns_only_this_users_trades_newest_first(db, user):
    from app.repository import register_user

    other_user = register_user(db, "other@example.com", "password123")

    first = _open_trade(db, user, symbol="BTCUSDT")
    second = _open_trade(db, user, symbol="ETHUSDT")
    _open_trade(db, other_user, symbol="BTCUSDT")

    trades = list_live_trades(db, user.id)

    assert [t.id for t in trades] == [second.id, first.id]
