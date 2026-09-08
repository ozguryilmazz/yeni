from decimal import Decimal
from uuid import UUID

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
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

from app import repository
from app.database import session_scope
from app.transfer_types import WalletType
from app.workers import ConnectCredentialWorker, CreateTransferWorker, LoadBalancesWorker

WALLET_LABELS = {
    WalletType.SPOT: "Spot",
    WalletType.USDM_FUTURES: "Futures (USDⓈ-M)",
    WalletType.FUNDING: "Funding",
}
STATUS_LABELS = {"PENDING": "Beklemede", "SUCCESS": "Başarılı", "FAILED": "Başarısız"}


class ConnectCredentialDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Binance Hesabı Bağla")

        self.label_input = QLineEdit("default")
        self.api_key_input = QLineEdit()
        self.api_secret_input = QLineEdit()
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)

        hint = QLabel(
            "Sadece 'Enable Reading' (ve gerekirse Spot/Futures trading) izni açık bir\n"
            "API key kullanın. Withdrawal (para çekme) izni açık key'ler reddedilir."
        )
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Etiket", self.label_input)
        form.addRow("API Key", self.api_key_input)
        form.addRow("API Secret", self.api_secret_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str]:
        return (
            self.label_input.text().strip() or "default",
            self.api_key_input.text().strip(),
            self.api_secret_input.text().strip(),
        )


class TransfersTab(QWidget):
    def __init__(self, user_id: UUID) -> None:
        super().__init__()
        self.user_id = user_id
        self.selected_credential_id: UUID | None = None
        self._credential_ids: list[UUID] = []
        self._connect_worker: ConnectCredentialWorker | None = None
        self._balances_worker: LoadBalancesWorker | None = None
        self._transfer_worker: CreateTransferWorker | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_credentials_section())
        layout.addWidget(self._build_wallet_section())
        layout.addWidget(self._build_transfer_section())

        self.refresh_credentials()
        self.refresh_transfers()

    # ---- credentials -------------------------------------------------------

    def _build_credentials_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("<b>Bağlı Binance Hesapları</b>"))

        self.credentials_table = QTableWidget(0, 3)
        self.credentials_table.setHorizontalHeaderLabels(["Etiket", "Withdrawal İzni", "Bağlanma Tarihi"])
        self.credentials_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.credentials_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.credentials_table.itemSelectionChanged.connect(self._on_credential_selected)
        layout.addWidget(self.credentials_table)

        buttons = QHBoxLayout()
        connect_button = QPushButton("Binance Hesabı Bağla")
        connect_button.clicked.connect(self._handle_connect_credential)
        remove_button = QPushButton("Seçileni Kaldır")
        remove_button.clicked.connect(self._handle_delete_credential)
        buttons.addWidget(connect_button)
        buttons.addWidget(remove_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        return box

    def refresh_credentials(self) -> None:
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            credentials = repository.list_credentials(db, user)
            rows = [(c.id, c.label, c.can_withdraw, c.created_at) for c in credentials]

        self._credential_ids = [row[0] for row in rows]
        self.credentials_table.setRowCount(len(rows))
        for i, (_cred_id, label, can_withdraw, created_at) in enumerate(rows):
            self.credentials_table.setItem(i, 0, QTableWidgetItem(label))
            self.credentials_table.setItem(i, 1, QTableWidgetItem("Açık ⚠️" if can_withdraw else "Kapalı"))
            self.credentials_table.setItem(i, 2, QTableWidgetItem(created_at.strftime("%Y-%m-%d %H:%M")))

        if rows:
            if self.selected_credential_id not in self._credential_ids:
                self.selected_credential_id = rows[0][0]
            self.credentials_table.selectRow(self._credential_ids.index(self.selected_credential_id))
        else:
            self.selected_credential_id = None

    def _on_credential_selected(self) -> None:
        row = self.credentials_table.currentRow()
        if 0 <= row < len(self._credential_ids):
            self.selected_credential_id = self._credential_ids[row]

    def _handle_connect_credential(self) -> None:
        dialog = ConnectCredentialDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        label, api_key, api_secret = dialog.values()
        if not api_key or not api_secret:
            QMessageBox.warning(self, "Bağlantı", "API key ve secret gerekli")
            return

        self._connect_worker = ConnectCredentialWorker(self.user_id, label, api_key, api_secret)
        self._connect_worker.success.connect(self._on_credential_connected)
        self._connect_worker.error.connect(self._on_credential_error)
        self._connect_worker.start()

    def _on_credential_connected(self, result: dict) -> None:
        QMessageBox.information(self, "Bağlandı", f"'{result['label']}' hesabı başarıyla bağlandı.")
        self.refresh_credentials()

    def _on_credential_error(self, message: str) -> None:
        QMessageBox.warning(self, "Bağlantı başarısız", message)

    def _handle_delete_credential(self) -> None:
        row = self.credentials_table.currentRow()
        if row < 0 or row >= len(self._credential_ids):
            QMessageBox.information(self, "Kaldır", "Kaldırmak için bir hesap seçin.")
            return

        credential_id = self._credential_ids[row]
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            repository.delete_credential(db, user, credential_id)
        self.refresh_credentials()
        if self.selected_credential_id is None:
            self._clear_balance_tables()

    # ---- wallet -------------------------------------------------------------

    def _build_wallet_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Bakiyeler</b>"))
        header.addStretch()
        self.refresh_balances_button = QPushButton("Yenile")
        self.refresh_balances_button.clicked.connect(self.refresh_balances)
        header.addWidget(self.refresh_balances_button)
        layout.addLayout(header)

        tables_layout = QHBoxLayout()
        self.spot_table = self._make_balance_table(["Coin", "Serbest", "Kilitli"])
        self.futures_table = self._make_balance_table(["Coin", "Cüzdan", "Kullanılabilir", "PNL"])
        self.funding_table = self._make_balance_table(["Coin", "Serbest", "Kilitli"])
        tables_layout.addWidget(self._wrap_table("Spot", self.spot_table))
        tables_layout.addWidget(self._wrap_table("Futures (USDⓈ-M)", self.futures_table))
        tables_layout.addWidget(self._wrap_table("Funding", self.funding_table))
        layout.addLayout(tables_layout)
        return box

    def _make_balance_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _wrap_table(self, title: str, table: QTableWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(title))
        layout.addWidget(table)
        return box

    def refresh_balances(self) -> None:
        if self.selected_credential_id is None:
            QMessageBox.information(self, "Bakiye", "Önce bir Binance hesabı bağlayın.")
            return

        self.refresh_balances_button.setEnabled(False)
        self._balances_worker = LoadBalancesWorker(self.user_id, self.selected_credential_id)
        self._balances_worker.success.connect(self._on_balances_loaded)
        self._balances_worker.error.connect(self._on_balances_error)
        self._balances_worker.start()

    def _on_balances_loaded(self, summary: dict) -> None:
        self.refresh_balances_button.setEnabled(True)
        self._fill_table(self.spot_table, summary["spot"], ["asset", "free", "locked"])
        self._fill_table(
            self.futures_table,
            summary["futures"],
            ["asset", "wallet_balance", "available_balance", "unrealized_profit"],
        )
        self._fill_table(self.funding_table, summary["funding"], ["asset", "free", "locked"])

    def _on_balances_error(self, message: str) -> None:
        self.refresh_balances_button.setEnabled(True)
        QMessageBox.warning(self, "Bakiye alınamadı", message)

    def _clear_balance_tables(self) -> None:
        for table in (self.spot_table, self.futures_table, self.funding_table):
            table.setRowCount(0)

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[dict], keys: list[str]) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, key in enumerate(keys):
                value = row[key]
                text = value if isinstance(value, str) else f"{value:.8f}".rstrip("0").rstrip(".")
                table.setItem(i, j, QTableWidgetItem(text or "0"))

    # ---- transfers -------------------------------------------------------

    def _build_transfer_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("<b>Cüzdanlar Arası Transfer</b>"))

        form = QHBoxLayout()
        self.from_wallet_combo = QComboBox()
        self.to_wallet_combo = QComboBox()
        for wallet in WalletType:
            self.from_wallet_combo.addItem(WALLET_LABELS[wallet], wallet)
            self.to_wallet_combo.addItem(WALLET_LABELS[wallet], wallet)
        self.to_wallet_combo.setCurrentIndex(1)

        self.asset_input = QLineEdit("USDT")
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setDecimals(8)
        self.amount_input.setMaximum(1_000_000_000)
        # Sistem yereli (ör. Türkçe Windows) ondalık ayracı olarak "," bekleyebilir;
        # bu widget her zaman "." ile çalışsın diye locale sabitleniyor (aksi halde
        # "0.04" gibi bir değer yanlış ayrıştırılıp farklı bir miktara dönüşebiliyor).
        self.amount_input.setLocale(QLocale(QLocale.Language.C))

        self.transfer_button = QPushButton("Transfer Et")
        self.transfer_button.clicked.connect(self._handle_transfer)

        form.addWidget(QLabel("Kaynak"))
        form.addWidget(self.from_wallet_combo)
        form.addWidget(QLabel("Hedef"))
        form.addWidget(self.to_wallet_combo)
        form.addWidget(QLabel("Coin"))
        form.addWidget(self.asset_input)
        form.addWidget(QLabel("Miktar"))
        form.addWidget(self.amount_input)
        form.addWidget(self.transfer_button)
        layout.addLayout(form)

        layout.addWidget(QLabel("Transfer Geçmişi"))
        self.transfers_table = QTableWidget(0, 5)
        self.transfers_table.setHorizontalHeaderLabels(["Tarih", "Coin", "Miktar", "Yön", "Durum"])
        self.transfers_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.transfers_table)
        return box

    def _handle_transfer(self) -> None:
        if self.selected_credential_id is None:
            QMessageBox.information(self, "Transfer", "Önce bir Binance hesabı bağlayın.")
            return

        # PySide6, str tabanlı bir Enum'u combo box itemData'sında saklarken QVariant
        # dönüşümü sırasında sessizce düz bir str'e indirgeyebiliyor; WalletType(...)
        # ile normalize ederek hem gerçek enum hem düz string dönmesi durumunu kapsıyoruz.
        from_wallet = WalletType(self.from_wallet_combo.currentData())
        to_wallet = WalletType(self.to_wallet_combo.currentData())
        if from_wallet == to_wallet:
            QMessageBox.warning(self, "Transfer", "Kaynak ve hedef cüzdan aynı olamaz")
            return

        asset = self.asset_input.text().strip().upper()
        amount = Decimal(str(self.amount_input.value()))
        if not asset or amount <= 0:
            QMessageBox.warning(self, "Transfer", "Geçerli bir coin ve miktar girin")
            return

        self.transfer_button.setEnabled(False)
        self._transfer_worker = CreateTransferWorker(
            self.user_id, self.selected_credential_id, asset, amount, from_wallet, to_wallet
        )
        self._transfer_worker.success.connect(self._on_transfer_success)
        self._transfer_worker.error.connect(self._on_transfer_error)
        self._transfer_worker.start()

    def _on_transfer_success(self, result: dict) -> None:
        self.transfer_button.setEnabled(True)
        QMessageBox.information(self, "Transfer", f"Transfer başarılı (tranId: {result['binance_tran_id']})")
        self.refresh_transfers()
        self.refresh_balances()

    def _on_transfer_error(self, message: str) -> None:
        self.transfer_button.setEnabled(True)
        QMessageBox.warning(self, "Transfer başarısız", message)
        self.refresh_transfers()

    def refresh_transfers(self) -> None:
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            transfers = repository.list_transfers(db, user)
            rows = [
                (t.created_at, t.asset, str(t.amount), t.from_wallet, t.to_wallet, t.status)
                for t in transfers
            ]

        self.transfers_table.setRowCount(len(rows))
        for i, (created_at, asset, amount, from_wallet, to_wallet, status) in enumerate(rows):
            direction = f"{WALLET_LABELS.get(WalletType(from_wallet), from_wallet)} → {WALLET_LABELS.get(WalletType(to_wallet), to_wallet)}"
            self.transfers_table.setItem(i, 0, QTableWidgetItem(created_at.strftime("%Y-%m-%d %H:%M")))
            self.transfers_table.setItem(i, 1, QTableWidgetItem(asset))
            self.transfers_table.setItem(i, 2, QTableWidgetItem(amount))
            self.transfers_table.setItem(i, 3, QTableWidgetItem(direction))
            self.transfers_table.setItem(i, 4, QTableWidgetItem(STATUS_LABELS.get(status, status)))
