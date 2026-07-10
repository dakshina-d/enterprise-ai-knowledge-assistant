"""Provider-neutral deterministic lexical token estimation."""

import re
from typing import Protocol

TOKEN_PATTERN = re.compile(r"\w+(?:[-'\N{RIGHT SINGLE QUOTATION MARK}]\w+)*|[^\w\s]", re.UNICODE)


class TokenEstimator(Protocol):
    name: str
    version: str

    def tokens(self, text: str) -> tuple[str, ...]: ...

    def count(self, text: str) -> int: ...


class RegexTokenEstimator:
    """Counts lexical words and standalone punctuation; not model tokens."""

    name = "unicode-regex-lexical-estimator"
    version = "1.0"

    def tokens(self, text: str) -> tuple[str, ...]:
        return tuple(TOKEN_PATTERN.findall(text))

    def count(self, text: str) -> int:
        return len(self.tokens(text))
