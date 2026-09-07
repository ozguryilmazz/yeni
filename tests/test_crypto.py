from app.crypto import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_round_trip():
    secret = "my-binance-api-secret-1234567890"
    encrypted = encrypt_secret(secret)

    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret


def test_encrypt_produces_different_ciphertext_each_time():
    secret = "same-secret"
    assert encrypt_secret(secret) != encrypt_secret(secret)
