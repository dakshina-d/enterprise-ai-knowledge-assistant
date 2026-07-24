"""Explicit checkpoint-deserialization allowlist coverage."""

from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.identifiers import (
    EnterpriseIdentifier,
    EnterpriseIdentifierKind,
)
from pydantic import BaseModel


class UnregisteredCheckpointModel(BaseModel):
    value: str


def test_registered_application_type_round_trips() -> None:
    serializer = create_checkpointer().serde
    encoded = serializer.dumps_typed(UserRole.VIEWER)
    assert serializer.loads_typed(encoded) is UserRole.VIEWER

    identifier = EnterpriseIdentifier(
        normalized="INC-PAY-2025-126",
        original="inc-pay-2025-126",
        kind=EnterpriseIdentifierKind.INCIDENT,
    )
    encoded_identifier = serializer.dumps_typed(identifier)
    assert serializer.loads_typed(encoded_identifier) == identifier


def test_unregistered_application_type_is_not_reconstructed() -> None:
    serializer = create_checkpointer().serde
    encoded = serializer.dumps_typed(UnregisteredCheckpointModel(value="safe"))
    restored = serializer.loads_typed(encoded)
    assert not isinstance(restored, UnregisteredCheckpointModel)
    assert restored == {"value": "safe"}
