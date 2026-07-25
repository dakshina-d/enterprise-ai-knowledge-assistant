"""Bounded server-owned recognition of explicit aggregate-analysis intent."""

import re

_AGGREGATE_INTENT = (
    re.compile(r"\bcount\b", re.I),
    re.compile(r"\bhow many\b", re.I),
    re.compile(r"\b(?:distribution|frequency|statistics)\b", re.I),
    re.compile(r"\brecurring root causes?\b", re.I),
    re.compile(r"\bgroup by\b", re.I),
    re.compile(r"\btrend(?:s)? across\b", re.I),
    re.compile(r"\bcompare\b.{0,80}\b(?:counts?|totals?)\b", re.I),
    re.compile(r"\b(?:average|maximum|minimum)\b", re.I),
    re.compile(r"\bsummari[sz]e categories\b", re.I),
    re.compile(r"\bmost often\b", re.I),
    re.compile(r"\b(?:per month|monthly)\b", re.I),
    re.compile(r"\b(?:calculate|statistical analysis|spreadsheet|python analysis)\b", re.I),
)


def has_explicit_aggregate_intent(text: str) -> bool:
    """Return whether text explicitly requests a bounded aggregate operation."""
    bounded = text[:4_000]
    return any(pattern.search(bounded) for pattern in _AGGREGATE_INTENT)
