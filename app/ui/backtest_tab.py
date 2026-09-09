from datetime import datetime, timezone

from PySide6.QtCore import QDateTime
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backtest.engine import BacktestResult, Trade
from app.backtest.service import BacktestComparison
from app.workers import RunBacktestWorker

EXIT_REASON_LABELS = {"TP": "TP", "SL": "SL", "EOD": "Veri Sonu"}


def _format_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")


class BacktestTab(QWidget):
    """'Backtest' sekmesi: seçilen coin ve tarih aralığında 5 dakikalık mumlar
    üzerinde 'Esnetilmiş 5D Scalp Stratejisi'ni (EMA9/21/100 + ATR14) simüle eder.
    Aynı veri üzerinde stratejinin ürettiği sinyalin TERSİ de hesaplanıp yan yana
    gösterilir. Gerçek işlem açmaz; sadece geçmiş veri üzerinde ne olurdu'yu
    gösterir."""

    def __init__(self) -> None:
        super().__init__()
        self._worker: RunBacktestWorker | None = None
        self._comparison: BacktestComparison | None = None

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sembol"))
        self.symbol_input = QLineEdit("BTCUSDT")
        self.symbol_input.setPlaceholderText("BTCUSDT")
        controls.addWidget(self.symbol_input)

        self.paste_button = QPushButton("Yapıştır")
        self.paste_button.clicked.connect(self._handle_paste)
        controls.addWidget(self.paste_button)

        controls.addWidget(QLabel("Başlangıç"))
        self.start_input = QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(-7))
        self.start_input.setCalendarPopup(True)
        self.start_input.setDisplayFormat("dd.MM.yyyy HH:mm")
        controls.addWidget(self.start_input)

        controls.addWidget(QLabel("Bitiş"))
        self.end_input = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        self.end_input.setCalendarPopup(True)
        self.end_input.setDisplayFormat("dd.MM.yyyy HH:mm")
        controls.addWidget(self.end_input)

        self.run_button = QPushButton("Backtest Çalıştır")
        self.run_button.clicked.connect(self._handle_run)
        controls.addWidget(self.run_button)
        controls.addStretch()
        layout.addLayout(controls)

        hint = QLabel(
            "5 dakikalık mumlarda 'Esnetilmiş 5D Scalp' stratejisi: Fiyat EMA100 üzerindeyse "
            "LONG, altındaysa SHORT yönü aranır; fiyat EMA9/EMA21 bölgesine ATR14'ün ±0.5 katı "
            "toleransla çekildiğinde giriş yapılır. Her işlem 2$ margin / 5x kaldıraç (10$ "
            "pozisyon büyüklüğü) ile 100$ bakiye üzerinden simüle edilir; açılış ve kapanışta "
            "%0.05 taker komisyonu uygulanır. SL/TP, o işlemin toplam (giriş+çıkış) komisyon "
            "maliyetinin katları olarak hesaplanır: SL 4 katı, TP 2 katı uzaktadır — yani her "
            "kazanan işlem en az 2 kaybeden işlemin komisyon+zarar maliyetini karşılamalıdır. "
            "Tarihler UTC (Binance sunucu saati) olarak yorumlanır. Aynı "
            "veri üzerinde stratejinin TERSİ (LONG↔SHORT) de otomatik hesaplanıp aşağıda "
            "karşılaştırma için gösterilir — SL/TP ters yönde entry'den yeniden hesaplanır, "
            "orijinal işlemin seviyeleriyle basitçe yer değiştirmez. Bu sekme sadece geçmiş "
            "veri üzerinde simülasyon yapar, gerçek işlem açmaz."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        summaries = QHBoxLayout()
        normal_box = QVBoxLayout()
        normal_box.addWidget(QLabel("<b>Normal Yön (strateji sinyali)</b>"))
        self.normal_summary_label = QLabel("—")
        self.normal_summary_label.setWordWrap(True)
        normal_box.addWidget(self.normal_summary_label)
        summaries.addLayout(normal_box)

        reversed_box = QVBoxLayout()
        reversed_box.addWidget(QLabel("<b>Ters Yön (sinyalin tersi)</b>"))
        self.reversed_summary_label = QLabel("—")
        self.reversed_summary_label.setWordWrap(True)
        reversed_box.addWidget(self.reversed_summary_label)
        summaries.addLayout(reversed_box)
        layout.addLayout(summaries)

        table_header = QHBoxLayout()
        table_header.addWidget(QLabel("Gösterilen İşlem Listesi"))
        self.result_selector = QComboBox()
        self.result_selector.addItem("Normal Yön", "normal")
        self.result_selector.addItem("Ters Yön", "reversed")
        self.result_selector.currentIndexChanged.connect(self._on_result_selector_changed)
        table_header.addWidget(self.result_selector)
        table_header.addStretch()
        layout.addLayout(table_header)

        self.trade_table = QTableWidget(0, 10)
        self.trade_table.setHorizontalHeaderLabels(
            [
                "Yön",
                "Giriş Zamanı",
                "Giriş Fiyatı",
                "SL",
                "TP",
                "Çıkış Zamanı",
                "Çıkış Fiyatı",
                "Neden",
                "Net K/Z (USD)",
                "Bakiye (USD)",
            ]
        )
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.trade_table)

    def _handle_paste(self) -> None:
        text = QGuiApplication.clipboard().text().strip().upper()
        if text:
            self.symbol_input.setText(text)

    def _handle_run(self) -> None:
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Backtest", "Bir sembol girin (ör. BTCUSDT)")
            return

        start = self.start_input.dateTime().toPython().replace(tzinfo=timezone.utc)
        end = self.end_input.dateTime().toPython().replace(tzinfo=timezone.utc)
        if start >= end:
            QMessageBox.warning(self, "Backtest", "Başlangıç tarihi bitiş tarihinden önce olmalı")
            return

        self.run_button.setEnabled(False)
        self.normal_summary_label.setText("Çalışıyor…")
        self.reversed_summary_label.setText("Çalışıyor…")
        self.trade_table.setRowCount(0)

        self._worker = RunBacktestWorker(symbol, start, end)
        self._worker.success.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, comparison: BacktestComparison) -> None:
        self.run_button.setEnabled(True)
        self._comparison = comparison
        self._render_summary(self.normal_summary_label, comparison.normal)
        self._render_summary(self.reversed_summary_label, comparison.reversed)
        self._render_selected_trades()

    def _on_error(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self._comparison = None
        self.normal_summary_label.setText("—")
        self.reversed_summary_label.setText("—")
        QMessageBox.warning(self, "Backtest çalıştırılamadı", message)

    def _on_result_selector_changed(self) -> None:
        self._render_selected_trades()

    def _render_selected_trades(self) -> None:
        if self._comparison is None:
            return
        key = self.result_selector.currentData()
        result = self._comparison.reversed if key == "reversed" else self._comparison.normal
        self._render_trades(result.trades)

    def _render_summary(self, label: QLabel, result: BacktestResult) -> None:
        trades = result.trades
        total = len(trades)
        wins = [t for t in trades if t.net_pnl_usd > 0]
        losses = [t for t in trades if t.net_pnl_usd <= 0]
        win_rate = (len(wins) / total * 100) if total else 0.0
        net_pnl = result.ending_balance_usd - result.starting_balance_usd
        total_fees = sum(t.fees_usd for t in trades)

        pnl_color = "#2e7d32" if net_pnl >= 0 else "#c62828"
        lines = [
            f"<b>Toplam İşlem:</b> {total} &nbsp; "
            f"<b>Kazanan/Kaybeden:</b> {len(wins)}/{len(losses)} &nbsp; "
            f"<b>Kazanma Oranı:</b> {win_rate:.1f}%",
            f"<b>Başlangıç:</b> {result.starting_balance_usd:,.2f}$ &nbsp; "
            f"<b>Bitiş:</b> {result.ending_balance_usd:,.2f}$ &nbsp; "
            f"<b>Net K/Z:</b> "
            f"<span style='color:{pnl_color};'>{net_pnl:+,.2f}$</span>",
            f"<b>Toplam Komisyon:</b> {total_fees:,.2f}$",
        ]
        if result.stopped_early:
            lines.append(
                "<span style='color:#c62828;'>Bakiye 2$ margin'in altına düştüğü için "
                "aralığın sonuna kadar yeni pozisyon açılamadı.</span>"
            )
        label.setText("<br>".join(lines))

    def _render_trades(self, trades: list[Trade]) -> None:
        self.trade_table.setRowCount(len(trades))
        for i, trade in enumerate(trades):
            self.trade_table.setItem(i, 0, QTableWidgetItem(trade.side))
            self.trade_table.setItem(i, 1, QTableWidgetItem(_format_ms(trade.entry_time_ms)))
            self.trade_table.setItem(i, 2, QTableWidgetItem(f"{trade.entry_price:,.6f}"))
            self.trade_table.setItem(i, 3, QTableWidgetItem(f"{trade.stop_loss:,.6f}"))
            self.trade_table.setItem(i, 4, QTableWidgetItem(f"{trade.take_profit:,.6f}"))
            self.trade_table.setItem(i, 5, QTableWidgetItem(_format_ms(trade.exit_time_ms)))
            self.trade_table.setItem(i, 6, QTableWidgetItem(f"{trade.exit_price:,.6f}"))
            self.trade_table.setItem(i, 7, QTableWidgetItem(EXIT_REASON_LABELS.get(trade.exit_reason, trade.exit_reason)))

            pnl_item = QTableWidgetItem(f"{trade.net_pnl_usd:+,.4f}")
            self.trade_table.setItem(i, 8, pnl_item)
            self.trade_table.setItem(i, 9, QTableWidgetItem(f"{trade.balance_after_usd:,.4f}"))
