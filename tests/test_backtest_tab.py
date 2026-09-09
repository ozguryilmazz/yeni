from unittest.mock import patch

from PySide6.QtGui import QGuiApplication

from app.backtest.engine import BacktestResult, Trade
from app.ui.backtest_tab import BacktestTab


def test_paste_button_fills_symbol_input_from_clipboard(qapp):
    QGuiApplication.clipboard().setText("ethusdt")
    tab = BacktestTab()

    tab._handle_paste()

    assert tab.symbol_input.text() == "ETHUSDT"


def test_run_warns_and_does_not_start_worker_when_symbol_is_empty(qapp):
    tab = BacktestTab()
    tab.symbol_input.setText("   ")

    with patch("app.ui.backtest_tab.QMessageBox.warning") as mock_warning:
        tab._handle_run()

    mock_warning.assert_called_once()
    assert tab._worker is None


def test_run_warns_and_does_not_start_worker_when_start_is_not_before_end(qapp):
    tab = BacktestTab()
    tab.start_input.setDateTime(tab.end_input.dateTime())

    with patch("app.ui.backtest_tab.QMessageBox.warning") as mock_warning:
        tab._handle_run()

    mock_warning.assert_called_once()
    assert tab._worker is None


def test_successful_run_renders_summary_and_trade_table(qapp):
    trade = Trade(
        side="LONG",
        entry_time_ms=0,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        exit_time_ms=300_000,
        exit_price=104.0,
        exit_reason="TP",
        quantity=0.1,
        gross_pnl_usd=0.4,
        fees_usd=0.0102,
        net_pnl_usd=0.3898,
        balance_after_usd=100.3898,
    )
    result = BacktestResult(
        trades=[trade], starting_balance_usd=100.0, ending_balance_usd=100.3898, stopped_early=False
    )

    with patch("app.workers.run_backtest_for_symbol", return_value=result):
        tab = BacktestTab()
        tab._handle_run()
        tab._worker.wait()
        qapp.processEvents()

    assert tab.run_button.isEnabled()
    assert tab.trade_table.rowCount() == 1
    assert tab.trade_table.item(0, 0).text() == "LONG"
    assert tab.trade_table.item(0, 7).text() == "TP"
    assert "1" in tab.summary_label.text()  # Toplam İşlem: 1


def test_run_error_shows_warning_and_reenables_button(qapp):
    with patch("app.workers.run_backtest_for_symbol", side_effect=RuntimeError("boom")):
        with patch("app.ui.backtest_tab.QMessageBox.warning") as mock_warning:
            tab = BacktestTab()
            tab._handle_run()
            tab._worker.wait()
            qapp.processEvents()

    mock_warning.assert_called_once()
    assert tab.run_button.isEnabled()
