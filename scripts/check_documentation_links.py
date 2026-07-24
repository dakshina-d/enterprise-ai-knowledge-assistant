"""Check repository-relative Markdown links without network access."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"!?\[[^\]]*]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^)]*['\"])?\)")


def documentation_files(root: Path) -> tuple[Path, ...]:
    files = [root / "README.md"]
    files.extend(sorted((root / "docs").rglob("*.md")))
    return tuple(path for path in files if path.is_file())


def broken_links(root: Path) -> tuple[str, ...]:
    failures: list[str] = []
    resolved_root = root.resolve()
    for document in documentation_files(resolved_root):
        content = document.read_text(encoding="utf-8")
        for match in LINK.finditer(content):
            raw_target = match.group("target").strip("<>")
            parts = urlsplit(raw_target)
            if parts.scheme in {"http", "https", "mailto"} or not parts.path:
                continue
            decoded = unquote(parts.path)
            candidate = (
                resolved_root / decoded.lstrip("/")
                if decoded.startswith("/")
                else document.parent / decoded
            ).resolve()
            try:
                candidate.relative_to(resolved_root)
            except ValueError:
                relative_document = document.relative_to(resolved_root)
                failures.append(f"{relative_document}: escapes root: {raw_target}")
                continue
            if not candidate.exists():
                failures.append(f"{document.relative_to(resolved_root)}: missing: {raw_target}")
    return tuple(failures)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = broken_links(root)
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"Documentation links passed: {len(documentation_files(root))} Markdown files.")


if __name__ == "__main__":
    main()
