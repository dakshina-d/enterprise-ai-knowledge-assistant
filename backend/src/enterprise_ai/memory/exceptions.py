"""Typed conversational-memory failures."""


class MemoryError(RuntimeError):
    """Base memory failure with no stored-content disclosure."""


class MemoryOwnershipError(MemoryError):
    """The session is bound to another principal or policy."""


class MemoryIntegrityError(MemoryError):
    """An idempotency or internal-state invariant failed."""


class MemoryCapacityError(MemoryError):
    """A configured capacity cannot accept a safe turn."""
