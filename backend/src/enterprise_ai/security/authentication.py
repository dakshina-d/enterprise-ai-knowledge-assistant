"""Configuration-backed demonstration authentication service."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pydantic import SecretStr

from enterprise_ai.core.config import Settings
from enterprise_ai.models.identity import PublicUserProfile, UserIdentity, UserRole
from enterprise_ai.security.exceptions import AuthenticationError
from enterprise_ai.security.password import PasswordService


@dataclass(frozen=True)
class ConfiguredUser:
    identity: UserIdentity
    password_hash: str

    def __repr__(self) -> str:
        return f"ConfiguredUser(identity={self.identity!r}, password_hash='**********')"


def normalize_username(username: str) -> str:
    """Normalize usernames using surrounding-whitespace removal and Unicode case-folding."""
    return username.strip().casefold()


class AuthenticationService:
    def __init__(
        self,
        users: tuple[ConfiguredUser, ...],
        password_service: PasswordService,
    ) -> None:
        self._password_service = password_service
        self._users = {normalize_username(user.identity.username): user for user in users}
        if len(self._users) != len(users) or not users:
            raise ValueError(
                "configured usernames must be non-empty and unique after normalization"
            )
        self._fallback_hash = users[0].password_hash

    def authenticate(self, username: str, password: SecretStr) -> PublicUserProfile:
        normalized = normalize_username(username)
        configured = self._users.get(normalized)
        candidate_hash = configured.password_hash if configured else self._fallback_hash
        verified = self._password_service.verify_password(
            candidate_hash, password.get_secret_value()
        )
        if configured is None or not verified:
            raise AuthenticationError(reason_code="authentication.invalid_credentials")
        return PublicUserProfile.model_validate(configured.identity.model_dump())


def configured_users_from_settings(settings: Settings) -> tuple[ConfiguredUser, ...]:
    """Build stable PoC identities without exposing configured password hashes."""
    users = (
        _configured_user(
            settings.demo_viewer_username,
            settings.demo_viewer_password_hash,
            UserRole.VIEWER,
            settings.auth_token_issuer,
        ),
        _configured_user(
            settings.demo_analyst_username,
            settings.demo_analyst_password_hash,
            UserRole.ANALYST,
            settings.auth_token_issuer,
        ),
        _configured_user(
            settings.demo_admin_username,
            settings.demo_admin_password_hash,
            UserRole.ADMINISTRATOR,
            settings.auth_token_issuer,
        ),
    )
    return users


def _configured_user(
    username: str,
    password_hash: SecretStr | None,
    role: UserRole,
    issuer: str,
) -> ConfiguredUser:
    if password_hash is None:
        raise ValueError("demonstration password hash is required")
    normalized = normalize_username(username)
    return ConfiguredUser(
        identity=UserIdentity(
            user_id=uuid5(NAMESPACE_URL, f"{issuer}:{normalized}"),
            username=normalized,
            display_name=f"Demo {role.value.replace('_', ' ').title()}",
            role=role,
        ),
        password_hash=password_hash.get_secret_value(),
    )
