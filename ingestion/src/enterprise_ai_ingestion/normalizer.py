"""Conservative line-preserving Markdown normalization."""

import re
import unicodedata
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.*)$")


@dataclass(frozen=True, slots=True)
class NormalizedLine:
    text: str
    source_line: int


def normalize_body(body: str, *, source_line_start: int) -> tuple[str, tuple[NormalizedLine, ...]]:
    """Normalize without rewriting content meaning or structural blocks."""
    canonical = unicodedata.normalize("NFC", body.replace("\r\n", "\n").replace("\r", "\n"))
    output: list[NormalizedLine] = []
    blank_count = 0
    for offset, raw_line in enumerate(canonical.splitlines()):
        line = raw_line.rstrip()
        heading = HEADING.match(line)
        if heading:
            line = f"{heading.group(1)} {heading.group(2)}"
        list_item = LIST_ITEM.match(line)
        if list_item:
            indentation = " " * (len(list_item.group(1).expandtabs(2)) // 2 * 2)
            line = f"{indentation}{list_item.group(2)} {list_item.group(3)}"
        if not line:
            blank_count += 1
            if blank_count > 2:
                continue
        else:
            blank_count = 0
        output.append(NormalizedLine(line, source_line_start + offset))
    while output and not output[-1].text:
        output.pop()
    normalized = "\n".join(item.text for item in output) + "\n"
    return normalized, tuple(output)
