from datetime import datetime

from PySide6.QtCore import QThread, Signal

from app import repository
from app.backtest.service import run_backtest_comparison
from app.database import session_scope
from app.grid_trading.screener import ScreenerCriteria, run_screener
from app.grid_trading.service import compute_range_for_symbol, run_grid_backtest_for_symbol


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


class LoadMarketOverviewWorker(QThread):
    success = Signal(list)
    error = Signal(str)

    def __init__(self, period: str) -> None:
        super().__init__()
        self._period = period

    def run(self) -> None:
        try:
            overview = repository.get_market_overview(self._period)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(overview)


class RunBacktestWorker(QThread):
    success = Signal(object)  # BacktestComparison
    error = Signal(str)

    def __init__(self, symbol: str, start: datetime, end: datetime, interval: str, strategy_name: str) -> None:
        super().__init__()
        self._symbol = symbol
        self._start = start
        self._end = end
        self._interval = interval
        self._strategy_name = strategy_name

    def run(self) -> None:
        try:
            result = run_backtest_comparison(
                self._symbol, self._start, self._end, interval=self._interval, strategy_name=self._strategy_name
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(result)


class RunGridScreenerWorker(QThread):
    success = Signal(list)  # list[CandidateResult]
    error = Signal(str)

    def __init__(self, criteria: ScreenerCriteria | None = None) -> None:
        super().__init__()
        self._criteria = criteria

    def run(self) -> None:
        try:
            results = run_screener(self._criteria)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(results)


class ComputeGridRangeWorker(QThread):
    success = Signal(object)  # GridRange
    error = Signal(str)

    def __init__(self, symbol: str, method: str, interval: str, lookback_candles: int, method_kwargs: dict) -> None:
        super().__init__()
        self._symbol = symbol
        self._method = method
        self._interval = interval
        self._lookback_candles = lookback_candles
        self._method_kwargs = method_kwargs

    def run(self) -> None:
        try:
            result = compute_range_for_symbol(
                self._symbol, self._method, self._interval, self._lookback_candles, **self._method_kwargs
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(result)


class RunGridBacktestWorker(QThread):
    success = Signal(object)  # GridBacktestResult
    error = Signal(str)

    def __init__(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        lower_price: float,
        upper_price: float,
        grid_count: int,
        capital_usd: float,
        leverage: float,
        fee_rate: float,
    ) -> None:
        super().__init__()
        self._symbol = symbol
        self._start = start
        self._end = end
        self._interval = interval
        self._lower_price = lower_price
        self._upper_price = upper_price
        self._grid_count = grid_count
        self._capital_usd = capital_usd
        self._leverage = leverage
        self._fee_rate = fee_rate

    def run(self) -> None:
        try:
            result = run_grid_backtest_for_symbol(
                self._symbol,
                self._start,
                self._end,
                self._interval,
                self._lower_price,
                self._upper_price,
                grid_count=self._grid_count,
                capital_usd=self._capital_usd,
                leverage=self._leverage,
                fee_rate=self._fee_rate,
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.success.emit(result)


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
