from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from app.ui.live_trading_tab import LiveTradingTab
from tests.conftest import connect_credential as connect_credential_helper


def test_credential_combo_populated_from_connected_accounts(qapp, db, user):
    connect_credential_helper(db, user)

    tab = LiveTradingTab(user.id)

    assert tab.credential_combo.count() == 1
    assert tab._current_credential_id is not None


def test_start_warns_when_no_credential_connected(qapp, db, user):
    tab = LiveTradingTab(user.id)

    with patch("app.ui.live_trading_tab.QMessageBox.warning") as mock_warning:
        tab._handle_start("auto")

    mock_warning.assert_called_once()
    assert tab._thread is None


def test_start_warns_when_symbol_empty(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab.symbol_input.setText("   ")

    with patch("app.ui.live_trading_tab.QMessageBox.warning") as mock_warning:
        tab._handle_start("auto")

    mock_warning.assert_called_once()
    assert tab._thread is None


def test_start_does_nothing_when_confirmation_dialog_declined(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)

    with (
        patch("app.ui.live_trading_tab.QMessageBox.warning", return_value=QMessageBox.StandardButton.No),
        patch("app.ui.live_trading_tab.LiveTradingThread") as mock_thread_cls,
    ):
        tab._handle_start("auto")

    mock_thread_cls.assert_not_called()
    assert tab._thread is None


def test_start_creates_thread_with_expected_params_when_confirmed(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab.symbol_input.setText("ethusdt")
    tab.margin_input.setValue(3.0)
    tab.leverage_input.setValue(7)

    mock_thread = MagicMock()
    with (
        patch("app.ui.live_trading_tab.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes),
        patch("app.ui.live_trading_tab.LiveTradingThread", return_value=mock_thread) as mock_thread_cls,
    ):
        tab._handle_start("confirm")

    mock_thread_cls.assert_called_once()
    args = mock_thread_cls.call_args.args
    assert args[2] == "ETHUSDT"  # symbol büyütülmüş olmalı
    risk = args[5]
    assert risk.margin_usd == 3.0
    assert risk.leverage == 7
    assert args[6] == "confirm"
    mock_thread.start.assert_called_once()
    assert tab._thread is mock_thread
    assert tab.stop_button.isEnabled()
    assert not tab.start_auto_button.isEnabled()


def test_start_twice_warns_bot_already_running(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab._thread = MagicMock()

    with patch("app.ui.live_trading_tab.QMessageBox.information") as mock_info:
        tab._handle_start("auto")

    mock_info.assert_called_once()


def test_order_placed_writes_trade_and_refreshes_history(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab._active_symbol = "BTCUSDT"

    trade = {
        "side": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 59400.0,
        "take_profit": 61200.0,
        "quantity": 0.001,
        "entry_order_id": 1,
        "sl_order_id": 2,
        "tp_order_id": 3,
    }
    tab._on_order_placed(trade)

    assert tab._current_trade_db_id is not None
    assert tab.history_table.rowCount() == 1
    assert tab.history_table.item(0, 3).text() == "LONG"


def test_position_closed_updates_status_to_closed(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab._active_symbol = "BTCUSDT"
    tab._on_order_placed(
        {
            "side": "SHORT",
            "entry_price": 100.0,
            "stop_loss": 101.0,
            "take_profit": 98.0,
            "quantity": 0.1,
            "entry_order_id": 1,
            "sl_order_id": 2,
            "tp_order_id": 3,
        }
    )

    tab._on_position_closed("TP")

    assert tab._current_trade_db_id is None
    assert tab.history_table.item(0, 8).text() == "Kapandı (TP)"


def test_stop_disables_further_stop_and_reenables_start(qapp, db, user):
    connect_credential_helper(db, user)
    tab = LiveTradingTab(user.id)
    tab._thread = MagicMock()
    tab._set_running_ui(True)

    tab._handle_stop()

    assert tab._thread is None
    assert tab.start_auto_button.isEnabled()
    assert not tab.stop_button.isEnabled()
