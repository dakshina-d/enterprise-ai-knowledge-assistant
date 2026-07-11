"""Checkpoint construction kept separate from graph topology."""

from langgraph.checkpoint.memory import InMemorySaver


def create_checkpointer() -> InMemorySaver:
    """Return the explicit local-development checkpoint implementation."""
    return InMemorySaver()
