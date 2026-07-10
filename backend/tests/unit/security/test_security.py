"""Unit tests for passwords, JWTs, deterministic RBAC, and retrieval policy."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from enterprise_ai.core.config import Settings
from enterprise_ai.models.identity import (
    AccessLevel,
    AuthenticatedPrincipal,
    ToolPermission,
    UserIdentity,
    UserRole,
)
from enterprise_ai.models.retrieval import DocumentMetadata, DocumentType
from enterprise_ai.models.tools import ToolName
from enterprise_ai.security.authentication import (
    AuthenticationService,
    ConfiguredUser,
    normalize_username,
)
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.exceptions import AuthenticationError, AuthorizationError
from enterprise_ai.security.password import PasswordService
from enterprise_ai.security.policies import ROLE_PERMISSIONS, TOOL_PERMISSIONS
from enterprise_ai.security.token import TokenService
from pydantic import SecretStr, ValidationError

SECRET = "test-signing-secret-with-at-least-48-characters-long"
OTHER_SECRET = "different-test-secret-with-at-least-48-characters-long"


def _identity(role: UserRole = UserRole.VIEWER) -> UserIdentity:
    return UserIdentity(
        user_id=uuid4(), username=f"demo-{role.value}", display_name="Demo", role=role
    )


def _principal(role: UserRole) -> AuthenticatedPrincipal:
    now = datetime.now(UTC)
    return AuthenticatedPrincipal(
        identity=_identity(role),
        permissions=ROLE_PERMISSIONS[role],
        authenticated_at=now,
        expires_at=now + timedelta(minutes=30),
    )


def _token_service(
    *, secret: str = SECRET, issuer: str = "test-issuer", audience: str = "test-audience"
) -> TokenService:
    return TokenService(
        secret=secret,
        algorithm="HS256",
        issuer=issuer,
        audience=audience,
        expiry_minutes=30,
    )


def _mutated_token(token: str, **changes: object) -> str:
    payload = jwt.decode(token, options={"verify_signature": False})
    payload.update(changes)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_argon2_password_hash_and_verification_are_safe() -> None:
    service = PasswordService()
    password = "Correct-Testing-Password"
    password_hash = service.hash_password(password)

    assert password not in password_hash
    assert service.verify_password(password_hash, password)
    assert not service.verify_password(password_hash, "incorrect-password")
    assert not service.verify_password("not-an-argon-hash", password)


def test_authentication_normalizes_username_and_masks_hash() -> None:
    password_service = PasswordService()
    user = ConfiguredUser(
        identity=_identity(),
        password_hash=password_service.hash_password("Correct-Testing-Password"),
    )
    authentication = AuthenticationService((user,), password_service)

    profile = authentication.authenticate(
        f"  {user.identity.username.upper()}  ", SecretStr("Correct-Testing-Password")
    )
    assert profile.user_id == user.identity.user_id
    assert normalize_username("  Demo-Viewer ") == "demo-viewer"
    assert user.password_hash not in repr(user)
    with pytest.raises(AuthenticationError):
        authentication.authenticate(user.identity.username, SecretStr("wrong-password"))


def test_valid_token_round_trip_uses_exact_role_policy() -> None:
    service = _token_service()
    identity = _identity(UserRole.ANALYST)
    token = service.issue_token(identity, ROLE_PERMISSIONS[UserRole.ANALYST])
    principal = service.decode_principal(token)

    assert principal.identity.user_id == identity.user_id
    assert principal.identity.role is UserRole.ANALYST
    assert principal.permissions == ROLE_PERMISSIONS[UserRole.ANALYST]
    assert token not in repr(service)


@pytest.mark.parametrize(
    "extra_permission",
    [ToolPermission.ADMINISTRATIVE_TOOLS, ToolPermission.INGESTION_MANAGEMENT],
)
def test_analyst_token_cannot_add_administrative_permissions(
    extra_permission: ToolPermission,
) -> None:
    service = _token_service()
    token = service.issue_token(_identity(UserRole.ANALYST), ROLE_PERMISSIONS[UserRole.ANALYST])
    permissions = [permission.value for permission in ROLE_PERMISSIONS[UserRole.ANALYST]]
    with pytest.raises(AuthenticationError):
        service.decode_principal(
            _mutated_token(token, permissions=[*permissions, extra_permission.value])
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"iss": "wrong-issuer"}, "invalid"),
        ({"aud": "wrong-audience"}, "invalid"),
        ({"role": "superuser"}, "invalid"),
        ({"permissions": ["unknown_permission"]}, "invalid"),
        ({"permissions": []}, "invalid"),
        ({"permissions": "knowledge_search"}, "invalid"),
        ({"permissions": ["knowledge_search", "python_analysis"]}, "invalid"),
        ({"permissions": ["knowledge_search", "mcp_tools"]}, "invalid"),
        ({"exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())}, "expired"),
    ],
)
def test_invalid_token_claims_are_rejected(changes: dict[str, object], reason: str) -> None:
    service = _token_service()
    token = service.issue_token(_identity(), ROLE_PERMISSIONS[UserRole.VIEWER])
    with pytest.raises(AuthenticationError) as caught:
        service.decode_principal(_mutated_token(token, **changes))
    assert reason in caught.value.reason_code


def test_missing_claim_invalid_signature_and_algorithm_confusion_are_rejected() -> None:
    service = _token_service()
    token = service.issue_token(_identity(), ROLE_PERMISSIONS[UserRole.VIEWER])
    payload = jwt.decode(token, options={"verify_signature": False})
    payload.pop("jti")
    missing_claim = jwt.encode(payload, SECRET, algorithm="HS256")
    wrong_signature = jwt.encode(payload | {"jti": str(uuid4())}, OTHER_SECRET, algorithm="HS256")
    wrong_algorithm = jwt.encode(payload | {"jti": str(uuid4())}, SECRET, algorithm="HS384")

    for invalid_token in (missing_claim, wrong_signature, wrong_algorithm, "not-a-jwt"):
        with pytest.raises(AuthenticationError):
            service.decode_principal(invalid_token)


def test_role_permission_policy_is_exact_and_defaults_to_deny() -> None:
    authorization = AuthorizationService()
    assert authorization.permissions_for_role(UserRole.VIEWER) == frozenset(
        {ToolPermission.KNOWLEDGE_SEARCH}
    )
    assert authorization.permissions_for_role(UserRole.ANALYST) == frozenset(
        {
            ToolPermission.KNOWLEDGE_SEARCH,
            ToolPermission.PYTHON_ANALYSIS,
            ToolPermission.MCP_TOOLS,
        }
    )
    assert authorization.permissions_for_role(UserRole.ADMINISTRATOR) == frozenset(ToolPermission)
    assert authorization.permissions_for_role("unknown") == frozenset()
    assert not authorization.has_permission(_principal(UserRole.VIEWER), "unknown")


def test_principal_cannot_gain_permissions_by_mutating_token_contract() -> None:
    now = datetime.now(UTC)
    manipulated = AuthenticatedPrincipal(
        identity=_identity(UserRole.VIEWER),
        permissions=frozenset(ToolPermission),
        authenticated_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    authorization = AuthorizationService()
    assert not authorization.has_permission(manipulated, ToolPermission.PYTHON_ANALYSIS)
    assert not authorization.authorize_tool(manipulated, ToolName.PYTHON_ANALYSIS).allowed
    assert not authorization.is_document_authorized(
        manipulated,
        _metadata(AccessLevel.CONFIDENTIAL, frozenset({UserRole.VIEWER})),
    )
    with pytest.raises(AuthorizationError):
        authorization.require_permission(manipulated, ToolPermission.PYTHON_ANALYSIS)


@pytest.mark.parametrize(("tool", "permission"), list(TOOL_PERMISSIONS.items()))
def test_every_tool_has_a_fixed_permission(tool: ToolName, permission: ToolPermission) -> None:
    assert (
        AuthorizationService()
        .authorize_tool(_principal(UserRole.ADMINISTRATOR), tool)
        .required_permission
        is permission
    )


def test_tool_authorization_matrix_and_unknown_tool_default_deny() -> None:
    authorization = AuthorizationService()
    viewer = _principal(UserRole.VIEWER)
    analyst = _principal(UserRole.ANALYST)
    admin = _principal(UserRole.ADMINISTRATOR)

    assert authorization.authorize_tool(viewer, ToolName.KNOWLEDGE_SEARCH).allowed
    assert not authorization.authorize_tool(viewer, ToolName.PYTHON_ANALYSIS).allowed
    assert not authorization.authorize_tool(viewer, ToolName.EMPLOYEE_DIRECTORY).allowed
    assert authorization.authorize_tool(analyst, ToolName.PYTHON_ANALYSIS).allowed
    assert authorization.authorize_tool(analyst, ToolName.SERVICE_CATALOG).allowed
    assert not authorization.authorize_tool(analyst, ToolName.ADMINISTRATIVE_INGESTION).allowed
    assert all(authorization.authorize_tool(admin, tool).allowed for tool in ToolName)
    assert not authorization.authorize_tool(admin, "unknown").allowed


def _metadata(access: AccessLevel, allowed_roles: frozenset[UserRole]) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=uuid4(),
        title="Authorization Fixture",
        source="mock://authorization",
        department="Security",
        document_type=DocumentType.POLICY,
        access_level=access,
        allowed_roles=allowed_roles,
        created_date=date(2026, 1, 1),
        updated_date=date(2026, 1, 1),
        version="1.0",
        content_hash="a" * 64,
    )


def test_retrieval_authorization_requires_level_and_allowed_role() -> None:
    authorization = AuthorizationService()
    viewer = _principal(UserRole.VIEWER)
    analyst = _principal(UserRole.ANALYST)
    admin = _principal(UserRole.ADMINISTRATOR)

    assert authorization.is_document_authorized(
        viewer, _metadata(AccessLevel.PUBLIC, frozenset({UserRole.VIEWER}))
    )
    assert authorization.is_document_authorized(
        viewer, _metadata(AccessLevel.INTERNAL, frozenset({UserRole.VIEWER}))
    )
    assert not authorization.is_document_authorized(
        viewer, _metadata(AccessLevel.CONFIDENTIAL, frozenset({UserRole.VIEWER}))
    )
    assert not authorization.is_document_authorized(
        viewer, _metadata(AccessLevel.RESTRICTED, frozenset({UserRole.VIEWER}))
    )
    assert authorization.is_document_authorized(
        analyst, _metadata(AccessLevel.CONFIDENTIAL, frozenset({UserRole.ANALYST}))
    )
    assert not authorization.is_document_authorized(
        analyst, _metadata(AccessLevel.RESTRICTED, frozenset({UserRole.ANALYST}))
    )
    assert authorization.is_document_authorized(
        admin, _metadata(AccessLevel.RESTRICTED, frozenset({UserRole.ADMINISTRATOR}))
    )
    assert not authorization.is_document_authorized(
        admin, _metadata(AccessLevel.PUBLIC, frozenset({UserRole.VIEWER}))
    )
    assert not authorization.is_document_authorized(viewer, {"access_level": "public"})


def test_authentication_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_enabled=True)
    with pytest.raises(ValidationError):
        Settings(auth_token_expiry_minutes=0)
    with pytest.raises(ValidationError):
        Settings(auth_token_algorithm="none")


def test_safe_authentication_settings_can_be_injected() -> None:
    password_hash = PasswordService().hash_password("Test-Only-Password")
    settings = Settings(
        auth_enabled=True,
        auth_token_secret=SECRET,
        demo_viewer_password_hash=password_hash,
        demo_analyst_password_hash=password_hash,
        demo_admin_password_hash=password_hash,
    )
    assert settings.auth_enabled
    assert SECRET not in repr(settings.auth_token_secret)
