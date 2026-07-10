"""Validate the deterministic synthetic sample-document corpus."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "sample_documents"
MANIFEST = CORPUS / "manifest.json"
FIXTURES = ROOT / "data" / "security_fixtures"
REQUIRED_DIRECTORIES = {
    "policies",
    "architecture",
    "runbooks",
    "incidents",
    "product_specifications",
    "meeting_notes",
}
REQUIRED_FIELDS = {
    "document_id",
    "title",
    "source",
    "department",
    "document_type",
    "access_level",
    "allowed_roles",
    "created_date",
    "updated_date",
    "version",
    "owner",
    "status",
    "tags",
    "related_document_ids",
}
REQUIRED_DEPARTMENTS = {
    "payments",
    "digital_banking",
    "cybersecurity",
    "infrastructure",
    "operations",
    "risk_and_compliance",
    "customer_service",
    "data_and_analytics",
}
VALID_STATUSES = {
    "approved",
    "active",
    "draft",
    "superseded",
    "archived",
    "final",
    "post_incident_final",
}
MINIMUM_WORDS = {
    "policy": 350,
    "architecture": 350,
    "runbook": 350,
    "incident": 400,
    "product_specification": 350,
    "meeting_note": 300,
}
DENIED_ORGANIZATIONS = {
    "commercial bank of ceylon",
    "hatton national bank",
    "sampath bank",
    "people's bank sri lanka",
    "seylan bank",
}
SENSITIVE_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}"),
    "api key": re.compile(r"\b(?:sk-|AIza)[A-Za-z0-9_-]{16,}"),
    "password assignment": re.compile(r"(?i)\bpassword\s*[=:]\s*[^\s\[<]{4,}"),
    "public IPv4": re.compile(r"\b(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-5])(?:\.(?:\d{1,3})){3}\b"),
    "real-domain email": re.compile(
        r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|test)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    "account identifier": re.compile(
        r"(?i)\b(?:account|customer)[ -]?(?:number|id)\s*[:=]\s*\d{8,16}\b"
    ),
}


class ValidationFailure(ValueError):
    """One or more corpus invariants failed."""


def parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise ValidationFailure("Markdown document is missing YAML front matter")
    try:
        raw, body = text[4:].split("\n---\n", maxsplit=1)
    except ValueError as error:
        raise ValidationFailure("YAML front matter is not terminated") from error
    metadata: dict[str, object] = {}
    active_list: list[object] | None = None
    for line in raw.splitlines():
        if line.startswith("  - "):
            if active_list is None:
                raise ValidationFailure("front-matter list item has no key")
            active_list.append(json.loads(line[4:]))
            continue
        key, separator, encoded = line.partition(":")
        if not separator:
            raise ValidationFailure(f"invalid front-matter line: {line}")
        if not encoded.strip():
            active_list = []
            metadata[key] = active_list
        else:
            active_list = None
            metadata[key] = json.loads(encoded.strip())
    return metadata, body.lstrip("\n")


def validate() -> dict[str, object]:
    errors: list[str] = []
    for directory in REQUIRED_DIRECTORIES:
        if not (CORPUS / directory).is_dir():
            errors.append(f"missing required directory: {directory}")
    if not MANIFEST.is_file():
        raise ValidationFailure("manifest.json is missing")
    manifest: list[dict[str, Any]] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids: set[str] = set()
    paths: set[str] = set()
    relationship_count = 0
    type_counts: Counter[str] = Counter()
    department_counts: Counter[str] = Counter()
    access_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    markdown_files = {
        path.relative_to(ROOT).as_posix()
        for directory in REQUIRED_DIRECTORIES
        for path in (CORPUS / directory).glob("*.md")
    }
    for entry in manifest:
        path_text = str(entry.get("file_path", ""))
        if Path(path_text).is_absolute() or "\\" in path_text:
            errors.append(f"non-portable path: {path_text}")
            continue
        if path_text in paths:
            errors.append(f"duplicate file path: {path_text}")
        paths.add(path_text)
        path = ROOT / path_text
        if not path.is_file():
            errors.append(f"manifest file missing: {path_text}")
            continue
        if FIXTURES in path.parents:
            errors.append(f"security fixture appears in valid manifest: {path_text}")
        try:
            metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
            _validate_entry(entry, metadata, body)
        except (ValidationFailure, ValueError, TypeError, json.JSONDecodeError) as error:
            errors.append(f"{path_text}: {error}")
            continue
        document_id = str(metadata["document_id"])
        if document_id in ids:
            errors.append(f"duplicate document ID: {document_id}")
        ids.add(document_id)
        related_value = metadata["related_document_ids"]
        roles_value = metadata["allowed_roles"]
        if not isinstance(related_value, list) or not isinstance(roles_value, list):
            errors.append(f"{path_text}: relationship and role metadata must be lists")
            continue
        related = [str(value) for value in related_value]
        relationship_count += len(related)
        type_counts[str(metadata["document_type"])] += 1
        department_counts[str(metadata["department"])] += 1
        access_counts[str(metadata["access_level"])] += 1
        role_counts.update(str(role) for role in roles_value)
        statuses[str(metadata["status"])] += 1
    if paths != markdown_files:
        errors.append("manifest and valid Markdown file sets differ")
    for entry in manifest:
        for related in entry.get("related_document_ids", []):
            if related not in ids:
                errors.append(f"broken relationship from {entry.get('document_id')} to {related}")
    if set(department_counts) != REQUIRED_DEPARTMENTS:
        errors.append("required department coverage is incomplete")
    if set(type_counts) != {item.value for item in DocumentType}:
        errors.append("required document-type coverage is incomplete")
    if set(access_counts) != {item.value for item in AccessLevel}:
        errors.append("required access-level coverage is incomplete")
    if set(role_counts) != {item.value for item in UserRole}:
        errors.append("required role coverage is incomplete")
    _validate_evaluation(ids, errors)
    _validate_fixtures(errors)
    if errors:
        raise ValidationFailure("\n".join(errors))
    incidents = [entry for entry in manifest if entry["document_type"] == "incident"]
    payment_incidents = [entry for entry in incidents if entry["payment_related"]]
    return {
        "total": len(manifest),
        "by_type": dict(sorted(type_counts.items())),
        "by_department": dict(sorted(department_counts.items())),
        "by_access": dict(sorted(access_counts.items())),
        "by_role": dict(sorted(role_counts.items())),
        "incidents": len(incidents),
        "payment_incidents": len(payment_incidents),
        "incident_date_range": [
            min(item["created_date"] for item in incidents),
            max(item["created_date"] for item in incidents),
        ],
        "root_causes": sorted({item["root_cause_category"] for item in incidents}),
        "statuses": dict(sorted(statuses.items())),
        "relationships": relationship_count,
    }


def _validate_entry(entry: dict[str, Any], metadata: dict[str, object], body: str) -> None:
    missing = REQUIRED_FIELDS - metadata.keys()
    if missing:
        raise ValidationFailure(f"missing metadata: {sorted(missing)}")
    UUID(str(metadata["document_id"]))
    document_type = DocumentType(str(metadata["document_type"]))
    AccessLevel(str(metadata["access_level"]))
    roles = metadata["allowed_roles"]
    if not isinstance(roles, list) or not roles:
        raise ValidationFailure("allowed_roles must be a non-empty list")
    for role in roles:
        UserRole(str(role))
    if str(metadata["department"]) not in REQUIRED_DEPARTMENTS:
        raise ValidationFailure("unknown department")
    if str(metadata["status"]) not in VALID_STATUSES:
        raise ValidationFailure("unknown status")
    created = date.fromisoformat(str(metadata["created_date"]))
    updated = date.fromisoformat(str(metadata["updated_date"]))
    if updated < created:
        raise ValidationFailure("updated_date precedes created_date")
    for field in REQUIRED_FIELDS:
        if entry.get(field) != metadata[field]:
            raise ValidationFailure(f"manifest mismatch for {field}")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if entry.get("content_hash") != digest:
        raise ValidationFailure("content hash mismatch")
    words = len(re.findall(r"\b[\w-]+\b", body))
    if entry.get("approximate_word_count") != words or words < MINIMUM_WORDS[document_type.value]:
        raise ValidationFailure(f"word count is invalid or too small: {words}")
    lowered = body.casefold()
    for organization in DENIED_ORGANIZATIONS:
        if organization in lowered:
            raise ValidationFailure(f"real organization denylist match: {organization}")
    for name, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(body):
            raise ValidationFailure(f"credential/sensitive-data pattern: {name}")


def _validate_evaluation(ids: set[str], errors: list[str]) -> None:
    questions: list[dict[str, Any]] = json.loads(
        (ROOT / "data/evaluation/research_questions.json").read_text(encoding="utf-8")
    )
    cases: list[dict[str, Any]] = json.loads(
        (ROOT / "data/evaluation/access_control_cases.json").read_text(encoding="utf-8")
    )
    if (
        len(questions) < 12
        or sum(
            item["expected_route"]
            in {"recursive_research", "cross_document_synthesis", "structured_analysis"}
            for item in questions
        )
        < 5
    ):
        errors.append("research benchmark coverage is insufficient")
    if not any(item["question"].startswith("Summarize all outage reports") for item in questions):
        errors.append("required outage benchmark question is missing")
    for collection in (questions, cases):
        for item in collection:
            references = item.get("relevant_document_ids", [item.get("document_id")])
            if any(reference not in ids for reference in references):
                errors.append("evaluation dataset references an unknown document")


def _validate_fixtures(errors: list[str]) -> None:
    fixture_manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    fixture_files = {path.relative_to(ROOT).as_posix() for path in FIXTURES.glob("*.md")}
    if {entry["file_path"] for entry in fixture_manifest} != fixture_files:
        errors.append("security fixture manifest mismatch")
    if any(entry["included_in_valid_manifest"] for entry in fixture_manifest):
        errors.append("security fixture incorrectly marked valid")


def main() -> int:
    try:
        summary = validate()
    except (ValidationFailure, OSError, json.JSONDecodeError) as error:
        print(f"Sample-data validation failed:\n{error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
