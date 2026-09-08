from datetime import datetime

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.whale_tracker.models import TrapScoreResult
from app.whale_tracker.qt_bridge import WhaleTrackerThread

MODULE_LABELS = {
    "open_interest": "Open Interest",
    "funding_rate": "Funding Rate",
    "volume": "Hacim Patlaması",
    "liquidation": "Likidasyon",
    "orderbook": "Emir Defteri",
    "REST": "Veri",
}


class WhaleTrapTab(QWidget):
    """'Tuzak Skoru' sekmesi: tek bir sembolü seçip Open Interest, Funding Rate,
    anlık likidasyon ve emir defteri dengesizliğini birleştiren 0-100 arası bir
    skoru canlı izler. Teknik indikatör kullanmaz; bilgi amaçlıdır, otomatik
    işlem açmaz."""

    def __init__(self) -> None:
        super().__init__()
        self._thread: WhaleTrackerThread | None = None

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sembol"))
        self.symbol_input = QLineEdit("BTCUSDT")
        controls.addWidget(self.symbol_input)

        self.start_button = QPushButton("İzlemeyi Başlat")
        self.start_button.clicked.connect(self._handle_start)
        controls.addWidget(self.start_button)

        self.stop_button = QPushButton("Durdur")
        self.stop_button.clicked.connect(self._handle_stop)
        self.stop_button.setEnabled(False)
        controls.addWidget(self.stop_button)
        controls.addStretch()
        layout.addLayout(controls)

        hint = QLabel(
            "Teknik indikatör (RSI/MACD/MA) kullanmaz. Open Interest sıçraması, Funding "
            "Rate anomalisi, anlık likidasyon patlamaları, emir defteri dengesizliği ve "
            "hacim verisini birleştirerek 0-100 arası bir 'Tuzak Skoru' üretir. Sadece "
            "bilgi amaçlıdır; otomatik işlem açmaz."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        score_row = QHBoxLayout()
        score_row.addWidget(QLabel("<b>Tuzak Skoru:</b>"))
        self.score_label = QLabel("—")
        self.score_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        score_row.addWidget(self.score_label)
        self.direction_label = QLabel("")
        self.direction_label.setStyleSheet("font-size: 16px;")
        score_row.addWidget(self.direction_label)
        score_row.addStretch()
        layout.addLayout(score_row)

        self.score_bar = QProgressBar()
        self.score_bar.setRange(0, 100)
        layout.addWidget(self.score_bar)

        layout.addWidget(QLabel("Modül Detayları"))
        self.breakdown_table = QTableWidget(0, 3)
        self.breakdown_table.setHorizontalHeaderLabels(["Modül", "Tetiklendi", "Mesaj"])
        self.breakdown_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.breakdown_table)

        layout.addWidget(QLabel("Olay Günlüğü"))
        self.event_table = QTableWidget(0, 3)
        self.event_table.setHorizontalHeaderLabels(["Zaman", "Modül", "Mesaj"])
        self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.event_table)

    def _handle_start(self) -> None:
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "İzleme", "Bir sembol girin (ör. BTCUSDT)")
            return

        self._thread = WhaleTrackerThread(symbol)
        self._thread.score_updated.connect(self._on_score_updated)
        self._thread.event_logged.connect(self._on_event_logged)
        self._thread.error.connect(self._on_error)
        self._thread.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.symbol_input.setEnabled(False)

    def _handle_stop(self) -> None:
        if self._thread is not None:
            self._thread.stop()
            self._thread.wait(5000)
            self._thread = None

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.symbol_input.setEnabled(True)
        self.score_label.setText("—")
        self.score_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.direction_label.setText("")
        self.score_bar.setValue(0)

    def stop_tracking(self) -> None:
        """Ana pencere kapanırken (closeEvent) thread'in düzgün sonlanması için
        çağrılır; izleme zaten kapalıysa bir şey yapmaz."""
        if self._thread is not None:
            self._handle_stop()

    def _on_score_updated(self, result: TrapScoreResult) -> None:
        self.score_label.setText(f"{result.score:.0f}")
        self.direction_label.setText(result.direction or "")
        self.score_bar.setValue(min(100, max(0, int(result.score))))

        color = {"LONG": "#2e7d32", "SHORT": "#c62828"}.get(result.direction, "#888888")
        self.score_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")
        self.direction_label.setStyleSheet(f"font-size: 16px; color: {color};")

        self.breakdown_table.setRowCount(len(result.signals))
        for i, (name, signal) in enumerate(result.signals.items()):
            self.breakdown_table.setItem(i, 0, QTableWidgetItem(MODULE_LABELS.get(name, name)))
            self.breakdown_table.setItem(i, 1, QTableWidgetItem("Evet" if signal.triggered else "Hayır"))
            self.breakdown_table.setItem(i, 2, QTableWidgetItem(signal.message))

    def _on_event_logged(self, event: dict) -> None:
        module = event.get("module", "")
        self.event_table.insertRow(0)
        self.event_table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self.event_table.setItem(0, 1, QTableWidgetItem(MODULE_LABELS.get(module, module)))
        self.event_table.setItem(0, 2, QTableWidgetItem(event.get("message", "")))

        max_rows = 200
        while self.event_table.rowCount() > max_rows:
            self.event_table.removeRow(self.event_table.rowCount() - 1)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "İzleme hatası", message)
        self._handle_stop()
