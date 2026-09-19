from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import LiveTrade


class LiveTradeNotFoundError(Exception):
    pass


def record_trade_opened(
    db: Session,
    *,
    user_id: UUID,
    credential_id: UUID | None,
    strategy_name: str,
    symbol: str,
    interval: str,
    mode: str,
    side: str,
    margin_usd: float,
    leverage: int,
    sl_fee_mult: float,
    tp_fee_mult: float,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    quantity: float,
    entry_order_id: object,
    sl_order_id: object,
    tp_order_id: object,
) -> LiveTrade:
    """Gerçek borsaya emir gönderildikten SONRA çağrılır — bu fonksiyon kendisi
    emir göndermez, sadece zaten gönderilmiş bir işlemi denetim kaydına yazar."""
    trade = LiveTrade(
        user_id=user_id,
        credential_id=credential_id,
        strategy_name=strategy_name,
        symbol=symbol,
        interval=interval,
        mode=mode,
        side=side,
        margin_usd=Decimal(str(margin_usd)),
        leverage=leverage,
        sl_fee_mult=Decimal(str(sl_fee_mult)),
        tp_fee_mult=Decimal(str(tp_fee_mult)),
        entry_price=Decimal(str(entry_price)),
        stop_loss_price=Decimal(str(stop_loss_price)),
        take_profit_price=Decimal(str(take_profit_price)),
        quantity=Decimal(str(quantity)),
        entry_order_id=str(entry_order_id) if entry_order_id is not None else None,
        sl_order_id=str(sl_order_id) if sl_order_id is not None else None,
        tp_order_id=str(tp_order_id) if tp_order_id is not None else None,
        status="OPEN",
        opened_at=datetime.now(UTC),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def record_trade_closed(db: Session, trade_id: UUID, exit_reason: str) -> LiveTrade:
    """`exit_reason`: 'TP' | 'SL' | 'UNKNOWN' -> status 'CLOSED_TP' vb. olur."""
    trade = db.get(LiveTrade, trade_id)
    if trade is None:
        raise LiveTradeNotFoundError("İşlem kaydı bulunamadı")
    trade.status = f"CLOSED_{exit_reason}"
    trade.closed_at = datetime.now(UTC)
    db.commit()
    db.refresh(trade)
    return trade


def record_trade_failed(db: Session, trade_id: UUID, error_message: str) -> LiveTrade:
    trade = db.get(LiveTrade, trade_id)
    if trade is None:
        raise LiveTradeNotFoundError("İşlem kaydı bulunamadı")
    trade.status = "FAILED"
    trade.error_message = error_message
    trade.closed_at = datetime.now(UTC)
    db.commit()
    db.refresh(trade)
    return trade


def list_live_trades(db: Session, user_id: UUID, limit: int = 200) -> list[LiveTrade]:
    return (
        db.query(LiveTrade)
        .filter(LiveTrade.user_id == user_id)
        .order_by(LiveTrade.created_at.desc())
        .limit(limit)
        .all()
    )
