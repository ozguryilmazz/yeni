from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.workers import LoadMarketOverviewWorker

PERIOD_LABELS = {"1h": "Son 1 Saat", "4h": "Son 4 Saat", "24h": "Son 24 Saat"}


class NumericTableWidgetItem(QTableWidgetItem):
    """Görünen metin biçimlendirilmiş olsa da (ör. '1,234.56'), sütun sıralaması
    sayısal değere göre yapılsın diye QTableWidgetItem'ın varsayılan string
    karşılaştırmasını eziyoruz."""

    def __init__(self, value: float, text: str) -> None:
        super().__init__(text)
        self._value = value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, NumericTableWidgetItem):
            return self._value < other._value
        return super().__lt__(other)


class MarketTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: LoadMarketOverviewWorker | None = None

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Futures — Hacme Göre Coinler</b>"))
        header.addStretch()
        header.addWidget(QLabel("Dönem"))
        self.period_combo = QComboBox()
        for period, label in PERIOD_LABELS.items():
            self.period_combo.addItem(label, period)
        self.period_combo.setCurrentIndex(2)  # 24h varsayılan
        self.period_combo.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.period_combo)

        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        hint = QLabel(
            "Sadece USDT-M perpetual futures'ta işlem gören coinler listelenir. "
            "Sütun başlıklarına tıklayarak sıralamayı değiştirebilirsiniz."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Sembol", "Hacim (USDT)", "Değişim %"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        period = self.period_combo.currentData()
        self.refresh_button.setEnabled(False)
        self.period_combo.setEnabled(False)
        self._worker = LoadMarketOverviewWorker(period)
        self._worker.success.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, overview: list[dict]) -> None:
        self.refresh_button.setEnabled(True)
        self.period_combo.setEnabled(True)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(overview))
        for i, row in enumerate(overview):
            self.table.setItem(i, 0, QTableWidgetItem(row["symbol"]))
            volume = row["quote_volume"]
            self.table.setItem(i, 1, NumericTableWidgetItem(volume, f"{volume:,.2f}"))

            change = row.get("price_change_percent", 0.0)
            change_item = NumericTableWidgetItem(change, f"{change:+.2f}%")
            change_item.setForeground(QBrush(QColor("#2e7d32" if change >= 0 else "#c62828")))
            self.table.setItem(i, 2, change_item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)

    def _on_error(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.period_combo.setEnabled(True)
        QMessageBox.warning(self, "Piyasa verisi alınamadı", message)
