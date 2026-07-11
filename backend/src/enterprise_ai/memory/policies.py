"""Central memory ownership and retention policy helpers."""

import hashlib
from uuid import UUID

from enterprise_ai.memory.models import SessionOwnership
from enterprise_ai.models.identity import AuthenticatedPrincipal


def ownership_for(session_id: UUID, principal: AuthenticatedPrincipal) -> SessionOwnership:
    identity = principal.identity
    policy = "|".join(
        (identity.role.value, *(permission.value for permission in sorted(principal.permissions)))
    )
    return SessionOwnership(
        session_id=session_id,
        user_id=identity.user_id,
        role=identity.role,
        permissions=principal.permissions,
        policy_fingerprint=hashlib.sha256(policy.encode()).hexdigest(),
    )
