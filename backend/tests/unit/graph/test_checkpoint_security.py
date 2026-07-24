"""Explicit checkpoint-deserialization allowlist coverage."""

from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.models.identity import UserRole
from pydantic import BaseModel


class UnregisteredCheckpointModel(BaseModel):
    value: str


def test_registered_application_type_round_trips() -> None:
    serializer = create_checkpointer().serde
    encoded = serializer.dumps_typed(UserRole.VIEWER)
    assert serializer.loads_typed(encoded) is UserRole.VIEWER


def test_unregistered_application_type_is_not_reconstructed() -> None:
    serializer = create_checkpointer().serde
    encoded = serializer.dumps_typed(UnregisteredCheckpointModel(value="safe"))
    restored = serializer.loads_typed(encoded)
    assert not isinstance(restored, UnregisteredCheckpointModel)
    assert restored == {"value": "safe"}
