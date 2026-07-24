"""Deterministic structured context and conservative follow-up resolution."""

import re

from enterprise_ai.memory.models import ConversationTurn, MemoryContext
from enterprise_ai.retrieval.identifiers import extract_enterprise_identifiers
from enterprise_ai.security.guardrails import contains_untrusted_instruction

_INCIDENT = re.compile(r"\bINC-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.I)
_SERVICES = ("HorizonPay Gateway", "LedgerBridge", "CardAuth Hub", "OpsPulse")
_FOLLOWUP = re.compile(
    r"\b(that|those|these|previous|same|them|first|second|again)\b|which runbook did you use",
    re.I,
)


def _unique[T](values: list[T], maximum: int) -> tuple[T, ...]:
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result[-maximum:])


def build_context(
    turns: tuple[ConversationTurn, ...], *, maximum_topics: int, maximum_identifiers: int
) -> MemoryContext:
    references = [reference for turn in turns for reference in turn.evidence_references]
    messages = " ".join(turn.user_message for turn in turns)
    incidents = _INCIDENT.findall(messages)
    services = [service for service in _SERVICES if service.casefold() in messages.casefold()]
    return MemoryContext(
        last_user_question=turns[-1].user_message if turns else None,
        last_intent=turns[-1].intent if turns else None,
        last_route=turns[-1].selected_route if turns else None,
        recent_document_titles=_unique([item.title for item in references], maximum_topics),
        recent_document_ids=_unique([item.document_id for item in references], maximum_topics),
        recent_incident_ids=_unique(incidents, maximum_identifiers),
        recent_service_names=_unique(services, maximum_topics),
        recent_departments=_unique([item.department for item in references], maximum_topics),
        recent_document_types=_unique([item.document_type for item in references], maximum_topics),
        recent_evidence_ids=_unique([item.evidence_id for item in references], maximum_identifiers),
        recent_warnings=_unique(
            [warning for turn in turns for warning in turn.warnings], maximum_topics
        ),
        turn_count=len(turns),
    )


def resolve_followup(
    query: str, context: MemoryContext, *, maximum: int = 4_000
) -> tuple[str, bool, bool]:
    detected = bool(_FOLLOWUP.search(query))
    if extract_enterprise_identifiers(query):
        return query, detected, False
    if not detected or context.turn_count == 0:
        return query, detected, False
    lowered = query.casefold()
    if (
        context.last_user_question
        and any(term in lowered for term in ("that", "previous", "again"))
        and not contains_untrusted_instruction(context.last_user_question)
    ):
        resolved = (
            "Explain again, in simpler terms, the answer to this prior user question: "
            f"{context.last_user_question}"
        )
        return resolved[:maximum], True, True
    additions: list[str] = []
    if "second" in lowered and len(context.recent_document_titles) >= 2:
        additions.append(context.recent_document_titles[1])
    elif "first" in lowered and context.recent_document_titles:
        additions.append(context.recent_document_titles[0])
    elif "runbook" in lowered:
        runbooks = [
            title for title in context.recent_document_titles if "runbook" in title.casefold()
        ]
        if len(runbooks) == 1:
            additions.extend(runbooks)
    elif "incident" in lowered and context.recent_incident_ids:
        additions.extend(context.recent_incident_ids)
    elif "same service" in lowered and context.recent_service_names:
        additions.extend(context.recent_service_names)
    if not additions:
        return query, True, False
    enriched = f"{query} Context references: {'; '.join(additions)}"
    return enriched[:maximum], True, True
