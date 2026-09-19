from datetime import datetime
from uuid import UUID

from PySide6.QtCore import QLocale
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import repository
from app.crypto import decrypt_secret
from app.database import session_scope
from app.live_trading.engine import RiskParams
from app.live_trading.qt_bridge import LiveTradingThread
from app.live_trading.repository import list_live_trades, record_trade_closed, record_trade_opened
from app.position_sizing import LEVERAGE, MARGIN_USD, SL_FEE_MULT, TP_FEE_MULT
from app.strategies.registry import DEFAULT_STRATEGY_NAME, STRATEGIES, get_strategy

INTERVAL_LABELS = {"1m": "1 Dakika", "5m": "5 Dakika", "15m": "15 Dakika", "1h": "1 Saat"}
STATUS_LABELS = {
    "OPEN": "Açık",
    "CLOSED_TP": "Kapandı (TP)",
    "CLOSED_SL": "Kapandı (SL)",
    "CLOSED_TIME": "Kapandı (Zaman Aşımı)",
    "CLOSED_UNKNOWN": "Kapandı (?)",
    "FAILED": "Başarısız",
}


class LiveTradingTab(QWidget):
    """'Canlı İşlem' sekmesi: seçilen strateji ve risk parametreleriyle
    Binance Futures hesabında GERÇEK PARA ile otomatik pozisyon açar/kapar.
    SL/TP borsa tarafında gerçek emirler olarak açılır. Backtest sekmesinin
    aksine bu sekme simülasyon YAPMAZ — burada gönderilen her emir gerçektir."""

    def __init__(self, user_id: UUID) -> None:
        super().__init__()
        self.user_id = user_id
        self._thread: LiveTradingThread | None = None
        self._credential_ids: list[UUID] = []
        self._current_credential_id: UUID | None = None
        self._current_trade_db_id = None
        self._active_strategy_name = DEFAULT_STRATEGY_NAME
        self._active_symbol = ""
        self._active_interval = "5m"
        self._active_mode = "auto"
        self._active_risk = RiskParams(MARGIN_USD, LEVERAGE, SL_FEE_MULT, TP_FEE_MULT)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_warning_banner())
        layout.addWidget(self._build_config_box())
        layout.addWidget(self._build_risk_box())
        layout.addLayout(self._build_controls_row())

        layout.addWidget(QLabel("Durum Günlüğü"))
        self.log_table = QTableWidget(0, 2)
        self.log_table.setHorizontalHeaderLabels(["Zaman", "Mesaj"])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.log_table)

        layout.addWidget(QLabel("İşlem Geçmişi (gerçek işlemler)"))
        self.history_table = QTableWidget(0, 9)
        self.history_table.setHorizontalHeaderLabels(
            ["Açılış", "Strateji", "Sembol", "Yön", "Giriş", "SL", "TP", "Miktar", "Durum"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history_table)

        self.refresh_credentials()
        self.refresh_history()

    # ---- kurulum ---------------------------------------------------------

    def _build_warning_banner(self) -> QLabel:
        banner = QLabel(
            "⚠️ GERÇEK PARA — Bu sekme Binance Futures hesabınızda gerçek parayla otomatik "
            "işlem açar/kapar. Test veya simülasyon değildir; Backtest sekmesinin aksine burada "
            "gönderilen her emir gerçek bir borsa işlemidir. SL/TP borsa tarafında gerçek "
            "STOP_MARKET/TAKE_PROFIT_MARKET emirleri olarak açılır — bu, uygulama kapansa/çökse "
            "bile açık pozisyonun korunmasını sağlar, ama 'Durdur' butonu açık pozisyonu KAPATMAZ, "
            "sadece yeni sinyal aramayı durdurur."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background-color: #c62828; color: white; padding: 8px; font-weight: bold; border-radius: 4px;"
        )
        return banner

    def _build_config_box(self) -> QGroupBox:
        box = QGroupBox("Ayarlar")
        row = QHBoxLayout(box)

        row.addWidget(QLabel("Hesap"))
        self.credential_combo = QComboBox()
        self.credential_combo.currentIndexChanged.connect(self._on_credential_combo_changed)
        row.addWidget(self.credential_combo)

        row.addWidget(QLabel("Strateji"))
        self.strategy_combo = QComboBox()
        for name in STRATEGIES:
            self.strategy_combo.addItem(name, name)
        self.strategy_combo.setCurrentIndex(self.strategy_combo.findData(DEFAULT_STRATEGY_NAME))
        row.addWidget(self.strategy_combo)

        row.addWidget(QLabel("Sembol"))
        self.symbol_input = QLineEdit("BTCUSDT")
        row.addWidget(self.symbol_input)
        self.paste_button = QPushButton("Yapıştır")
        self.paste_button.clicked.connect(self._handle_paste)
        row.addWidget(self.paste_button)

        row.addWidget(QLabel("Zaman Dilimi"))
        self.interval_combo = QComboBox()
        for interval, label in INTERVAL_LABELS.items():
            self.interval_combo.addItem(label, interval)
        row.addWidget(self.interval_combo)
        return box

    def _build_risk_box(self) -> QGroupBox:
        box = QGroupBox("Risk Parametreleri (canlıya geçmeden önce manuel girilir)")
        row = QHBoxLayout(box)

        row.addWidget(QLabel("Margin ($)"))
        self.margin_input = QDoubleSpinBox()
        self.margin_input.setDecimals(2)
        self.margin_input.setRange(0.01, 1_000_000)
        self.margin_input.setValue(MARGIN_USD)
        self.margin_input.setLocale(QLocale(QLocale.Language.C))
        row.addWidget(self.margin_input)

        row.addWidget(QLabel("Kaldıraç (x)"))
        self.leverage_input = QSpinBox()
        self.leverage_input.setRange(1, 125)
        self.leverage_input.setValue(LEVERAGE)
        row.addWidget(self.leverage_input)

        row.addWidget(QLabel("SL Çarpanı"))
        self.sl_mult_input = QDoubleSpinBox()
        self.sl_mult_input.setDecimals(2)
        self.sl_mult_input.setRange(0.1, 1000)
        self.sl_mult_input.setValue(SL_FEE_MULT)
        self.sl_mult_input.setLocale(QLocale(QLocale.Language.C))
        row.addWidget(self.sl_mult_input)

        row.addWidget(QLabel("TP Çarpanı"))
        self.tp_mult_input = QDoubleSpinBox()
        self.tp_mult_input.setDecimals(2)
        self.tp_mult_input.setRange(0.1, 1000)
        self.tp_mult_input.setValue(TP_FEE_MULT)
        self.tp_mult_input.setLocale(QLocale(QLocale.Language.C))
        row.addWidget(self.tp_mult_input)
        return box

    def _build_controls_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.start_auto_button = QPushButton("Bot Başlat")
        self.start_auto_button.setToolTip("Sinyal oluşunca hiçbir onay beklemeden anında gerçek emir gönderir.")
        self.start_auto_button.clicked.connect(lambda: self._handle_start("auto"))
        row.addWidget(self.start_auto_button)

        self.start_confirm_button = QPushButton("Bot Onaylı Başlat")
        self.start_confirm_button.setToolTip("Sinyal oluşunca emir göndermeden önce onayınızı bekler.")
        self.start_confirm_button.clicked.connect(lambda: self._handle_start("confirm"))
        row.addWidget(self.start_confirm_button)

        self.stop_button = QPushButton("Durdur")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._handle_stop)
        row.addWidget(self.stop_button)
        row.addStretch()
        return row

    # ---- credential ---------------------------------------------------------

    def refresh_credentials(self) -> None:
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            credentials = repository.list_credentials(db, user)

        self.credential_combo.blockSignals(True)
        self.credential_combo.clear()
        self._credential_ids = []
        for credential in credentials:
            self.credential_combo.addItem(credential.label, credential.id)
            self._credential_ids.append(credential.id)
        self.credential_combo.blockSignals(False)

        self._current_credential_id = self._credential_ids[0] if self._credential_ids else None
        if self._credential_ids:
            self.credential_combo.setCurrentIndex(0)

    def _on_credential_combo_changed(self, index: int) -> None:
        if 0 <= index < len(self._credential_ids):
            self._current_credential_id = self._credential_ids[index]

    def _handle_paste(self) -> None:
        text = QGuiApplication.clipboard().text().strip().upper()
        if text:
            self.symbol_input.setText(text)

    # ---- başlat/durdur ---------------------------------------------------

    def _handle_start(self, mode: str) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "Canlı İşlem", "Bot zaten çalışıyor.")
            return
        if self._current_credential_id is None:
            QMessageBox.warning(
                self, "Canlı İşlem", "Önce Transferler sekmesinden bir Binance hesabı bağlayın."
            )
            return
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Canlı İşlem", "Bir sembol girin (ör. BTCUSDT)")
            return

        mode_label = "Onaylı" if mode == "confirm" else "Tam Otomatik"
        answer = QMessageBox.warning(
            self,
            "GERÇEK PARA İLE İŞLEM BAŞLATILACAK",
            f"{symbol} üzerinde {mode_label} modda GERÇEK PARA ile otomatik işlem başlatılacak.\n\n"
            f"Strateji: {self.strategy_combo.currentData()}\n"
            f"Margin: {self.margin_input.value():.2f}$   Kaldıraç: {self.leverage_input.value()}x\n"
            f"SL çarpanı: {self.sl_mult_input.value():.2f}   TP çarpanı: {self.tp_mult_input.value():.2f}\n\n"
            "Bu işlem gerçek bakiyenizi etkiler. Devam etmek istediğinizden emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            with session_scope() as db:
                user = repository.get_user_by_id(db, self.user_id)
                credential = repository.get_credential(db, user, self._current_credential_id)
                api_key = decrypt_secret(credential.encrypted_api_key)
                api_secret = decrypt_secret(credential.encrypted_api_secret)
        except repository.CredentialNotFoundError as exc:
            QMessageBox.warning(self, "Canlı İşlem", str(exc))
            return

        strategy_name = self.strategy_combo.currentData()
        strategy = get_strategy(strategy_name)
        interval = self.interval_combo.currentData()
        risk = RiskParams(
            margin_usd=self.margin_input.value(),
            leverage=self.leverage_input.value(),
            sl_fee_mult=self.sl_mult_input.value(),
            tp_fee_mult=self.tp_mult_input.value(),
        )

        self._active_strategy_name = strategy_name
        self._active_symbol = symbol
        self._active_interval = interval
        self._active_mode = mode
        self._active_risk = risk

        self._thread = LiveTradingThread(api_key, api_secret, symbol, interval, strategy, risk, mode)
        self._thread.status.connect(self._on_status)
        self._thread.signal_detected.connect(self._on_signal_detected)
        self._thread.confirmation_needed.connect(self._on_confirmation_needed)
        self._thread.order_placed.connect(self._on_order_placed)
        self._thread.position_closed.connect(self._on_position_closed)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

        self._set_running_ui(True)
        self._log(f"Bot başlatıldı ({mode_label} mod) — {symbol} {interval} — {strategy_name}")

    def _handle_stop(self) -> None:
        if self._thread is None:
            return
        self._thread.stop()
        self._thread.wait(5000)
        self._thread = None
        self._set_running_ui(False)
        self._log("Bot durduruldu. Açık pozisyon varsa borsadaki SL/TP emirleri korumaya devam ediyor.")

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._set_running_ui(False)

    def _set_running_ui(self, running: bool) -> None:
        self.start_auto_button.setEnabled(not running)
        self.start_confirm_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.credential_combo.setEnabled(not running)
        self.strategy_combo.setEnabled(not running)
        self.symbol_input.setEnabled(not running)
        self.interval_combo.setEnabled(not running)
        self.margin_input.setEnabled(not running)
        self.leverage_input.setEnabled(not running)
        self.sl_mult_input.setEnabled(not running)
        self.tp_mult_input.setEnabled(not running)

    def stop_tracking(self) -> None:
        """Ana pencere kapanırken (closeEvent) thread'in düzgün sonlanması için
        çağrılır; bot zaten durduysa bir şey yapmaz. Açık pozisyonu KAPATMAZ."""
        if self._thread is not None:
            self._handle_stop()

    # ---- motor olayları ---------------------------------------------------

    def _on_status(self, message: str) -> None:
        self._log(message)

    def _on_signal_detected(self, side: str, price: float) -> None:
        self._log(f"SİNYAL: {side} @ {price}")

    def _on_confirmation_needed(self, side: str, price: float, stop_loss: float, take_profit: float) -> None:
        self._log(f"ONAY BEKLENİYOR: {side} @ {price} (SL={stop_loss:.6f} TP={take_profit:.6f})")
        answer = QMessageBox.question(
            self,
            "Sinyal Onayı — GERÇEK PARA",
            f"{self._active_symbol} için {side} sinyali oluştu.\n\n"
            f"Fiyat: {price}\nSL: {stop_loss:.6f}\nTP: {take_profit:.6f}\n\n"
            "Bu işlemi GERÇEK PARA ile açmak istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if self._thread is None:
            return
        if answer == QMessageBox.StandardButton.Yes:
            self._thread.confirm_pending_signal()
        else:
            self._thread.reject_pending_signal()
            self._log("Sinyal reddedildi, gerçek emir gönderilmedi.")

    def _on_order_placed(self, trade: dict) -> None:
        self._log(
            f"POZİSYON AÇILDI: {trade['side']} {trade['quantity']} {self._active_symbol} "
            f"@ {trade['entry_price']} (SL={trade['stop_loss']} TP={trade['take_profit']})"
        )
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            record = record_trade_opened(
                db,
                user_id=user.id,
                credential_id=self._current_credential_id,
                strategy_name=self._active_strategy_name,
                symbol=self._active_symbol,
                interval=self._active_interval,
                mode=self._active_mode,
                side=trade["side"],
                margin_usd=self._active_risk.margin_usd,
                leverage=self._active_risk.leverage,
                sl_fee_mult=self._active_risk.sl_fee_mult,
                tp_fee_mult=self._active_risk.tp_fee_mult,
                entry_price=trade["entry_price"],
                stop_loss_price=trade["stop_loss"],
                take_profit_price=trade["take_profit"],
                quantity=trade["quantity"],
                entry_order_id=trade["entry_order_id"],
                sl_order_id=trade["sl_order_id"],
                tp_order_id=trade["tp_order_id"],
            )
            self._current_trade_db_id = record.id
        self.refresh_history()

    def _on_position_closed(self, exit_reason: str) -> None:
        self._log(f"POZİSYON KAPANDI: {exit_reason}")
        if self._current_trade_db_id is not None:
            with session_scope() as db:
                record_trade_closed(db, self._current_trade_db_id, exit_reason)
            self._current_trade_db_id = None
        self.refresh_history()

    def _on_error(self, message: str) -> None:
        self._log(f"HATA: {message}")
        QMessageBox.warning(self, "Canlı İşlem Hatası", message)

    def _log(self, message: str) -> None:
        self.log_table.insertRow(0)
        self.log_table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self.log_table.setItem(0, 1, QTableWidgetItem(message))
        max_rows = 300
        while self.log_table.rowCount() > max_rows:
            self.log_table.removeRow(self.log_table.rowCount() - 1)

    # ---- geçmiş -------------------------------------------------------------

    def refresh_history(self) -> None:
        with session_scope() as db:
            user = repository.get_user_by_id(db, self.user_id)
            trades = list_live_trades(db, user.id)
            rows = [
                (
                    t.opened_at.strftime("%Y-%m-%d %H:%M"),
                    t.strategy_name,
                    t.symbol,
                    t.side,
                    str(t.entry_price),
                    str(t.stop_loss_price),
                    str(t.take_profit_price),
                    str(t.quantity),
                    STATUS_LABELS.get(t.status, t.status),
                )
                for t in trades
            ]

        self.history_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                self.history_table.setItem(i, j, QTableWidgetItem(value))
