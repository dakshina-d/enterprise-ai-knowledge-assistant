"""Focused tests for the offline Markdown link checker."""

from pathlib import Path

from scripts.check_documentation_links import broken_links


def test_checker_accepts_relative_file_and_anchor(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "target.md").write_text("# Target\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[local](docs/target.md#section) [external](https://example.test/page)\n",
        encoding="utf-8",
    )
    assert broken_links(tmp_path) == ()


def test_checker_rejects_missing_and_escaping_links(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "[missing](docs/missing.md) [escape](../private.md)\n",
        encoding="utf-8",
    )
    failures = broken_links(tmp_path)
    assert any("missing" in failure for failure in failures)
    assert any("escapes root" in failure for failure in failures)
