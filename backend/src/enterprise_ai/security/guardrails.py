"""Bounded deterministic input, evidence, and public-response safety checks."""

import re
from typing import Literal

SecurityDenialCategory = Literal[
    "credential_exfiltration",
    "instruction_extraction",
    "privilege_escalation",
    "session_exfiltration",
    "tool_abuse",
]

_SECURITY_DENIALS: tuple[tuple[SecurityDenialCategory, re.Pattern[str]], ...] = (
    (
        "instruction_extraction",
        re.compile(r"\bignore (?:all |any )?(?:previous|prior|system) instructions?\b", re.I),
    ),
    (
        "privilege_escalation",
        re.compile(r"\bact as (?:an? )?(?:administrator|admin|system)\b", re.I),
    ),
    (
        "instruction_extraction",
        re.compile(
            r"\b(?:reveal|show|print|return|provide)\b.{0,120}"
            r"\b(?:system prompt|developer instructions?|hidden instructions?|"
            r"security policies|chain of thought|private reasoning)\b",
            re.I,
        ),
    ),
    (
        "tool_abuse",
        re.compile(r"\bcall (?:every|all) (?:available )?tools?\b", re.I),
    ),
    (
        "privilege_escalation",
        re.compile(
            r"\b(?:all|every) access levels?\b|"
            r"\b(?:upgrade|change|elevate) (?:my |the )?role\b|"
            r"\b(?:bypass|override) (?:access|authorization|permissions?)\b|"
            r"\bI am (?:the |an? )?(?:administrator|admin)\b.{0,100}"
            r"\b(?:restricted|upgrade|elevate)\b",
            re.I,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"\b(?:reveal|show|return|dump|print|expose|list|read)\b.{0,240}"
            r"\b(?:credentials?|api keys?|environment variables?|secrets?|passwords?|"
            r"access tokens?|jwt (?:claims?|secrets?|signing material)|connection strings?|"
            r"private configuration|\.env(?:\.[a-z0-9_-]+)?|filesystem|file path)\b",
            re.I,
        ),
    ),
    (
        "session_exfiltration",
        re.compile(r"\b(?:other|another) user(?:'s|s')? sessions?\b", re.I),
    ),
    (
        "credential_exfiltration",
        re.compile(r"\b(?:hack|steal credentials?)\b", re.I),
    ),
)
_DIRECT_ATTACKS = tuple(pattern for _, pattern in _SECURITY_DENIALS)

_UNTRUSTED_INSTRUCTIONS = (
    *_DIRECT_ATTACKS,
    re.compile(r"\boverride (?:authorization|permissions?|policy|identity)\b", re.I),
    re.compile(r"\bchange (?:the )?(?:user|identity|role|system policy)\b", re.I),
    re.compile(r"\bfabricate (?:a )?citations?\b", re.I),
    re.compile(r"\bcite\b.{0,80}\bwithout evidence\b", re.I),
    re.compile(
        r"\b(?:execute|invoke) (?:an? )?(?:unapproved )?(?:tool|command|shell|python)\b",
        re.I,
    ),
)

_PUBLIC_RESPONSE_VIOLATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("executable_content", re.compile(r"<\s*script|javascript:|https?://", re.I)),
    (
        "false_guarantee",
        re.compile(
            r"\b(?:we|I|the bank) guarantee(?:s|d)?\b|"
            r"\bguaranteed (?:approval|return|availability|outcome)\b",
            re.I,
        ),
    ),
    (
        "false_identity",
        re.compile(
            r"\bI am (?:an? )?(?:bank )?(?:employee|officer|advisor|representative)\b",
            re.I,
        ),
    ),
    (
        "invented_customer_fact",
        re.compile(
            r"\byour (?:account balance|account number|credit score|loan balance|"
            r"customer record)\b",
            re.I,
        ),
    ),
    (
        "unsupported_legal_certainty",
        re.compile(
            r"\b(?:legally guaranteed|definitely compliant|certainly lawful|"
            r"binding legal advice)\b",
            re.I,
        ),
    ),
    (
        "evidence_overclaim",
        re.compile(r"\bconfirmed fact\b.{0,80}\b(?:incomplete|insufficient) evidence\b", re.I),
    ),
)


def is_direct_prompt_attack(text: str) -> bool:
    """Return whether caller text explicitly attempts to override a trust boundary."""
    return any(pattern.search(text) for pattern in _DIRECT_ATTACKS)


def security_denial_category(text: str) -> SecurityDenialCategory | None:
    """Return a stable safe category without retaining or echoing the request."""
    bounded = text[:4_000]
    return next(
        (category for category, pattern in _SECURITY_DENIALS if pattern.search(bounded)),
        None,
    )


def contains_untrusted_instruction(text: str) -> bool:
    """Detect instruction-like content that must not enter model evidence context."""
    return any(pattern.search(text) for pattern in _UNTRUSTED_INSTRUCTIONS)


def response_policy_violations(text: str) -> tuple[str, ...]:
    """Return stable public-policy codes without retaining unsafe response text."""
    return tuple(code for code, pattern in _PUBLIC_RESPONSE_VIOLATIONS if pattern.search(text))
