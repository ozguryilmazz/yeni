import sys

from PySide6.QtWidgets import QApplication

from app.database import init_db
from app.ui.login_window import LoginWindow


def main() -> None:
    init_db()
    application = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
