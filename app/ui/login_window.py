from PySide6.QtWidgets import (
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.database import session_scope
from app.repository import DuplicateEmailError, InvalidCredentialsError, authenticate_user, register_user


class LoginWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Binance Cüzdan Yöneticisi - Giriş")
        self.resize(380, 240)
        self.main_window = None

        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), "Giriş Yap")
        tabs.addTab(self._build_register_tab(), "Kayıt Ol")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def _build_login_tab(self) -> QWidget:
        widget = QWidget()
        self.login_email = QLineEdit()
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("E-posta", self.login_email)
        form.addRow("Şifre", self.login_password)

        button = QPushButton("Giriş Yap")
        button.clicked.connect(self._handle_login)

        layout = QVBoxLayout(widget)
        layout.addLayout(form)
        layout.addWidget(button)
        return widget

    def _build_register_tab(self) -> QWidget:
        widget = QWidget()
        self.register_email = QLineEdit()
        self.register_password = QLineEdit()
        self.register_password.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("E-posta", self.register_email)
        form.addRow("Şifre (en az 8 karakter)", self.register_password)

        button = QPushButton("Kayıt Ol")
        button.clicked.connect(self._handle_register)

        layout = QVBoxLayout(widget)
        layout.addLayout(form)
        layout.addWidget(button)
        return widget

    def _handle_login(self) -> None:
        email = self.login_email.text().strip()
        password = self.login_password.text()
        try:
            with session_scope() as db:
                user = authenticate_user(db, email, password)
                user_id, user_email = user.id, user.email
        except InvalidCredentialsError as exc:
            QMessageBox.warning(self, "Giriş başarısız", str(exc))
            return
        self._open_main_window(user_id, user_email)

    def _handle_register(self) -> None:
        email = self.register_email.text().strip()
        password = self.register_password.text()
        if len(password) < 8:
            QMessageBox.warning(self, "Kayıt başarısız", "Şifre en az 8 karakter olmalı")
            return
        try:
            with session_scope() as db:
                user = register_user(db, email, password)
                user_id, user_email = user.id, user.email
        except DuplicateEmailError as exc:
            QMessageBox.warning(self, "Kayıt başarısız", str(exc))
            return
        self._open_main_window(user_id, user_email)

    def _open_main_window(self, user_id, user_email: str) -> None:
        from app.ui.main_window import MainWindow

        self.main_window = MainWindow(user_id, user_email)
        self.main_window.show()
        self.close()
