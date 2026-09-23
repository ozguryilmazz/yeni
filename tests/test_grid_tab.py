import os
import time as time_module
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDateTime
from PySide6.QtGui import QGuiApplication

from app.backtest.engine import Candle
from app.grid_trading.grid import GridBacktestResult, GridFill, GridLiquidation, GridTrade, OpenGridPosition
from app.grid_trading.range_methods import GridRange
from app.grid_trading.screener import CandidateResult
from app.grid_trading.service import BacktestPreview, RangePreview
from app.ui.grid_tab import GridTab


def _candidate(symbol: str, passes: bool, **overrides) -> CandidateResult:
    defaults = dict(
        symbol=symbol,
        passes=passes,
        futures_volume_usd=250_000_000.0,
        atr_pct=0.03,
        adx_value=15.0,
        rsi_value=50.0,
        bollinger_percent_b=0.5,
        bollinger_bandwidth=0.08,
        last_price=100.0,
        failed_reasons=[] if passes else ["volatility"],
    )
    defaults.update(overrides)
    return CandidateResult(**defaults)


def _grid_backtest_result(
    trades: list[GridTrade] | None = None,
    liquidation: GridLiquidation | None = None,
    open_positions: list[OpenGridPosition] | None = None,
    end_price: float = 90.0,
) -> GridBacktestResult:
    trades = trades or []
    open_positions = open_positions or []
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
        end_price=end_price,
        min_price_seen=88.0,
        max_price_seen=100.0,
        breached_lower=True,
        breached_upper=False,
        open_buy_levels=[],
        open_sell_levels=[] if liquidation else [95.0],
        open_positions=open_positions,
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

    # Grafik başlığı hangi zaman dilimini gösterdiğini belirtmeli -- Aralık ve
    # Backtest grafikleri farklı ayarlar kullanabildiğinden (bkz. hangisine
    # bakıldığını karıştırmama amacı) bu ayrım önemli.
    assert "4 Saatlik" in tab.range_chart.title()


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


def test_run_backtest_converts_local_datetime_input_to_utc_not_just_relabels_it(qapp):
    # QDateTimeEdit.dateTime().toPython() kullanıcının GİRDİĞİ (sistemin
    # yerel saat diliminde yorumlanan) naive bir datetime döner -- bunun
    # UTC'ye sadece ETİKETLENMEDİĞİNİ, gerçekten DÖNÜŞTÜRÜLDÜĞÜNÜ doğrulamak
    # için işlemin yerel saat dilimini geçici olarak İstanbul'a (UTC+3, yaz
    # saati uygulaması olmayan sabit bir ofset) alıyoruz.
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Istanbul"
    time_module.tzset()
    try:
        with patch("app.workers.run_grid_backtest_for_symbol") as mock_run:
            tab = GridTab()
            tab.start_input.setDateTime(QDateTime(2026, 6, 1, 16, 0, 0))
            tab.end_input.setDateTime(QDateTime(2026, 6, 1, 18, 0, 0))

            tab._handle_run_backtest()
            tab._backtest_worker.wait()
            qapp.processEvents()

        captured_start = mock_run.call_args.args[1]
        captured_end = mock_run.call_args.args[2]
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time_module.tzset()

    # Yerel (İstanbul) 16:00 -> UTC 13:00 olmalı (16:00 UTC DEĞİL).
    assert captured_start == datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
    assert captured_end == datetime(2026, 6, 1, 15, 0, 0, tzinfo=timezone.utc)


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
    assert tab.backtest_open_positions_table.rowCount() == 0  # fixture'da açık pozisyon yok
    assert tab.grid_trade_table.rowCount() == 1
    assert tab.grid_trade_table.item(0, 1).text() == "90.000000"

    # Grafik: mum + 3 ara grid seviyesi + alt/üst sınır -- likidasyon YOK, 3. bir
    # referans çizgisi (likidasyon) eklenmemeli.
    assert len(tab.backtest_chart.series()) == 1 + 3 + 2
    assert "15 Dakika" in tab.backtest_chart.title()


def test_backtest_finished_renders_open_positions_table(qapp):
    position = OpenGridPosition(
        buy_price=90.0, buy_time_ms=0, sell_price=95.0, quantity=1.0, current_price=92.0, unrealized_pnl_usd=1.5
    )
    result = _grid_backtest_result(open_positions=[position], end_price=92.0)
    preview = BacktestPreview(result=result, candles=_backtest_candles())

    tab = GridTab()
    tab._on_backtest_finished(preview)

    assert tab.backtest_open_positions_table.rowCount() == 1
    assert tab.backtest_open_positions_table.item(0, 1).text() == "90.000000"  # Alış Fiyatı
    assert tab.backtest_open_positions_table.item(0, 3).text() == "92.000000"  # Güncel Fiyat
    assert tab.backtest_open_positions_table.item(0, 5).text() == "+1.5000"  # Anlık K/Z


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


# ---- Kağıt İşlem (İleri Test) ----------------------------------------------


def test_start_paper_trading_warns_when_symbol_is_empty(qapp):
    tab = GridTab()
    tab.symbol_input.setText("")

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_start_paper_trading()

    mock_warning.assert_called_once()
    assert tab._paper_thread is None


def test_start_paper_trading_warns_when_lower_bound_is_not_below_upper(qapp):
    tab = GridTab()
    tab.lower_price_input.setValue(110.0)
    tab.upper_price_input.setValue(100.0)

    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._handle_start_paper_trading()

    mock_warning.assert_called_once()
    assert tab._paper_thread is None


def test_start_paper_trading_creates_thread_with_shared_settings_and_updates_ui(qapp):
    mock_thread = MagicMock()
    with patch("app.ui.grid_tab.GridPaperTradingThread", return_value=mock_thread) as mock_thread_cls:
        tab = GridTab()
        tab.symbol_input.setText("ethusdt")
        tab.lower_price_input.setValue(90.0)
        tab.upper_price_input.setValue(110.0)
        tab.grid_count_input.setValue(10)
        tab.capital_input.setValue(500.0)
        tab.leverage_input.setValue(5)
        tab.fee_rate_input.setValue(0.05)
        tab.maintenance_margin_input.setValue(0.4)
        tab._handle_start_paper_trading()

    mock_thread_cls.assert_called_once()
    args = mock_thread_cls.call_args.args
    assert args[0] == "ETHUSDT"
    assert args[2] == pytest.approx(90.0)
    assert args[3] == pytest.approx(110.0)
    assert args[4] == 10
    assert args[5] == pytest.approx(500.0)
    assert args[6] == 5
    assert args[7] == pytest.approx(0.0005)
    assert args[8] == pytest.approx(0.004)

    mock_thread.start.assert_called_once()
    assert tab._paper_thread is mock_thread
    assert not tab.start_paper_button.isEnabled()
    assert tab.stop_paper_button.isEnabled()
    assert not tab.lower_price_input.isEnabled()


def test_stop_paper_trading_stops_thread_and_resets_ui(qapp):
    tab = GridTab()
    mock_thread = MagicMock()
    tab._paper_thread = mock_thread
    tab._set_paper_running_ui(True)

    tab._handle_stop_paper_trading()

    mock_thread.stop.assert_called_once()
    mock_thread.wait.assert_called_once()
    assert tab._paper_thread is None
    assert tab.start_paper_button.isEnabled()
    assert not tab.stop_paper_button.isEnabled()


def test_stop_paper_trading_public_method_is_noop_when_not_running(qapp):
    tab = GridTab()
    tab.stop_paper_trading()  # hiçbir kağıt işlem çalışmıyorken hata vermemeli
    assert tab._paper_thread is None


def test_paper_setup_info_renders_and_survives_later_status_updates(qapp):
    # Açılış koşulları (sermaye/kaldıraç/komisyon/vb.) ayrı bir etikette
    # gösterilmeli ki sonradan gelen geçici durum mesajlarıyla (ör. WS
    # yeniden bağlanma) ÜZERİNE YAZILMASIN.
    tab = GridTab()

    tab._on_paper_setup_info("<b>Kurulum:</b> ETHUSDT · Sermaye: 500.00$ · Kaldıraç: 5x")
    tab._on_paper_status("ETHUSDT 5m mum kapanışları izleniyor…")

    assert "Kurulum" in tab.paper_setup_label.text()
    assert "500" in tab.paper_setup_label.text()
    assert "izleniyor" in tab.paper_status_label.text()


def test_start_paper_trading_resets_setup_label(qapp):
    tab = GridTab()
    tab.paper_setup_label.setText("eski kurulum bilgisi")

    with patch("app.ui.grid_tab.GridPaperTradingThread", return_value=MagicMock()):
        tab._handle_start_paper_trading()

    assert tab.paper_setup_label.text() == "—"


def test_paper_snapshot_renders_summary_chart_and_trades(qapp):
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
    candles = _backtest_candles()

    tab = GridTab()
    tab._on_paper_snapshot(result, candles)

    assert tab._paper_result is result
    assert "1" in tab.paper_summary_label.text()  # Tamamlanan İşlem: 1
    assert tab.paper_trade_table.rowCount() == 1
    assert tab.paper_trade_table.item(0, 1).text() == "90.000000"
    assert len(tab.paper_chart.series()) == 1 + 3 + 2
    assert "Kağıt İşlem" in tab.paper_chart.title()


def test_paper_snapshot_renders_open_positions_table(qapp):
    position = OpenGridPosition(
        buy_price=90.0, buy_time_ms=0, sell_price=95.0, quantity=1.0, current_price=92.0, unrealized_pnl_usd=1.5
    )
    result = _grid_backtest_result(open_positions=[position], end_price=92.0)
    candles = _backtest_candles()

    tab = GridTab()
    tab._on_paper_snapshot(result, candles)

    assert tab.paper_open_positions_table.rowCount() == 1
    assert tab.paper_open_positions_table.item(0, 1).text() == "90.000000"  # Alış Fiyatı
    assert tab.paper_open_positions_table.item(0, 2).text() == "95.000000"  # Hedef Satış
    assert tab.paper_open_positions_table.item(0, 3).text() == "92.000000"  # Güncel Fiyat
    assert tab.paper_open_positions_table.item(0, 5).text() == "+1.5000"  # Anlık K/Z


def test_paper_snapshot_price_ticker_shows_direction_and_color(qapp):
    tab = GridTab()
    candles = _backtest_candles()

    # İlk güncelleme: karşılaştırılacak önceki fiyat yok -- nötr (oksuz) gösterilmeli.
    tab._on_paper_snapshot(_grid_backtest_result(end_price=100.0), candles)
    assert "100.000000" in tab.paper_price_ticker_label.text()
    assert "▲" not in tab.paper_price_ticker_label.text()
    assert "▼" not in tab.paper_price_ticker_label.text()

    # Fiyat YÜKSELDİ: yeşil + yukarı ok.
    tab._on_paper_snapshot(_grid_backtest_result(end_price=101.0), candles)
    assert "▲" in tab.paper_price_ticker_label.text()
    assert "#2e7d32" in tab.paper_price_ticker_label.text()

    # Fiyat DÜŞTÜ: kırmızı + aşağı ok.
    tab._on_paper_snapshot(_grid_backtest_result(end_price=99.0), candles)
    assert "▼" in tab.paper_price_ticker_label.text()
    assert "#c62828" in tab.paper_price_ticker_label.text()


def test_start_paper_trading_resets_open_positions_table_and_price_ticker(qapp):
    tab = GridTab()
    position = OpenGridPosition(
        buy_price=90.0, buy_time_ms=0, sell_price=95.0, quantity=1.0, current_price=92.0, unrealized_pnl_usd=1.5
    )
    tab._on_paper_snapshot(_grid_backtest_result(open_positions=[position], end_price=92.0), _backtest_candles())
    assert tab.paper_open_positions_table.rowCount() == 1
    assert tab._paper_last_ticker_price == pytest.approx(92.0)

    tab.symbol_input.setText("BTCUSDT")
    with patch("app.ui.grid_tab.GridPaperTradingThread", return_value=MagicMock()):
        tab._handle_start_paper_trading()

    assert tab.paper_open_positions_table.rowCount() == 0
    assert tab.paper_price_ticker_label.text() == "—"
    assert tab._paper_last_ticker_price is None


def test_paper_liquidated_shows_warning(qapp):
    liquidation = GridLiquidation(
        time_ms=0, liquidation_price=92.5, position_qty=15.0, avg_entry_price=98.0, margin_lost_usd=1.5
    )
    result = _grid_backtest_result(liquidation=liquidation)

    tab = GridTab()
    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._on_paper_liquidated(result)

    mock_warning.assert_called_once()
    assert "92.5" in mock_warning.call_args.args[2]


def test_paper_error_shows_warning(qapp):
    tab = GridTab()
    with patch("app.ui.grid_tab.QMessageBox.warning") as mock_warning:
        tab._on_paper_error("boom")

    mock_warning.assert_called_once()
    assert "boom" in mock_warning.call_args.args[2]
