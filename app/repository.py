from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.binance_client import (
    BinanceAPIError,
    create_universal_transfer,
    get_api_restrictions,
    get_funding_wallet,
    get_futures_account,
    get_futures_market_overview,
    get_spot_account,
)
from app.crypto import decrypt_secret, encrypt_secret
from app.models import ApiCredential, Transfer, User
from app.security import hash_password, verify_password
from app.transfer_types import TRANSFER_TYPE_MAP, WalletType


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class CredentialNotFoundError(Exception):
    pass


class WithdrawalPermissionError(Exception):
    pass


class SameWalletError(Exception):
    pass


class UnsupportedTransferError(Exception):
    pass


# ---- Auth -------------------------------------------------------------


def get_user_by_id(db: Session, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise InvalidCredentialsError("Kullanıcı bulunamadı")
    return user


def register_user(db: Session, email: str, password: str) -> User:
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        raise DuplicateEmailError(f"'{email}' zaten kayıtlı")

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("E-posta veya şifre hatalı")
    return user


# ---- Credentials --------------------------------------------------------


def connect_credential(db: Session, user: User, label: str, api_key: str, api_secret: str) -> ApiCredential:
    restrictions = get_api_restrictions(api_key, api_secret)  # BinanceAPIError olduğu gibi yukarı fırlatılır

    if restrictions.get("enableWithdrawals"):
        raise WithdrawalPermissionError(
            "Bu API key'de para çekme (withdrawal) izni açık. Güvenlik nedeniyle sadece "
            "'Enable Reading' ve gerekirse 'Enable Spot & Margin/Futures Trading' izinleri "
            "açık olan bir API key kullanın; Binance panelinden withdrawal iznini kapatın."
        )

    credential = ApiCredential(
        user_id=user.id,
        label=label,
        encrypted_api_key=encrypt_secret(api_key),
        encrypted_api_secret=encrypt_secret(api_secret),
        can_withdraw=bool(restrictions.get("enableWithdrawals")),
        permissions_verified_at=datetime.now(UTC),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


def list_credentials(db: Session, user: User) -> list[ApiCredential]:
    return (
        db.query(ApiCredential)
        .filter(ApiCredential.user_id == user.id)
        .order_by(ApiCredential.created_at.desc())
        .all()
    )


def get_credential(db: Session, user: User, credential_id: UUID | None) -> ApiCredential:
    query = db.query(ApiCredential).filter(ApiCredential.user_id == user.id)
    credential = (
        query.filter(ApiCredential.id == credential_id).first()
        if credential_id is not None
        else query.order_by(ApiCredential.created_at.desc()).first()
    )
    if credential is None:
        raise CredentialNotFoundError("Bağlı bir Binance hesabı bulunamadı. Önce bir API key bağlayın.")
    return credential


def delete_credential(db: Session, user: User, credential_id: UUID) -> None:
    credential = db.query(ApiCredential).filter(
        ApiCredential.id == credential_id, ApiCredential.user_id == user.id
    ).first()
    if credential is None:
        raise CredentialNotFoundError("Bağlı hesap bulunamadı")
    db.delete(credential)
    db.commit()


# ---- Wallet --------------------------------------------------------------


def get_wallet_summary(db: Session, user: User, credential_id: UUID | None = None) -> dict:
    credential = get_credential(db, user, credential_id)
    api_key = decrypt_secret(credential.encrypted_api_key)
    api_secret = decrypt_secret(credential.encrypted_api_secret)

    spot_account = get_spot_account(api_key, api_secret)
    futures_account = get_futures_account(api_key, api_secret)
    funding_wallet = get_funding_wallet(api_key, api_secret)

    spot = [
        {"asset": b["asset"], "free": float(b["free"]), "locked": float(b["locked"])}
        for b in spot_account.get("balances", [])
        if float(b["free"]) > 0 or float(b["locked"]) > 0
    ]
    futures = [
        {
            "asset": a["asset"],
            "wallet_balance": float(a["walletBalance"]),
            "available_balance": float(a["availableBalance"]),
            "unrealized_profit": float(a.get("unrealizedProfit", 0)),
        }
        for a in futures_account.get("assets", [])
        if float(a["walletBalance"]) != 0
    ]
    funding = [
        {"asset": f["asset"], "free": float(f["free"]), "locked": float(f.get("locked", 0))}
        for f in funding_wallet
        if float(f["free"]) > 0 or float(f.get("locked", 0)) > 0
    ]

    return {
        "credential_id": str(credential.id),
        "credential_label": credential.label,
        "spot": spot,
        "futures": futures,
        "funding": funding,
    }


# ---- Transfers -------------------------------------------------------------


def create_transfer(
    db: Session,
    user: User,
    asset: str,
    amount: Decimal,
    from_wallet: WalletType,
    to_wallet: WalletType,
    credential_id: UUID | None = None,
) -> Transfer:
    if from_wallet == to_wallet:
        raise SameWalletError("Kaynak ve hedef cüzdan aynı olamaz")

    transfer_type = TRANSFER_TYPE_MAP.get((from_wallet, to_wallet))
    if transfer_type is None:
        raise UnsupportedTransferError("Desteklenmeyen transfer yönü")

    credential = get_credential(db, user, credential_id)
    api_key = decrypt_secret(credential.encrypted_api_key)
    api_secret = decrypt_secret(credential.encrypted_api_secret)

    asset = asset.upper()
    transfer = Transfer(
        user_id=user.id,
        credential_id=credential.id,
        asset=asset,
        amount=amount,
        from_wallet=from_wallet.value,
        to_wallet=to_wallet.value,
        status="PENDING",
    )
    db.add(transfer)
    db.flush()

    try:
        result = create_universal_transfer(api_key, api_secret, transfer_type, asset, str(amount))
    except BinanceAPIError as exc:
        transfer.status = "FAILED"
        transfer.error_message = exc.message
        db.commit()
        db.refresh(transfer)
        raise

    transfer.status = "SUCCESS"
    tran_id = result.get("tranId")
    transfer.binance_tran_id = str(tran_id) if tran_id is not None else None
    db.commit()
    db.refresh(transfer)
    return transfer


# ---- Piyasa verisi (public, kullanıcıdan/credential'dan bağımsız) --------


def get_market_overview(period: str) -> list[dict]:
    """USDT-M perpetual futures sembollerini verilen dönemdeki (1h/4h/24h) işlem
    hacmine (USDT) göre büyükten küçüğe sıralı döner."""
    overview = get_futures_market_overview(period)
    return sorted(overview, key=lambda row: row["quote_volume"], reverse=True)


def list_transfers(db: Session, user: User, limit: int = 50) -> list[Transfer]:
    return (
        db.query(Transfer)
        .filter(Transfer.user_id == user.id)
        .order_by(Transfer.created_at.desc())
        .limit(limit)
        .all()
    )
