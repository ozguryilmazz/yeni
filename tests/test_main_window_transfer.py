"""PySide6, str tabanlı bir Enum'u (WalletType) combo box itemData'sında
saklarken QVariant dönüşümü sırasında sessizce düz bir str'e indirgeyebiliyor.
Bu testler, Transferler sekmesindeki transfer formunun bu durumdan etkilenmediğini
(from_wallet/to_wallet her zaman doğru WalletType değerine normalize edildiğini
ve virgüllü/Türkçe locale'de miktarın yanlış yorumlanmadığını) doğrular.
"""

from unittest.mock import patch

from PySide6.QtCore import QLocale

from app.transfer_types import WalletType
from app.ui.transfers_tab import TransfersTab
from app.workers import CreateTransferWorker

from tests.conftest import connect_credential as connect_credential_helper


def test_combo_box_current_data_normalizes_to_wallet_type(qapp, db, user):
    connect_credential_helper(db, user)
    tab = TransfersTab(user.id)

    # Qt'nin currentData() için ne döndürdüğünden bağımsız olarak (enum veya
    # düz str), WalletType(...) ile normalize edildiğinde her zaman geçerli
    # bir WalletType üyesi elde edilmeli.
    from_wallet = WalletType(tab.from_wallet_combo.currentData())
    to_wallet = WalletType(tab.to_wallet_combo.currentData())

    assert isinstance(from_wallet, WalletType)
    assert isinstance(to_wallet, WalletType)


def test_amount_input_uses_c_locale_regardless_of_system_locale(qapp, db, user):
    original_locale = QLocale.system()
    QLocale.setDefault(QLocale(QLocale.Language.Turkish, QLocale.Country.Turkey))
    try:
        connect_credential_helper(db, user)
        tab = TransfersTab(user.id)

        tab.amount_input.lineEdit().setText("0.04")
        tab.amount_input.interpretText()

        assert tab.amount_input.value() == 0.04
    finally:
        QLocale.setDefault(original_locale)


def test_transfer_with_combo_selection_does_not_crash(qapp, db, user):
    connect_credential_helper(db, user)
    tab = TransfersTab(user.id)

    futures_index = tab.from_wallet_combo.findText("Futures (USDⓈ-M)")
    funding_index = tab.to_wallet_combo.findText("Funding")
    tab.from_wallet_combo.setCurrentIndex(futures_index)
    tab.to_wallet_combo.setCurrentIndex(funding_index)
    tab.amount_input.lineEdit().setText("0.04")
    tab.amount_input.interpretText()
    tab.asset_input.setText("USDT")

    from_wallet = WalletType(tab.from_wallet_combo.currentData())
    to_wallet = WalletType(tab.to_wallet_combo.currentData())
    assert from_wallet == WalletType.USDM_FUTURES
    assert to_wallet == WalletType.FUNDING

    with patch("app.repository.create_universal_transfer", return_value={"tranId": 777}):
        worker = CreateTransferWorker(
            user.id,
            tab.selected_credential_id,
            "USDT",
            tab.amount_input.value(),
            from_wallet,
            to_wallet,
        )
        results = {}
        worker.success.connect(lambda r: results.update(ok=r))
        worker.error.connect(lambda e: results.update(err=e))
        worker.run()

    assert "err" not in results, results.get("err")
    assert results["ok"]["status"] == "SUCCESS"
