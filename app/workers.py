from PySide6.QtCore import QThread, Signal

from app import repository
from app.database import session_scope


class ConnectCredentialWorker(QThread):
    success = Signal(object)
    error = Signal(str)

    def __init__(self, user_id, label: str, api_key: str, api_secret: str) -> None:
        super().__init__()
        self._user_id = user_id
        self._label = label
        self._api_key = api_key
        self._api_secret = api_secret

    def run(self) -> None:
        try:
            with session_scope() as db:
                user = repository.get_user_by_id(db, self._user_id)
                credential = repository.connect_credential(db, user, self._label, self._api_key, self._api_secret)
                result = {
                    "id": credential.id,
                    "label": credential.label,
                    "can_withdraw": credential.can_withdraw,
                    "created_at": credential.created_at,
                }
        except Exception as exc:  # noqa: BLE001 - UI'ya taşınacak, tipi önemli değil
            self.error.emit(str(exc))
            return
        self.success.emit(result)


class LoadBalancesWorker(QThread):
    success = Signal(dict)
    error = Signal(str)

    def __init__(self, user_id, credential_id=None) -> None:
        super().__init__()
        self._user_id = user_id
        self._credential_id = credential_id

    def run(self) -> None:
        try:
            with session_scope() as db:
                user = repository.get_user_by_id(db, self._user_id)
                summary = repository.get_wallet_summary(db, user, self._credential_id)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(summary)


class CreateTransferWorker(QThread):
    success = Signal(object)
    error = Signal(str)

    def __init__(self, user_id, credential_id, asset, amount, from_wallet, to_wallet) -> None:
        super().__init__()
        self._user_id = user_id
        self._credential_id = credential_id
        self._asset = asset
        self._amount = amount
        self._from_wallet = from_wallet
        self._to_wallet = to_wallet

    def run(self) -> None:
        try:
            with session_scope() as db:
                user = repository.get_user_by_id(db, self._user_id)
                transfer = repository.create_transfer(
                    db,
                    user,
                    self._asset,
                    self._amount,
                    self._from_wallet,
                    self._to_wallet,
                    credential_id=self._credential_id,
                )
                result = {
                    "asset": transfer.asset,
                    "amount": str(transfer.amount),
                    "status": transfer.status,
                    "binance_tran_id": transfer.binance_tran_id,
                    "error_message": transfer.error_message,
                }
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(result)
