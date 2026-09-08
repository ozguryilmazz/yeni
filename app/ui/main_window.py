from uuid import UUID

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from app.ui.market_tab import MarketTab
from app.ui.transfers_tab import TransfersTab


class MainWindow(QMainWindow):
    def __init__(self, user_id: UUID, user_email: str) -> None:
        super().__init__()
        self.user_id = user_id
        self.user_email = user_email

        self.setWindowTitle("Binance Cüzdan Yöneticisi")
        self.resize(1000, 780)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_header())

        self.market_tab = MarketTab()
        self.transfers_tab = TransfersTab(user_id)

        tabs = QTabWidget()
        tabs.addTab(self.market_tab, "Piyasa")
        tabs.addTab(self.transfers_tab, "Transferler")
        layout.addWidget(tabs)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addWidget(QLabel(f"Giriş yapan: {self.user_email}"))
        header.addStretch()
        return header
