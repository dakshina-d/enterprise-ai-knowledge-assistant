"""Versioned Unicode lexical analyzer preserving structured identifiers."""

import re
import unicodedata

ANALYZER_NAME = "unicode-identifier-analyzer"
ANALYZER_VERSION = "1.0"
STOP_WORD_VERSION = "none-1.0"
TOKEN = re.compile(r"[\w]+(?:[-][\w]+)*", re.UNICODE)


def analyze(text: str, *, maximum_tokens: int | None = None) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFC", " ".join(text.split())).casefold()
    tokens: list[str] = []
    for match in TOKEN.finditer(normalized):
        value = match.group(0)
        tokens.append(value)
        if "-" in value or "_" in value:
            tokens.extend(part for part in re.split(r"[-_]", value) if part and part != value)
        if maximum_tokens is not None and len(tokens) > maximum_tokens:
            raise ValueError("analyzed query exceeds configured token limit")
    return tuple(tokens)
