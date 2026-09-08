import base64
import hashlib
from functools import lru_cache

import keyring
from cryptography.fernet import Fernet

from app.config import get_app_data_dir

_SERVICE_NAME = "BinanceWalletManager"
_KEY_USERNAME = "encryption-master-key"


def _fallback_key_file():
    return get_app_data_dir() / ".master_key"


@lru_cache
def _get_or_create_master_key() -> str:
    """Binance API secret'larını şifrelemek için kullanılan ana anahtar.

    Öncelik OS'in güvenli kimlik bilgisi deposudur (Windows Credential Manager /
    macOS Keychain / Linux Secret Service). Keyring kullanılamıyorsa (ör. başsız
    Linux ortamı) izinleri kısıtlı bir local dosyaya düşülür.
    """
    try:
        key = keyring.get_password(_SERVICE_NAME, _KEY_USERNAME)
        if key:
            return key
        key = Fernet.generate_key().decode()
        keyring.set_password(_SERVICE_NAME, _KEY_USERNAME, key)
        return key
    except Exception:  # noqa: BLE001 - keyring backend'i platforma göre öngörülemez şekilde başarısız olabilir
        return _get_or_create_fallback_key()


def _get_or_create_fallback_key() -> str:
    key_file = _fallback_key_file()
    if key_file.exists():
        return key_file.read_text().strip()

    key = Fernet.generate_key().decode()
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(_get_or_create_master_key().encode()).digest())
    return Fernet(derived_key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
