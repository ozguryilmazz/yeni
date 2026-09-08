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


def test_main_window_has_market_and_transfers_tabs(qapp, db, user):
    with patch("app.repository.get_market_overview", return_value=[]):
        window = MainWindow(user.id, user.email)
        window.market_tab._worker.wait()
        qapp.processEvents()

    tabs = window.findChild(QTabWidget)
    assert tabs.count() == 2
    assert tabs.tabText(0) == "Piyasa"
    assert tabs.tabText(1) == "Transferler"
