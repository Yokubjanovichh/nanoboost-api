"""Unit tests for password hashing + JWT token round-trips."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.constants import TokenType, UserRole
from app.core.exceptions import TokenInvalidError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        hashed = hash_password("CorrectHorseBatteryStaple!")
        assert verify_password("CorrectHorseBatteryStaple!", hashed)

    def test_verify_rejects_wrong_password(self):
        hashed = hash_password("right-one")
        assert not verify_password("wrong-one", hashed)

    def test_each_hash_is_unique(self):
        assert hash_password("same") != hash_password("same")  # bcrypt salt


class TestJWT:
    def test_access_token_roundtrip(self):
        uid = uuid4()
        token = create_access_token(uid, UserRole.ADMIN)
        decoded = decode_token(token, TokenType.ACCESS)
        assert decoded["sub"] == str(uid)
        assert decoded["role"] == UserRole.ADMIN.value
        assert decoded["type"] == TokenType.ACCESS.value

    def test_refresh_token_rejected_as_access(self):
        token = create_refresh_token(uuid4(), UserRole.VIEWER)
        with pytest.raises(TokenInvalidError):
            decode_token(token, TokenType.ACCESS)

    def test_garbage_token_rejected(self):
        with pytest.raises(TokenInvalidError):
            decode_token("not.a.real.jwt", TokenType.ACCESS)
