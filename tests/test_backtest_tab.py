from unittest.mock import patch

from PySide6.QtGui import QGuiApplication

from app.backtest.engine import BacktestResult, Trade
from app.backtest.service import BacktestComparison
from app.ui.backtest_tab import BacktestTab


def _make_trade(side: str, exit_reason: str, net_pnl_usd: float, balance_after_usd: float) -> Trade:
    return Trade(
        side=side,
        entry_time_ms=0,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        exit_time_ms=300_000,
        exit_price=104.0,
        exit_reason=exit_reason,
        quantity=0.1,
        gross_pnl_usd=net_pnl_usd,
        fees_usd=0.0,
        net_pnl_usd=net_pnl_usd,
        balance_after_usd=balance_after_usd,
    )


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


def test_successful_run_renders_both_summaries_and_defaults_to_normal_trade_table(qapp):
    comparison = BacktestComparison(
        normal=BacktestResult(
            trades=[_make_trade("LONG", "TP", 0.39, 100.39)],
            starting_balance_usd=100.0,
            ending_balance_usd=100.39,
            stopped_early=False,
        ),
        reversed=BacktestResult(
            trades=[
                _make_trade("SHORT", "SL", -0.21, 99.79),
                _make_trade("SHORT", "TP", 0.5, 100.29),
            ],
            starting_balance_usd=100.0,
            ending_balance_usd=100.29,
            stopped_early=False,
        ),
    )

    with patch("app.workers.run_backtest_comparison", return_value=comparison):
        tab = BacktestTab()
        tab._handle_run()
        tab._worker.wait()
        qapp.processEvents()

    assert tab.run_button.isEnabled()
    assert "1" in tab.normal_summary_label.text()  # Toplam İşlem: 1
    assert "2" in tab.reversed_summary_label.text()  # Toplam İşlem: 2

    # Varsayılan olarak "Normal Yön" seçili -> tabloda tek satır (normal.trades) olmalı.
    assert tab.trade_table.rowCount() == 1
    assert tab.trade_table.item(0, 0).text() == "LONG"

    # Seçimi "Ters Yön"e çevirince tablo reversed.trades'i göstermeli.
    reversed_index = tab.result_selector.findData("reversed")
    tab.result_selector.setCurrentIndex(reversed_index)

    assert tab.trade_table.rowCount() == 2
    assert tab.trade_table.item(0, 0).text() == "SHORT"


def test_run_error_shows_warning_and_reenables_button(qapp):
    with patch("app.workers.run_backtest_comparison", side_effect=RuntimeError("boom")):
        with patch("app.ui.backtest_tab.QMessageBox.warning") as mock_warning:
            tab = BacktestTab()
            tab._handle_run()
            tab._worker.wait()
            qapp.processEvents()

    mock_warning.assert_called_once()
    assert tab.run_button.isEnabled()
