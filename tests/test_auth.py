import pytest

from app.repository import DuplicateEmailError, InvalidCredentialsError, authenticate_user, register_user


def test_register_and_authenticate(db):
    user = register_user(db, "a@b.com", "password123")
    assert user.email == "a@b.com"
    assert user.password_hash != "password123"

    authenticated = authenticate_user(db, "a@b.com", "password123")
    assert authenticated.id == user.id


def test_authenticate_wrong_password(db):
    register_user(db, "a@b.com", "password123")
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "a@b.com", "wrong-password")


def test_authenticate_unknown_email(db):
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "nobody@example.com", "password123")


def test_register_duplicate_email(db):
    register_user(db, "a@b.com", "password123")
    with pytest.raises(DuplicateEmailError):
        register_user(db, "a@b.com", "password456")
