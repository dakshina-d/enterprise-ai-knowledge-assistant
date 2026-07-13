"""Pure deterministic reducers for partial graph-state updates."""

from collections.abc import Sequence

from enterprise_ai.models.events import AgentEvent

MAX_RETAINED_ACTIVITY_EVENTS = 200


def append_unique[ItemT](left: Sequence[ItemT], right: Sequence[ItemT]) -> tuple[ItemT, ...]:
    if not right:
        return ()
    result = list(left)
    for item in right:
        if item not in result:
            result.append(item)
    return tuple(result)


def append_text(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    if not right:
        return ()
    return tuple((*left, *right))


def append_events(
    left: Sequence[AgentEvent], right: Sequence[AgentEvent]
) -> tuple[AgentEvent, ...]:
    """Reset event history when a new correlated invocation starts at sequence zero."""
    if right and right[0].sequence_number == 0:
        return tuple(right[-MAX_RETAINED_ACTIVITY_EVENTS:])
    return append_unique(left, right)[-MAX_RETAINED_ACTIVITY_EVENTS:]
