from PySide6.QtGui import QGuiApplication

from app.ui.whale_tracker_tab import WhaleTrapTab


def test_paste_button_fills_symbol_input_from_clipboard(qapp):
    QGuiApplication.clipboard().setText("ethusdt")
    tab = WhaleTrapTab()

    tab._handle_paste()

    assert tab.symbol_input.text() == "ETHUSDT"


def test_paste_button_ignores_empty_clipboard(qapp):
    QGuiApplication.clipboard().setText("")
    tab = WhaleTrapTab()
    tab.symbol_input.setText("BTCUSDT")

    tab._handle_paste()

    assert tab.symbol_input.text() == "BTCUSDT"
