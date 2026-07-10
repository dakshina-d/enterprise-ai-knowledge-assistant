"""Argon2id password hashing and verification wrapper."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordService:
    """Delegate password cryptography to argon2-cffi."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash_password(self, password: str) -> str:
        """Create an Argon2id hash; callers must not retain the plaintext."""
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        """Verify in constant-time library code and fail closed on malformed hashes."""
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False
