import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    # ENCRYPTION_MASTER_KEY herhangi bir uzunlukta rastgele bir string olabilir;
    # Fernet'in istediği 32 byte'lık url-safe base64 anahtara burada indirgeniyor.
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(settings.encryption_master_key.encode()).digest())
    return Fernet(derived_key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
