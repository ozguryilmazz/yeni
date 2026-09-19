from unittest.mock import patch

import pytest

from app.binance_client import (
    BinanceAPIError,
    cancel_all_futures_open_orders,
    cancel_futures_order,
    get_futures_open_orders,
    get_futures_position_risk,
    get_futures_symbol_info,
    has_futures_trading_permission,
    place_futures_market_order,
    place_futures_stop_loss_order,
    place_futures_take_profit_order,
    round_price_to_tick_size,
    round_quantity_to_lot_size,
    set_futures_leverage,
    set_futures_margin_type,
)

SYMBOL_INFO = {
    "symbol": "BTCUSDT",
    "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "0"},
    ],
}


def test_get_futures_symbol_info_finds_symbol():
    exchange_info = {"symbols": [{"symbol": "ETHUSDT"}, SYMBOL_INFO]}
    with patch("app.binance_client._public_get", return_value=exchange_info):
        info = get_futures_symbol_info("BTCUSDT")

    assert info == SYMBOL_INFO


def test_get_futures_symbol_info_raises_when_not_found():
    with patch("app.binance_client._public_get", return_value={"symbols": []}):
        with pytest.raises(ValueError):
            get_futures_symbol_info("NOPEUSDT")


def test_round_quantity_to_lot_size_rounds_down():
    # 0.0019 -> stepSize 0.001 ile aşağı yuvarlanınca 0.001 kalmalı (0.002 değil).
    assert round_quantity_to_lot_size(SYMBOL_INFO, 0.0019) == pytest.approx(0.001)
    assert round_quantity_to_lot_size(SYMBOL_INFO, 0.0035) == pytest.approx(0.003)


def test_round_price_to_tick_size_rounds_down():
    assert round_price_to_tick_size(SYMBOL_INFO, 100.27) == pytest.approx(100.2)


def test_has_futures_trading_permission():
    assert has_futures_trading_permission({"enableFutures": True}) is True
    assert has_futures_trading_permission({"enableFutures": False}) is False
    assert has_futures_trading_permission({}) is False


def test_set_futures_leverage_posts_expected_params():
    with patch("app.binance_client._signed_post", return_value={"leverage": 5}) as mock_post:
        set_futures_leverage("key", "secret", "BTCUSDT", 5)

    args, _ = mock_post.call_args
    assert args[1] == "/fapi/v1/leverage"
    assert args[4] == {"symbol": "BTCUSDT", "leverage": 5}


def test_set_futures_margin_type_swallows_already_set_error():
    with patch("app.binance_client._signed_post", side_effect=BinanceAPIError("already isolated", -4046)):
        result = set_futures_margin_type("key", "secret", "BTCUSDT", "ISOLATED")

    assert result == {"msg": "no need to change margin type"}


def test_set_futures_margin_type_reraises_other_errors():
    with patch("app.binance_client._signed_post", side_effect=BinanceAPIError("some other error", -1000)):
        with pytest.raises(BinanceAPIError):
            set_futures_margin_type("key", "secret", "BTCUSDT", "ISOLATED")


def test_place_futures_market_order_sets_reduce_only_when_requested():
    with patch("app.binance_client._signed_post", return_value={"orderId": 1}) as mock_post:
        place_futures_market_order("key", "secret", "BTCUSDT", "SELL", 0.01, reduce_only=True)

    args, _ = mock_post.call_args
    assert args[4] == {"symbol": "BTCUSDT", "side": "SELL", "type": "MARKET", "quantity": 0.01, "reduceOnly": "true"}


def test_place_futures_market_order_without_reduce_only():
    with patch("app.binance_client._signed_post", return_value={"orderId": 1}) as mock_post:
        place_futures_market_order("key", "secret", "BTCUSDT", "BUY", 0.01)

    args, _ = mock_post.call_args
    assert "reduceOnly" not in args[4]


def test_place_futures_stop_loss_order_uses_close_position():
    with patch("app.binance_client._signed_post", return_value={"orderId": 2}) as mock_post:
        place_futures_stop_loss_order("key", "secret", "BTCUSDT", "SELL", 59000.0)

    args, _ = mock_post.call_args
    assert args[1] == "/fapi/v1/order"
    assert args[4] == {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "type": "STOP_MARKET",
        "stopPrice": 59000.0,
        "closePosition": "true",
    }


def test_place_futures_take_profit_order_uses_close_position():
    with patch("app.binance_client._signed_post", return_value={"orderId": 3}) as mock_post:
        place_futures_take_profit_order("key", "secret", "BTCUSDT", "SELL", 62000.0)

    args, _ = mock_post.call_args
    assert args[4] == {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": 62000.0,
        "closePosition": "true",
    }


def test_cancel_futures_order_sends_order_id():
    with patch("app.binance_client._signed_delete", return_value={"orderId": 4}) as mock_delete:
        cancel_futures_order("key", "secret", "BTCUSDT", 4)

    args, _ = mock_delete.call_args
    assert args[1] == "/fapi/v1/order"
    assert args[4] == {"symbol": "BTCUSDT", "orderId": 4}


def test_cancel_all_futures_open_orders_sends_symbol_only():
    with patch("app.binance_client._signed_delete", return_value={}) as mock_delete:
        cancel_all_futures_open_orders("key", "secret", "BTCUSDT")

    args, _ = mock_delete.call_args
    assert args[1] == "/fapi/v1/allOpenOrders"
    assert args[4] == {"symbol": "BTCUSDT"}


def test_get_futures_open_orders_returns_list():
    with patch("app.binance_client._signed_get", return_value=[{"orderId": 1}]):
        orders = get_futures_open_orders("key", "secret", "BTCUSDT")

    assert orders == [{"orderId": 1}]


def test_get_futures_open_orders_defaults_to_empty_list_on_unexpected_shape():
    with patch("app.binance_client._signed_get", return_value={}):
        orders = get_futures_open_orders("key", "secret", "BTCUSDT")

    assert orders == []


def test_get_futures_position_risk_returns_list():
    position = [{"symbol": "BTCUSDT", "positionAmt": "0.010", "entryPrice": "60000"}]
    with patch("app.binance_client._signed_get", return_value=position):
        result = get_futures_position_risk("key", "secret", "BTCUSDT")

    assert result == position
