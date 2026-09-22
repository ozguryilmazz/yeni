from unittest.mock import patch

import pytest
from PySide6.QtGui import QGuiApplication

from app.backtest.engine import Candle
from app.grid_trading.grid import GridBacktestResult, GridFill, GridLiquidation, GridTrade
from app.grid_trading.range_methods import GridRange
from app.grid_trading.screener import CandidateResult
from app.grid_trading.service import BacktestPreview, RangePreview
from app.ui.grid_tab import GridTab


def _candidate(symbol: str, passes: bool, **overrides) -> CandidateResult:
    defaults = dict(
        symbol=symbol,
        passes=passes,
        spot_volume_usd=60_000_000.0,
        futures_volume_usd=250_000_000.0,
        atr_pct=0.04,
        adx_value=15.0,
        last_price=100.0,
        failed_reasons=[] if passes else ["volatility"],
    )
    defaults.update(overrides)
    return CandidateResult(**defaults)


def _grid_backtest_result(
    trades: list[GridTrade] | None = None, liquidation: GridLiquidation | None = None
) -> GridBacktestResult:
    trades = trades or []
    total_pnl = -400.0 if liquidation else sum(t.net_pnl_usd for t in trades) - 1.5
    return GridBacktestResult(
        grid_levels=[90.0, 95.0, 100.0, 105.0, 110.0],
        trades=trades,
        fills=[GridFill(side="BUY", time_ms=0, price=90.0, quantity=1.0, fee_rate=0.0002)],
        realized_pnl_usd=sum(t.net_pnl_usd for t in trades),
        unrealized_pnl_usd=0.0 if liquidation else -1.5,
        total_pnl_usd=total_pnl,
        fees_usd=0.05,
        capital_usd=400.0,
        leverage=3.0,
        fee_rate=0.0005,
        maintenance_margin_rate=0.005,
        qty_per_grid=1.0,
        final_inventory_qty=0.0 if liquidation else 1.0,
        final_inventory_value_usd=0.0 if liquidation else 90.0,
        start_price=100.0,
        end_price=90.0,
        min_price_seen=88.0,
        max_price_seen=100.0,
        breached_lower=True,
        breached_upper=False,
        open_buy_levels=[],
        open_sell_levels=[] if liquidation else [95.0],
        liquidated=liquidation is not None,
        liquidation=liquidation,
    )


def _backtest_candles(n: int = 5) -> list[Candle]:
    return [Candle(open_time_ms=i * 3_600_000, open=95.0, high=101.0, low=89.0, close=95.0) for i in range(n)]


# ---- Tarama ------------------------------------------------------------


def test_scan_button_disables_while_running_and_populates_table(qapp):
    results = [_candidate("AAAUSDT", True), _candidate("BBBUSDT", False)]

    with patch("app.workers.run_screener", return_value=results):
        tab = GridTab()
        tab._handle_scan()
        tab._screener_worker.wait()
        qapp.processEvents()

    assert tab.scan_button.isEnabled()
    assert "2 sembol tarandı" in tab.screener_status_label.text()
    # varsayılan olarak "sadece uygun" işaretli -> sadece AAAUSDT görünür
    assert tab.screener_table.rowCount() == 1
    assert tab.screener_table.item(0, 0).text() == "AAAUSDT"

    tab.only_eligible_checkbox.setChecked(False)
    assert tab.screener_table.rowCount() == 2


def test_scan_error_shows_warning_and_reenables_button(qapp):
    with patch("app.workers.run_screener", side_effect=RuntimeError("boom")):
        with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
            tab = GridTab()
            tab._handle_scan()
            tab._screener_worker.wait()
            qapp.processEvents()

    mock_warning.assert_called_once()
    assert tab.scan_button.isEnabled()


def test_double_clicking_screener_row_fills_symbol_input(qapp):
    results = [_candidate("ETHUSDT", True)]
    with patch("app.workers.run_screener", return_value=results):
        tab = GridTab()
        tab._handle_scan()
        tab._screener_worker.wait()
        qapp.processEvents()

    tab._handle_screener_row_selected(0, 0)

    assert tab.symbol_input.text() == "ETHUSDT"


# ---- Aralık Hesaplama ----------------------------------------------------


def test_compute_range_warns_when_symbol_is_empty(qapp):
    tab = GridTab()
    tab.symbol_input.setText("   ")

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_compute_range()

    mock_warning.assert_called_once()
    assert tab._range_worker is None


def test_paste_button_fills_symbol_input_from_clipboard(qapp):
    QGuiApplication.clipboard().setText("ethusdt")
    tab = GridTab()

    tab._handle_paste()

    assert tab.symbol_input.text() == "ETHUSDT"


def test_method_combo_toggles_param_row_visibility(qapp):
    tab = GridTab()

    support_index = tab.method_combo.findData("support_resistance")
    tab.method_combo.setCurrentIndex(support_index)
    assert tab.min_touches_input.isVisibleTo(tab)
    assert not tab.bollinger_period_input.isVisibleTo(tab)
    assert not tab.atr_k_input.isVisibleTo(tab)

    atr_index = tab.method_combo.findData("atr")
    tab.method_combo.setCurrentIndex(atr_index)
    assert tab.atr_k_input.isVisibleTo(tab)
    assert not tab.min_touches_input.isVisibleTo(tab)


def test_successful_range_computation_fills_bounds_and_passes_method_kwargs(qapp):
    grid_range = GridRange(method="atr", lower_price=85.0, upper_price=115.0, details={"k": 2.5, "period": 10})
    candles = [Candle(open_time_ms=i * 3_600_000, open=100.0, high=101.0, low=99.0, close=100.0) for i in range(5)]
    preview = RangePreview(grid_range=grid_range, candles=candles)

    with patch("app.workers.compute_range_for_symbol", return_value=preview) as mock_compute:
        tab = GridTab()
        atr_index = tab.method_combo.findData("atr")
        tab.method_combo.setCurrentIndex(atr_index)
        tab.atr_k_input.setValue(2.5)
        tab.atr_period_input.setValue(10)

        tab._handle_compute_range()
        tab._range_worker.wait()
        qapp.processEvents()

    assert tab.lower_price_input.value() == 85.0
    assert tab.upper_price_input.value() == 115.0
    assert "85" in tab.range_result_label.text()
    assert mock_compute.call_args.args[1] == "atr"
    assert mock_compute.call_args.kwargs == {"period": 10, "k": 2.5}

    # Grafik: mum serisi + ara grid çizgileri (varsayılan grid sayısı - 1) +
    # alt/üst sınır çizgileri (2) çizilmiş olmalı.
    expected_series_count = 1 + (tab.grid_count_input.value() - 1) + 2
    assert len(tab.range_chart.series()) == expected_series_count


def test_range_chart_is_cleared_when_computation_returns_no_candles(qapp):
    grid_range = GridRange(method="atr", lower_price=85.0, upper_price=115.0, details={})
    preview = RangePreview(grid_range=grid_range, candles=[])

    with patch("app.workers.compute_range_for_symbol", return_value=preview):
        tab = GridTab()
        tab._handle_compute_range()
        tab._range_worker.wait()
        qapp.processEvents()

    assert tab.range_chart.series() == []


def test_range_computation_error_shows_warning(qapp):
    with patch("app.workers.compute_range_for_symbol", side_effect=ValueError("veri yok")):
        with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
            tab = GridTab()
            tab._handle_compute_range()
            tab._range_worker.wait()
            qapp.processEvents()

    mock_warning.assert_called_once()


# ---- Grid Backtest ---------------------------------------------------------


def test_run_backtest_warns_when_symbol_is_empty(qapp):
    tab = GridTab()
    tab.symbol_input.setText("")

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_run_backtest()

    mock_warning.assert_called_once()
    assert tab._backtest_worker is None


def test_run_backtest_warns_when_lower_bound_is_not_below_upper(qapp):
    tab = GridTab()
    tab.lower_price_input.setValue(110.0)
    tab.upper_price_input.setValue(100.0)

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_run_backtest()

    mock_warning.assert_called_once()
    assert tab._backtest_worker is None


def test_run_backtest_warns_when_start_is_not_before_end(qapp):
    tab = GridTab()
    tab.start_input.setDateTime(tab.end_input.dateTime())

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_run_backtest()

    mock_warning.assert_called_once()
    assert tab._backtest_worker is None


def test_successful_backtest_renders_summary_trade_table_and_chart(qapp):
    trade = GridTrade(
        buy_price=90.0,
        sell_price=95.0,
        quantity=1.0,
        buy_time_ms=0,
        sell_time_ms=60_000,
        gross_pnl_usd=5.0,
        fees_usd=0.037,
        net_pnl_usd=4.963,
    )
    result = _grid_backtest_result(trades=[trade])
    preview = BacktestPreview(result=result, candles=_backtest_candles())

    with patch("app.workers.run_grid_backtest_for_symbol", return_value=preview) as mock_run:
        tab = GridTab()
        tab.leverage_input.setValue(7)
        tab.fee_rate_input.setValue(0.04)
        tab.maintenance_margin_input.setValue(0.6)
        tab._handle_run_backtest()
        tab._backtest_worker.wait()
        qapp.processEvents()

    assert mock_run.call_args.kwargs["leverage"] == 7
    assert mock_run.call_args.kwargs["fee_rate"] == pytest.approx(0.0004)  # %0.04 -> oran
    assert mock_run.call_args.kwargs["maintenance_margin_rate"] == pytest.approx(0.006)  # %0.6 -> oran

    assert tab.run_backtest_button.isEnabled()
    assert "1" in tab.backtest_summary_label.text()  # Tamamlanan İşlem: 1
    assert "ALT sınırın altına indi" in tab.backtest_summary_label.text()
    assert "ÜST sınırın üstüne çıktı" not in tab.backtest_summary_label.text()
    assert "LİKİDE OLDU" not in tab.backtest_summary_label.text()
    assert tab.grid_trade_table.rowCount() == 1
    assert tab.grid_trade_table.item(0, 1).text() == "90.000000"

    # Grafik: mum + 3 ara grid seviyesi + alt/üst sınır -- likidasyon YOK, 3. bir
    # referans çizgisi (likidasyon) eklenmemeli.
    assert len(tab.backtest_chart.series()) == 1 + 3 + 2


def test_liquidated_backtest_shows_warning_and_liquidation_chart_line(qapp):
    liquidation = GridLiquidation(
        time_ms=0, liquidation_price=92.5, position_qty=15.0, avg_entry_price=98.0, margin_lost_usd=1.5
    )
    result = _grid_backtest_result(liquidation=liquidation)
    preview = BacktestPreview(result=result, candles=_backtest_candles())

    with patch("app.workers.run_grid_backtest_for_symbol", return_value=preview):
        tab = GridTab()
        tab._handle_run_backtest()
        tab._backtest_worker.wait()
        qapp.processEvents()

    summary = tab.backtest_summary_label.text()
    assert "LİKİDE OLDU" in summary
    assert "92.5" in summary
    assert "400" in summary  # kaybedilen sermaye (capital_usd)

    # Grafik: mum + 3 ara grid seviyesi + alt/üst sınır + likidasyon çizgisi (4. referans).
    assert len(tab.backtest_chart.series()) == 1 + 3 + 3


def test_backtest_error_shows_warning_and_reenables_button(qapp):
    with patch("app.workers.run_grid_backtest_for_symbol", side_effect=RuntimeError("boom")):
        with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
            tab = GridTab()
            tab._handle_run_backtest()
            tab._backtest_worker.wait()
            qapp.processEvents()

    mock_warning.assert_called_once()
    assert tab.run_backtest_button.isEnabled()
