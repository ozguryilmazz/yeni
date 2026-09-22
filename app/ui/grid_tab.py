from datetime import datetime, timezone

from PySide6.QtCharts import (
    QCandlestickSeries,
    QCandlestickSet,
    QChart,
    QChartView,
    QDateTimeAxis,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backtest.engine import Candle
from app.grid_trading.grid import (
    DEFAULT_FEE_RATE,
    DEFAULT_GRID_COUNT,
    DEFAULT_MAINTENANCE_MARGIN_RATE,
    GridBacktestResult,
    build_grid_levels,
)
from app.grid_trading.range_methods import DEFAULT_RANGE_METHOD, RANGE_METHOD_LABELS, GridRange
from app.grid_trading.screener import CandidateResult, ScreenerCriteria
from app.grid_trading.service import (
    DEFAULT_CAPITAL_USD,
    DEFAULT_GRID_BACKTEST_INTERVAL,
    DEFAULT_RANGE_INTERVAL,
    SUPPORTED_GRID_INTERVALS,
    BacktestPreview,
    RangePreview,
)
from app.ui.market_tab import NumericTableWidgetItem
from app.workers import ComputeGridRangeWorker, RunGridBacktestWorker, RunGridScreenerWorker

RANGE_INTERVAL_LABELS = {"4h": "4 Saatlik", "1d": "Günlük"}
BACKTEST_INTERVAL_LABELS = {"5m": "5 Dakika", "15m": "15 Dakika", "1h": "1 Saat", "4h": "4 Saatlik"}
FAILED_REASON_LABELS = {
    "spot_volume": "Spot Hacim",
    "futures_volume": "Futures Hacim",
    "volatility": "Volatilite",
    "trend": "Trend",
}


def _format_usd_compact(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M$"
    if abs(value) >= 1_000:
        return f"{value / 1_000:,.1f}K$"
    return f"{value:,.2f}$"


def _format_pct(value: float | None) -> str:
    return "—" if value is None else f"%{value * 100:.2f}"


def _format_number(value: float | None, decimals: int = 2) -> str:
    return "—" if value is None else f"{value:,.{decimals}f}"


class GridTab(QWidget):
    """'Grid' sekmesi: 3 aşamalı grid ticareti iş akışı.

    1. **Tarama**: TÜM USDT-M futures sembollerini likidite (24s hacim),
       volatilite (ATR14/fiyat %2-%6) ve trend-olmama (ADX14<25) kurallarına
       göre tarar (bkz. app.grid_trading.screener) — grid için uygun aday
       coinleri bulur.
    2. **Aralık Hesaplama**: seçilen sembol için 3 yöntemden biriyle
       (destek/direnç, Bollinger, ATR — bkz. app.grid_trading.range_methods)
       grid'in alt/üst sınırını önerir.
    3. **Grid Backtest**: önerilen (veya elle girilen) sınırlar, grid sayısı
       ve sermaye ile geçmiş veri üzerinde AL/SAT dolum simülasyonu çalıştırır
       (bkz. app.grid_trading.grid).

    Bu sekme SADECE simülasyon yapar — gerçek para ile canlı grid emri
    göndermez (bu, ayrı bir sonraki adımdır)."""

    def __init__(self) -> None:
        super().__init__()
        self._screener_worker: RunGridScreenerWorker | None = None
        self._range_worker: ComputeGridRangeWorker | None = None
        self._backtest_worker: RunGridBacktestWorker | None = None
        self._screener_results: list[CandidateResult] = []
        self._backtest_result: GridBacktestResult | None = None

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addLayout(self._build_screener_section())
        content_layout.addLayout(self._build_range_section())
        content_layout.addLayout(self._build_backtest_section())

        # Bu sekmede çok sayıda bölüm (tarama tablosu, grafik, backtest formu +
        # sonuç tablosu) alt alta dizili -- pencere boyunu kolayca aşabiliyor.
        # Kaydırma alanı olmadan Qt bazı widget'ları sıkıştırıp üst üste
        # bindirebiliyordu; bunun yerine gerektiğinde kaydırma çubuğu çıkar.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll_area)

    # ---- 1. Tarama ----------------------------------------------------

    def _build_screener_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.addWidget(QLabel("<b>1. Coin Tarama</b>"))

        hint = QLabel(
            "24s hacim (spotta ≥50M$, futures'ta ≥200M$), volatilite (günlük ATR14/fiyat "
            "%2-%6 arası) ve trend olmama (4 saatlik ADX14<25) kriterlerine göre TÜM USDT-M "
            "futures sembollerini tarar. Bir satıra çift tıklayarak sembolü aşağıdaki "
            "Aralık Hesaplama ve Backtest bölümlerine seçebilirsiniz."
        )
        hint.setWordWrap(True)
        section.addWidget(hint)

        controls = QHBoxLayout()
        self.scan_button = QPushButton("Coin Tara")
        self.scan_button.clicked.connect(self._handle_scan)
        controls.addWidget(self.scan_button)

        self.only_eligible_checkbox = QCheckBox("Sadece uygun coinleri göster")
        self.only_eligible_checkbox.setChecked(True)
        self.only_eligible_checkbox.stateChanged.connect(self._render_screener_results)
        controls.addWidget(self.only_eligible_checkbox)
        controls.addStretch()
        section.addLayout(controls)

        self.screener_status_label = QLabel("—")
        section.addWidget(self.screener_status_label)

        self.screener_table = QTableWidget(0, 6)
        self.screener_table.setHorizontalHeaderLabels(
            ["Sembol", "Spot Hacim", "Futures Hacim", "ATR%", "ADX", "Durum"]
        )
        self.screener_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.screener_table.setSortingEnabled(True)
        self.screener_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.screener_table.cellDoubleClicked.connect(self._handle_screener_row_selected)
        self.screener_table.setMaximumHeight(220)
        section.addWidget(self.screener_table)

        return section

    def _handle_scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.screener_status_label.setText("Taranıyor… (yüzlerce sembol için birkaç dakika sürebilir)")
        self._screener_worker = RunGridScreenerWorker(ScreenerCriteria())
        self._screener_worker.success.connect(self._on_scan_finished)
        self._screener_worker.error.connect(self._on_scan_error)
        self._screener_worker.start()

    def _on_scan_finished(self, results: list[CandidateResult]) -> None:
        self.scan_button.setEnabled(True)
        self._screener_results = results
        passing = sum(1 for r in results if r.passes)
        self.screener_status_label.setText(f"{len(results)} sembol tarandı, {passing} tanesi uygun.")
        self._render_screener_results()

    def _on_scan_error(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.screener_status_label.setText("—")
        QMessageBox.warning(self, "Tarama başarısız", message)

    def _render_screener_results(self) -> None:
        rows = self._screener_results
        if self.only_eligible_checkbox.isChecked():
            rows = [r for r in rows if r.passes]

        self.screener_table.setSortingEnabled(False)
        self.screener_table.setRowCount(len(rows))
        for i, candidate in enumerate(rows):
            self.screener_table.setItem(i, 0, QTableWidgetItem(candidate.symbol))
            self.screener_table.setItem(
                i, 1, NumericTableWidgetItem(candidate.spot_volume_usd or 0.0, _format_usd_compact(candidate.spot_volume_usd))
            )
            self.screener_table.setItem(
                i,
                2,
                NumericTableWidgetItem(
                    candidate.futures_volume_usd or 0.0, _format_usd_compact(candidate.futures_volume_usd)
                ),
            )
            self.screener_table.setItem(
                i, 3, NumericTableWidgetItem(candidate.atr_pct or 0.0, _format_pct(candidate.atr_pct))
            )
            self.screener_table.setItem(
                i, 4, NumericTableWidgetItem(candidate.adx_value or 0.0, _format_number(candidate.adx_value))
            )
            status_text = "Uygun" if candidate.passes else ", ".join(
                FAILED_REASON_LABELS.get(r, r) for r in candidate.failed_reasons
            )
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QBrush(QColor("#2e7d32" if candidate.passes else "#c62828")))
            self.screener_table.setItem(i, 5, status_item)
        self.screener_table.setSortingEnabled(True)

    def _handle_screener_row_selected(self, row: int, _column: int) -> None:
        symbol_item = self.screener_table.item(row, 0)
        if symbol_item:
            self.symbol_input.setText(symbol_item.text())

    # ---- 2. Aralık Hesaplama -------------------------------------------

    def _build_range_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.addWidget(QLabel("<b>2. Grid Aralığı (Alt/Üst Sınır) Hesaplama</b>"))

        symbol_row = QHBoxLayout()
        symbol_row.addWidget(QLabel("Sembol"))
        self.symbol_input = QLineEdit("BTCUSDT")
        symbol_row.addWidget(self.symbol_input)
        self.paste_button = QPushButton("Yapıştır")
        self.paste_button.clicked.connect(self._handle_paste)
        symbol_row.addWidget(self.paste_button)

        symbol_row.addWidget(QLabel("Zaman Dilimi"))
        self.range_interval_combo = QComboBox()
        for interval, label in RANGE_INTERVAL_LABELS.items():
            self.range_interval_combo.addItem(label, interval)
        self.range_interval_combo.setCurrentIndex(self.range_interval_combo.findData(DEFAULT_RANGE_INTERVAL))
        symbol_row.addWidget(self.range_interval_combo)

        symbol_row.addWidget(QLabel("Metot"))
        self.method_combo = QComboBox()
        for method, label in RANGE_METHOD_LABELS.items():
            self.method_combo.addItem(label, method)
        self.method_combo.setCurrentIndex(self.method_combo.findData(DEFAULT_RANGE_METHOD))
        self.method_combo.currentIndexChanged.connect(self._update_method_params_visibility)
        symbol_row.addWidget(self.method_combo)
        section.addLayout(symbol_row)

        section.addLayout(self._build_support_resistance_params())
        section.addLayout(self._build_bollinger_params())
        section.addLayout(self._build_atr_params())
        self._update_method_params_visibility()

        compute_row = QHBoxLayout()
        self.compute_range_button = QPushButton("Aralık Hesapla")
        self.compute_range_button.clicked.connect(self._handle_compute_range)
        compute_row.addWidget(self.compute_range_button)
        compute_row.addStretch()
        section.addLayout(compute_row)

        self.range_result_label = QLabel("—")
        self.range_result_label.setWordWrap(True)
        section.addWidget(self.range_result_label)

        self.range_chart = QChart()
        self.range_chart.legend().hide()
        self.range_chart_view = QChartView(self.range_chart)
        self.range_chart_view.setFixedHeight(320)
        section.addWidget(self.range_chart_view)

        return section

    def _build_support_resistance_params(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Min. Dokunuş"))
        self.min_touches_input = QSpinBox()
        self.min_touches_input.setRange(2, 10)
        self.min_touches_input.setValue(2)
        row.addWidget(self.min_touches_input)

        row.addWidget(QLabel("Marj %"))
        self.margin_pct_input = QDoubleSpinBox()
        self.margin_pct_input.setRange(0.0, 10.0)
        self.margin_pct_input.setSingleStep(0.1)
        self.margin_pct_input.setValue(1.5)
        row.addWidget(self.margin_pct_input)
        row.addStretch()
        self._support_resistance_params_row = row
        return row

    def _build_bollinger_params(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Periyot"))
        self.bollinger_period_input = QSpinBox()
        self.bollinger_period_input.setRange(2, 200)
        self.bollinger_period_input.setValue(20)
        row.addWidget(self.bollinger_period_input)

        row.addWidget(QLabel("Std. Sapma Çarpanı"))
        self.bollinger_std_input = QDoubleSpinBox()
        self.bollinger_std_input.setRange(0.5, 5.0)
        self.bollinger_std_input.setSingleStep(0.1)
        self.bollinger_std_input.setValue(2.0)
        row.addWidget(self.bollinger_std_input)
        row.addStretch()
        self._bollinger_params_row = row
        return row

    def _build_atr_params(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("ATR Periyot"))
        self.atr_period_input = QSpinBox()
        self.atr_period_input.setRange(2, 200)
        self.atr_period_input.setValue(14)
        row.addWidget(self.atr_period_input)

        row.addWidget(QLabel("Çarpan (k)"))
        self.atr_k_input = QDoubleSpinBox()
        self.atr_k_input.setRange(0.5, 20.0)
        self.atr_k_input.setSingleStep(0.5)
        self.atr_k_input.setValue(3.0)
        row.addWidget(self.atr_k_input)
        row.addStretch()
        self._atr_params_row = row
        return row

    def _update_method_params_visibility(self) -> None:
        method = self.method_combo.currentData()
        self._set_row_visible(self._support_resistance_params_row, method == "support_resistance")
        self._set_row_visible(self._bollinger_params_row, method == "bollinger")
        self._set_row_visible(self._atr_params_row, method == "atr")

    @staticmethod
    def _set_row_visible(row: QHBoxLayout, visible: bool) -> None:
        for i in range(row.count()):
            widget = row.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(visible)

    def _handle_paste(self) -> None:
        text = QGuiApplication.clipboard().text().strip().upper()
        if text:
            self.symbol_input.setText(text)

    def _handle_compute_range(self) -> None:
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Grid", "Bir sembol girin (ör. BTCUSDT)")
            return

        method = self.method_combo.currentData()
        method_kwargs = self._current_method_kwargs(method)

        self.compute_range_button.setEnabled(False)
        self.range_result_label.setText("Hesaplanıyor…")
        self._range_worker = ComputeGridRangeWorker(
            symbol, method, self.range_interval_combo.currentData(), 120, method_kwargs
        )
        self._range_worker.success.connect(self._on_range_computed)
        self._range_worker.error.connect(self._on_range_error)
        self._range_worker.start()

    def _current_method_kwargs(self, method: str) -> dict:
        if method == "support_resistance":
            return {"min_touches": self.min_touches_input.value(), "margin_pct": self.margin_pct_input.value() / 100}
        if method == "bollinger":
            return {"period": self.bollinger_period_input.value(), "std_mult": self.bollinger_std_input.value()}
        if method == "atr":
            return {"period": self.atr_period_input.value(), "k": self.atr_k_input.value()}
        return {}

    def _on_range_computed(self, preview: RangePreview) -> None:
        self.compute_range_button.setEnabled(True)
        grid_range = preview.grid_range
        self.lower_price_input.setValue(grid_range.lower_price)
        self.upper_price_input.setValue(grid_range.upper_price)

        details = ", ".join(f"{k}: {v:.6g}" if isinstance(v, float) else f"{k}: {v}" for k, v in grid_range.details.items())
        self.range_result_label.setText(
            f"<b>Alt Sınır:</b> {grid_range.lower_price:,.6f} &nbsp; <b>Üst Sınır:</b> {grid_range.upper_price:,.6f}"
            f"<br><span style='color:#666;'>{details}</span>"
        )
        self._render_range_chart(preview.candles, grid_range)

    def _on_range_error(self, message: str) -> None:
        self.compute_range_button.setEnabled(True)
        self.range_result_label.setText("—")
        QMessageBox.warning(self, "Aralık hesaplanamadı", message)

    def _render_range_chart(self, candles: list[Candle], grid_range: GridRange) -> None:
        # Aralık önizlemesinde, kullanıcının o an Backtest bölümünde seçili
        # grid sayısı kadar ARA seviyeyi de ince gri çizgilerle gösteririz --
        # gerçek backtest'te kullanılacak grid'in bir önizlemesi.
        grid_count = self.grid_count_input.value()
        try:
            grid_levels = build_grid_levels(grid_range.lower_price, grid_range.upper_price, grid_count)
            inner_levels = grid_levels[1:-1]
        except ValueError:
            inner_levels = []
        interval_label = RANGE_INTERVAL_LABELS.get(self.range_interval_combo.currentData(), "")
        self._render_price_chart(
            self.range_chart,
            candles,
            bound_lines=[
                (grid_range.lower_price, "Alt Sınır", "#1565c0"),
                (grid_range.upper_price, "Üst Sınır", "#ef6c00"),
            ],
            grid_lines=inner_levels,
            title=_format_chart_title(f"Aralık önizlemesi — {interval_label}", candles),
        )

    def _render_price_chart(
        self,
        chart: QChart,
        candles: list[Candle],
        bound_lines: list[tuple[float, str, str]],
        grid_lines: list[float] | None = None,
        title: str = "",
    ) -> None:
        """Mum grafiği + öne çıkan (kalın/renkli, `bound_lines`) referans
        çizgileri + istenirse (`grid_lines`) aradaki TÜM grid seviyelerini
        ince gri çizgilerle çizer. `title`, grafiğin hangi zaman dilimi/
        aralığı gösterdiğini belirtir -- Aralık Hesaplama ve Grid Backtest
        grafikleri BAĞIMSIZ ayarlar (farklı zaman dilimi/pencere)
        kullandığından, hangisine baktığınızı karıştırmamak için."""
        chart.setTitle(title)
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)
        if not candles:
            return

        candle_series = QCandlestickSeries()
        candle_series.setIncreasingColor(QColor("#2e7d32"))
        candle_series.setDecreasingColor(QColor("#c62828"))
        for candle in candles:
            candle_series.append(
                QCandlestickSet(candle.open, candle.high, candle.low, candle.close, float(candle.open_time_ms))
            )
        chart.addSeries(candle_series)
        all_series = [candle_series]

        for level in grid_lines or []:
            line = self._make_reference_line(None, candles, level, "#bdbdbd", width=1, style=Qt.PenStyle.SolidLine)
            chart.addSeries(line)
            all_series.append(line)

        for price, name, color in bound_lines:
            line = self._make_reference_line(name, candles, price, color, width=2, style=Qt.PenStyle.DashLine)
            chart.addSeries(line)
            all_series.append(line)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("dd.MM HH:mm")
        axis_x.setRange(
            QDateTime.fromMSecsSinceEpoch(candles[0].open_time_ms), QDateTime.fromMSecsSinceEpoch(candles[-1].open_time_ms)
        )
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)

        axis_y = QValueAxis()
        all_prices = (
            [c.low for c in candles] + [c.high for c in candles] + [price for price, _, _ in bound_lines] + (grid_lines or [])
        )
        y_min, y_max = min(all_prices), max(all_prices)
        padding = (y_max - y_min) * 0.05 if y_max > y_min else max(abs(y_max) * 0.01, 1e-9)
        axis_y.setRange(y_min - padding, y_max + padding)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)

        for series in all_series:
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

    @staticmethod
    def _make_reference_line(
        name: str | None, candles: list[Candle], price: float, color: str, width: int, style: Qt.PenStyle
    ) -> QLineSeries:
        series = QLineSeries()
        if name:
            series.setName(name)
        series.append(float(candles[0].open_time_ms), price)
        series.append(float(candles[-1].open_time_ms), price)
        pen = series.pen()
        pen.setColor(QColor(color))
        pen.setStyle(style)
        pen.setWidth(width)
        series.setPen(pen)
        return series

    # ---- 3. Grid Backtest ------------------------------------------------

    def _build_backtest_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.addWidget(QLabel("<b>3. Grid Backtest</b>"))

        bounds_row = QHBoxLayout()
        bounds_row.addWidget(QLabel("Alt Sınır"))
        self.lower_price_input = QDoubleSpinBox()
        self.lower_price_input.setRange(0.000001, 10_000_000.0)
        self.lower_price_input.setDecimals(6)
        self.lower_price_input.setValue(90.0)
        bounds_row.addWidget(self.lower_price_input)

        bounds_row.addWidget(QLabel("Üst Sınır"))
        self.upper_price_input = QDoubleSpinBox()
        self.upper_price_input.setRange(0.000001, 10_000_000.0)
        self.upper_price_input.setDecimals(6)
        self.upper_price_input.setValue(110.0)
        bounds_row.addWidget(self.upper_price_input)

        bounds_row.addWidget(QLabel("Grid Sayısı"))
        self.grid_count_input = QSpinBox()
        self.grid_count_input.setRange(2, 500)
        self.grid_count_input.setValue(DEFAULT_GRID_COUNT)
        bounds_row.addWidget(self.grid_count_input)

        bounds_row.addWidget(QLabel("Sermaye (USD)"))
        self.capital_input = QDoubleSpinBox()
        self.capital_input.setRange(1.0, 100_000_000.0)
        self.capital_input.setDecimals(2)
        self.capital_input.setValue(DEFAULT_CAPITAL_USD)
        bounds_row.addWidget(self.capital_input)
        section.addLayout(bounds_row)

        risk_row = QHBoxLayout()
        risk_row.addWidget(QLabel("Kaldıraç"))
        self.leverage_input = QSpinBox()
        self.leverage_input.setRange(1, 20)
        self.leverage_input.setValue(3)
        self.leverage_input.setSuffix("x")
        risk_row.addWidget(self.leverage_input)

        risk_row.addWidget(QLabel("Komisyon %"))
        self.fee_rate_input = QDoubleSpinBox()
        self.fee_rate_input.setRange(0.0, 1.0)
        self.fee_rate_input.setDecimals(3)
        self.fee_rate_input.setSingleStep(0.01)
        self.fee_rate_input.setValue(DEFAULT_FEE_RATE * 100)
        risk_row.addWidget(self.fee_rate_input)

        risk_row.addWidget(QLabel("Bakım Marjini %"))
        self.maintenance_margin_input = QDoubleSpinBox()
        self.maintenance_margin_input.setRange(0.01, 10.0)
        self.maintenance_margin_input.setDecimals(3)
        self.maintenance_margin_input.setSingleStep(0.1)
        self.maintenance_margin_input.setValue(DEFAULT_MAINTENANCE_MARGIN_RATE * 100)
        risk_row.addWidget(self.maintenance_margin_input)
        risk_row.addStretch()
        section.addLayout(risk_row)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Zaman Dilimi"))
        self.backtest_interval_combo = QComboBox()
        for interval in SUPPORTED_GRID_INTERVALS:
            self.backtest_interval_combo.addItem(BACKTEST_INTERVAL_LABELS.get(interval, interval), interval)
        self.backtest_interval_combo.setCurrentIndex(
            self.backtest_interval_combo.findData(DEFAULT_GRID_BACKTEST_INTERVAL)
        )
        date_row.addWidget(self.backtest_interval_combo)

        date_row.addWidget(QLabel("Başlangıç"))
        self.start_input = QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(-14))
        self.start_input.setCalendarPopup(True)
        self.start_input.setDisplayFormat("dd.MM.yyyy HH:mm")
        date_row.addWidget(self.start_input)

        date_row.addWidget(QLabel("Bitiş"))
        self.end_input = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        self.end_input.setCalendarPopup(True)
        self.end_input.setDisplayFormat("dd.MM.yyyy HH:mm")
        date_row.addWidget(self.end_input)

        self.run_backtest_button = QPushButton("Grid Backtest Çalıştır")
        self.run_backtest_button.clicked.connect(self._handle_run_backtest)
        date_row.addWidget(self.run_backtest_button)
        date_row.addStretch()
        section.addLayout(date_row)

        hint = QLabel(
            "Sermaye × kaldıraç (nominal büyüklük) grid sayısına eşit bölünüp ilk mumun "
            "açılışına göre sabit bir miktara çevrilir. Başlangıç fiyatının ALTINDAKİ "
            "seviyelere AL emri konur; ÜSTÜNDEKİ seviyeler için ise (gerçek grid botlarında "
            "olduğu gibi) kurulumda PİYASADAN envanter alınıp hemen SAT emri konur — aksi "
            "halde fiyat aralığın tamamen dışında başlarsa (ör. aralık güncel fiyata göre "
            "hesaplanıp backtest geçmişe dönük çalıştırıldığında) hiç emir kurulamaz ve hiç "
            "işlem gerçekleşmez. Her hücre AL+SAT tamamlandığında yeniden kurulur. TÜM "
            "dolumlarda (kurulum seed'i dahil) girdiğiniz TEK komisyon oranı uygulanır — "
            "varsayılan olarak taker (maker'dan yüksek) oranı, her dolumun iyimser biçimde "
            "maker olacağını varsaymamak için. Fiyat grid ARALIĞININ dışına çıkarsa o yöndeki "
            "emirler tükenir (stop-loss YOK) — kalan envanter sadece mark-to-market izlenir. "
            "LİKİDASYON: kaldıraç 1'den büyükse, o anki TÜM açık envanter (kurulum seed'i "
            "dahil) tek bir izole marjin pozisyonu gibi izlenir; fiyat likidasyon seviyesine "
            "değerse (grid aralığından bağımsız, ondan genelde çok daha aşağıda olur) TÜM açık "
            "pozisyon zorla kapatılır, tüm emirler iptal edilir ve backtest orada durur — "
            "sermayenin tamamı kaybedilmiş sayılır. Realize edilen kârlar bu izole marjini "
            "büyütüp likidasyon riskini gerçekçi şekilde azaltır. Bakım marjini oranı sembole "
            "göre değişir, buradaki değer bir yaklaşıklıktır. Bu sekme sadece geçmiş veri "
            "üzerinde simülasyon yapar, gerçek işlem açmaz."
        )
        hint.setWordWrap(True)
        section.addWidget(hint)

        self.backtest_summary_label = QLabel("—")
        self.backtest_summary_label.setWordWrap(True)
        section.addWidget(self.backtest_summary_label)

        self.backtest_chart = QChart()
        self.backtest_chart.legend().hide()
        self.backtest_chart_view = QChartView(self.backtest_chart)
        self.backtest_chart_view.setFixedHeight(320)
        section.addWidget(self.backtest_chart_view)

        self.grid_trade_table = QTableWidget(0, 6)
        self.grid_trade_table.setHorizontalHeaderLabels(
            ["Alış Zamanı", "Alış Fiyatı", "Satış Zamanı", "Satış Fiyatı", "Miktar", "Net K/Z (USD)"]
        )
        self.grid_trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        section.addWidget(self.grid_trade_table)

        return section

    def _handle_run_backtest(self) -> None:
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Grid Backtest", "Bir sembol girin (ör. BTCUSDT)")
            return
        if self.lower_price_input.value() >= self.upper_price_input.value():
            QMessageBox.warning(self, "Grid Backtest", "Alt sınır, üst sınırdan küçük olmalı")
            return

        start = self.start_input.dateTime().toPython().replace(tzinfo=timezone.utc)
        end = self.end_input.dateTime().toPython().replace(tzinfo=timezone.utc)
        if start >= end:
            QMessageBox.warning(self, "Grid Backtest", "Başlangıç tarihi bitiş tarihinden önce olmalı")
            return

        self.run_backtest_button.setEnabled(False)
        self.backtest_summary_label.setText("Çalışıyor…")
        self.grid_trade_table.setRowCount(0)

        self._backtest_worker = RunGridBacktestWorker(
            symbol,
            start,
            end,
            self.backtest_interval_combo.currentData(),
            self.lower_price_input.value(),
            self.upper_price_input.value(),
            self.grid_count_input.value(),
            self.capital_input.value(),
            self.leverage_input.value(),
            self.fee_rate_input.value() / 100,
            self.maintenance_margin_input.value() / 100,
        )
        self._backtest_worker.success.connect(self._on_backtest_finished)
        self._backtest_worker.error.connect(self._on_backtest_error)
        self._backtest_worker.start()

    def _on_backtest_finished(self, preview: BacktestPreview) -> None:
        self.run_backtest_button.setEnabled(True)
        self._backtest_result = preview.result
        self._render_backtest_summary(preview.result)
        self._render_grid_trades(preview.result)
        self._render_backtest_chart(preview.candles, preview.result)

    def _on_backtest_error(self, message: str) -> None:
        self.run_backtest_button.setEnabled(True)
        self._backtest_result = None
        self.backtest_summary_label.setText("—")
        QMessageBox.warning(self, "Grid backtest çalıştırılamadı", message)

    def _render_backtest_chart(self, candles: list[Candle], result: GridBacktestResult) -> None:
        inner_levels = result.grid_levels[1:-1]
        bound_lines = [
            (result.grid_levels[0], "Alt Sınır", "#1565c0"),
            (result.grid_levels[-1], "Üst Sınır", "#ef6c00"),
        ]
        if result.liquidation is not None:
            bound_lines.append((result.liquidation.liquidation_price, "Likidasyon", "#b71c1c"))
        interval_label = BACKTEST_INTERVAL_LABELS.get(self.backtest_interval_combo.currentData(), "")
        self._render_price_chart(
            self.backtest_chart,
            candles,
            bound_lines=bound_lines,
            grid_lines=inner_levels,
            title=_format_chart_title(f"Grid Backtest — {interval_label}", candles),
        )

    def _render_backtest_summary(self, result: GridBacktestResult) -> None:
        pnl_color = "#2e7d32" if result.total_pnl_usd >= 0 else "#c62828"
        realized_color = "#2e7d32" if result.realized_pnl_usd >= 0 else "#c62828"
        unrealized_color = "#2e7d32" if result.unrealized_pnl_usd >= 0 else "#c62828"

        lines = []
        if result.liquidated and result.liquidation is not None:
            liq = result.liquidation
            lines.append(
                "<span style='color:#b71c1c; font-weight:bold;'>LİKİDE OLDU</span> — "
                f"{_format_ms(liq.time_ms)} tarihinde, {liq.liquidation_price:,.6f} fiyatında, "
                f"{liq.position_qty:.6f} adetlik (ort. giriş {liq.avg_entry_price:,.6f}) açık pozisyon "
                f"zorla kapatıldı; bot orada durdu (sonraki mumlar işlenmedi). Sermayenin TAMAMI "
                f"({result.capital_usd:,.2f}$) kaybedilmiş sayılır — o ana kadar gerçekleşen kârlar "
                f"da (aşağıdaki 'Gerçekleşen K/Z') aynı izole marjin cüzdanında olduğundan onunla "
                f"birlikte gitmiştir."
            )
        lines += [
            f"<b>Tamamlanan İşlem:</b> {len(result.trades)} &nbsp; "
            f"<b>Gerçekleşen K/Z:</b> <span style='color:{realized_color};'>{result.realized_pnl_usd:+,.4f}$</span>",
            f"<b>Envanter (Gerçekleşmemiş) K/Z:</b> "
            f"<span style='color:{unrealized_color};'>{result.unrealized_pnl_usd:+,.4f}$</span> "
            f"({result.final_inventory_qty:.6f} adet, {result.final_inventory_value_usd:,.2f}$ değerinde)",
            f"<b>Toplam K/Z:</b> <span style='color:{pnl_color};'>{result.total_pnl_usd:+,.4f}$</span> &nbsp; "
            f"<b>Toplam Komisyon:</b> {result.fees_usd:,.4f}$ "
            f"({result.leverage:g}x kaldıraç, %{result.fee_rate * 100:g} komisyon, "
            f"%{result.maintenance_margin_rate * 100:g} bakım marjini oranıyla)",
            f"<b>Grid Aralığı:</b> {result.grid_levels[0]:,.6f} - {result.grid_levels[-1]:,.6f} "
            f"({len(result.grid_levels) - 1} grid) &nbsp; "
            f"<b>Başlangıç/Bitiş Fiyatı:</b> {result.start_price:,.6f} / {result.end_price:,.6f}",
        ]
        if result.breached_lower:
            lines.append(
                "<span style='color:#c62828;'>Fiyat, aralık boyunca en az bir kez ALT sınırın altına indi "
                "— bu yöndeki AL emirleri tükendi.</span>"
            )
        if result.breached_upper:
            lines.append(
                "<span style='color:#c62828;'>Fiyat, aralık boyunca en az bir kez ÜST sınırın üstüne çıktı "
                "— bu yöndeki SAT emirleri tükendi.</span>"
            )
        self.backtest_summary_label.setText("<br>".join(lines))

    def _render_grid_trades(self, result: GridBacktestResult) -> None:
        self.grid_trade_table.setRowCount(len(result.trades))
        for i, trade in enumerate(result.trades):
            self.grid_trade_table.setItem(i, 0, QTableWidgetItem(_format_ms(trade.buy_time_ms)))
            self.grid_trade_table.setItem(i, 1, QTableWidgetItem(f"{trade.buy_price:,.6f}"))
            self.grid_trade_table.setItem(i, 2, QTableWidgetItem(_format_ms(trade.sell_time_ms)))
            self.grid_trade_table.setItem(i, 3, QTableWidgetItem(f"{trade.sell_price:,.6f}"))
            self.grid_trade_table.setItem(i, 4, QTableWidgetItem(f"{trade.quantity:,.6f}"))
            self.grid_trade_table.setItem(i, 5, QTableWidgetItem(f"{trade.net_pnl_usd:+,.4f}"))


def _format_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")


def _format_chart_title(label: str, candles: list[Candle]) -> str:
    if not candles:
        return label
    return f"{label} ({_format_ms(candles[0].open_time_ms)} - {_format_ms(candles[-1].open_time_ms)})"
