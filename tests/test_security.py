from __future__ import annotations

import pytest
from fishrag_api.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip() -> None:
    token = create_access_token(subject="user-1", role="admin")
    payload = decode_access_token(token)

    assert payload.subject == "user-1"
    assert payload.role == "admin"


def test_access_token_rejects_tampering() -> None:
    token = create_access_token(subject="user-1", role="admin")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

    with pytest.raises(ValueError):
        decode_access_token(tampered)
