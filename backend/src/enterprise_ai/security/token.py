"""Strict JWT access-token issuance and validation for the proof of concept."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

import jwt
from pydantic import Field, ValidationError

from enterprise_ai.models.common import ContractModel
from enterprise_ai.models.identity import (
    AuthenticatedPrincipal,
    ToolPermission,
    UserIdentity,
    UserRole,
)
from enterprise_ai.security.exceptions import AuthenticationError
from enterprise_ai.security.policies import ROLE_PERMISSIONS


class TokenClaims(ContractModel):
    sub: UUID
    preferred_username: Annotated[str, Field(min_length=1, max_length=128)]
    role: UserRole
    permissions: tuple[ToolPermission, ...]
    iss: Annotated[str, Field(min_length=1)]
    aud: Annotated[str, Field(min_length=1)]
    iat: Annotated[int, Field(ge=0)]
    exp: Annotated[int, Field(ge=0)]
    jti: UUID


class TokenService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        issuer: str,
        audience: str,
        expiry_minutes: int,
    ) -> None:
        if algorithm != "HS256":
            raise ValueError("unsupported JWT algorithm")
        if len(secret) < 32:
            raise ValueError("JWT signing secret must contain at least 32 characters")
        if expiry_minutes < 1:
            raise ValueError("token expiry must be positive")
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._expiry = timedelta(minutes=expiry_minutes)

    @property
    def expires_in_seconds(self) -> int:
        return int(self._expiry.total_seconds())

    def issue_token(self, identity: UserIdentity, permissions: frozenset[ToolPermission]) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(identity.user_id),
            "preferred_username": identity.username,
            "role": identity.role.value,
            "permissions": sorted(permission.value for permission in permissions),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int((now + self._expiry).timestamp()),
            "jti": str(uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_principal(self, token: str) -> AuthenticatedPrincipal:
        try:
            raw: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": [
                        "sub",
                        "preferred_username",
                        "role",
                        "permissions",
                        "iss",
                        "aud",
                        "iat",
                        "exp",
                        "jti",
                    ]
                },
            )
            self._validate_raw_claim_types(raw)
            claims = TokenClaims.model_validate(raw)
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError(reason_code="authentication.token_expired") from error
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as error:
            raise AuthenticationError(reason_code="authentication.invalid_token") from error

        expected_permissions = ROLE_PERMISSIONS.get(claims.role)
        token_permissions = frozenset(claims.permissions)
        if expected_permissions is None or token_permissions != expected_permissions:
            raise AuthenticationError(reason_code="authentication.invalid_permissions")

        authenticated_at = datetime.fromtimestamp(claims.iat, tz=UTC)
        expires_at = datetime.fromtimestamp(claims.exp, tz=UTC)
        return AuthenticatedPrincipal(
            identity=UserIdentity(
                user_id=claims.sub,
                username=claims.preferred_username,
                display_name=claims.preferred_username,
                role=claims.role,
            ),
            permissions=expected_permissions,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
        )

    @staticmethod
    def _validate_raw_claim_types(raw: dict[str, Any]) -> None:
        string_claims = ("sub", "preferred_username", "role", "iss", "aud", "jti")
        if any(not isinstance(raw.get(name), str) for name in string_claims):
            raise ValueError("invalid JWT claim types")
        if not isinstance(raw.get("permissions"), list) or any(
            not isinstance(item, str) for item in raw["permissions"]
        ):
            raise ValueError("invalid JWT permission claim")
        if not isinstance(raw.get("iat"), int) or not isinstance(raw.get("exp"), int):
            raise ValueError("invalid JWT timestamp claims")
