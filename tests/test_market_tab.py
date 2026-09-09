from unittest.mock import patch

from PySide6.QtWidgets import QTabWidget

from app.ui.main_window import MainWindow
from app.ui.market_tab import MarketTab, NumericTableWidgetItem


def test_numeric_table_widget_item_sorts_by_value_not_text(qapp):
    small = NumericTableWidgetItem(2.0, "2.00")
    big = NumericTableWidgetItem(10.0, "10.00")

    # Metne göre "10.00" < "2.00" olurdu; sayısal olarak tam tersi olmalı.
    assert small < big


def test_market_tab_populates_table_sorted_by_volume_desc(qapp):
    overview = [
        {"symbol": "AAAUSDT", "quote_volume": 10.0},
        {"symbol": "BBBUSDT", "quote_volume": 100.0},
        {"symbol": "CCCUSDT", "quote_volume": 50.0},
    ]
    with patch("app.repository.get_market_overview", return_value=overview):
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

    assert tab.table.rowCount() == 3
    assert [tab.table.item(i, 0).text() for i in range(3)] == ["BBBUSDT", "CCCUSDT", "AAAUSDT"]


def test_market_tab_shows_last_price_column(qapp):
    overview = [
        {"symbol": "AAAUSDT", "quote_volume": 100.0, "last_price": 1.2345},
    ]
    with patch("app.repository.get_market_overview", return_value=overview):
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

    assert tab.table.item(0, 1).text() == "1.2345"


def test_market_tab_shows_volume_and_price_change_percent_columns(qapp):
    overview = [
        {
            "symbol": "AAAUSDT",
            "quote_volume": 100.0,
            "volume_change_percent": 12.34,
            "price_change_percent": 3.456,
        },
        {
            "symbol": "BBBUSDT",
            "quote_volume": 50.0,
            "volume_change_percent": -5.0,
            "price_change_percent": -1.2,
        },
    ]
    with patch("app.repository.get_market_overview", return_value=overview):
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

    assert tab.table.item(0, 3).text() == "+12.34%"
    assert tab.table.item(0, 4).text() == "+3.46%"
    assert tab.table.item(1, 3).text() == "-5.00%"
    assert tab.table.item(1, 4).text() == "-1.20%"


def test_market_tab_copies_symbol_to_clipboard_from_context_menu(qapp):
    from unittest.mock import MagicMock

    from PySide6.QtGui import QGuiApplication

    overview = [{"symbol": "AAAUSDT", "quote_volume": 100.0}]
    with patch("app.repository.get_market_overview", return_value=overview):
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

    # Gerçek QMenu.exec() bir native popup açıp kullanıcı tıklamasını bekler
    # (headless/offscreen'de sonsuza kadar bloklar); QMenu'nün kendisini sahte bir
    # nesneyle değiştirip "kopyala" eylemine tıklanmış gibi davranıyoruz.
    fake_action = object()
    fake_menu = MagicMock()
    fake_menu.addAction.return_value = fake_action
    fake_menu.exec.return_value = fake_action

    with patch("app.ui.market_tab.QMenu", return_value=fake_menu):
        position = tab.table.visualItemRect(tab.table.item(0, 0)).center()
        tab._show_context_menu(position)

    assert QGuiApplication.clipboard().text() == "AAAUSDT"


def test_market_tab_context_menu_does_nothing_when_no_row_under_cursor(qapp):
    from PySide6.QtGui import QGuiApplication

    overview = [{"symbol": "AAAUSDT", "quote_volume": 100.0}]
    with patch("app.repository.get_market_overview", return_value=overview):
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

    QGuiApplication.clipboard().setText("değişmedi")
    from PySide6.QtCore import QPoint

    tab._show_context_menu(QPoint(-1, -1))

    assert QGuiApplication.clipboard().text() == "değişmedi"


def test_market_tab_refresh_uses_selected_period(qapp):
    with patch("app.repository.get_market_overview", return_value=[]) as mock_overview:
        tab = MarketTab()
        tab._worker.wait()
        qapp.processEvents()

        one_hour_index = tab.period_combo.findData("1h")
        tab.period_combo.setCurrentIndex(one_hour_index)
        tab._worker.wait()
        qapp.processEvents()

    called_periods = [call.args[0] for call in mock_overview.call_args_list]
    assert called_periods[-1] == "1h"


def test_main_window_has_expected_tabs(qapp, db, user):
    with patch("app.repository.get_market_overview", return_value=[]):
        window = MainWindow(user.id, user.email)
        window.market_tab._worker.wait()
        qapp.processEvents()

    tabs = window.findChild(QTabWidget)
    assert tabs.count() == 4
    assert tabs.tabText(0) == "Piyasa"
    assert tabs.tabText(1) == "Transferler"
    assert tabs.tabText(2) == "Tuzak Skoru"
    assert tabs.tabText(3) == "Backtest"
