"""Conservative deterministic redaction for stored conversation text."""

import re

REDACTED = "[REDACTED]"
_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|authorization)\s*[:=]\s*\S+"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.S,
    ),
)


def sanitize_text(value: str, *, enabled: bool = True) -> str:
    if not enabled:
        return value
    result = value
    for pattern in _PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result
