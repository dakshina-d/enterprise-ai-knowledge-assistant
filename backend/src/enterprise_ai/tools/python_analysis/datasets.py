"""Authorized deterministic extraction from the committed incident corpus."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.exceptions import AnalysisDatasetError
from enterprise_ai.tools.python_analysis.models import IncidentAnalysisRow
from enterprise_ai.tools.python_analysis.taxonomy import classify_root_cause

_FIELD = {
    "incident_id": re.compile(r"\*\*Incident ID:\*\*\s*([^\n]+)"),
    "severity": re.compile(r"\*\*Severity:\*\*\s*([^\n]+)"),
    "start": re.compile(r"\*\*Start:\*\*\s*([^\n]+)"),
    "end": re.compile(r"\*\*End:\*\*\s*([^\n]+)"),
    "services": re.compile(r"\*\*Affected services:\*\*\s*([^\n]+)"),
}


def _section(body: str, heading: str) -> str | None:
    match = re.search(rf"## {re.escape(heading)}\s+(.*?)(?=\n## |\Z)", body, re.S)
    return match.group(1).strip() if match else None


def load_authorized_incidents(
    principal: AuthenticatedPrincipal,
    *,
    manifest_path: Path = Path("data/sample_documents/manifest.json"),
) -> tuple[tuple[IncidentAnalysisRow, ...], int]:
    authorization = AuthorizationService()
    root = manifest_path.resolve().parent
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[IncidentAnalysisRow] = []
    excluded = 0
    for entry in raw_manifest:
        if entry.get("document_type") != "incident":
            continue
        candidate = Path(str(entry["file_path"])).resolve()
        expected_parent = (root / "incidents").resolve()
        if candidate.parent != expected_parent or candidate.is_symlink():
            raise AnalysisDatasetError("incident manifest path is invalid")
        text = candidate.read_text(encoding="utf-8")
        try:
            raw_yaml, body = text[4:].split("\n---\n", maxsplit=1)
            metadata = yaml.safe_load(raw_yaml)
        except (ValueError, yaml.YAMLError) as error:
            raise AnalysisDatasetError("incident document is malformed") from error
        if hashlib.sha256(body.encode()).hexdigest() != entry["content_hash"]:
            raise AnalysisDatasetError("incident document hash does not match manifest")
        from datetime import date

        from enterprise_ai.models.identity import AccessLevel, UserRole
        from enterprise_ai.models.retrieval import DocumentMetadata, DocumentType

        document = DocumentMetadata(
            document_id=entry["document_id"],
            title=entry["title"],
            source=entry["source"],
            department=entry["department"],
            document_type=DocumentType.INCIDENT,
            access_level=AccessLevel(entry["access_level"]),
            allowed_roles=frozenset(UserRole(role) for role in entry["allowed_roles"]),
            created_date=date.fromisoformat(entry["created_date"]),
            updated_date=date.fromisoformat(entry["updated_date"]),
            version=entry["version"],
            content_hash=entry["content_hash"],
        )
        if not authorization.is_document_authorized(principal, document):
            excluded += 1
            continue
        values = {name: pattern.search(body) for name, pattern in _FIELD.items()}
        start = (
            datetime.fromisoformat(values["start"].group(1).strip()) if values["start"] else None
        )
        end = datetime.fromisoformat(values["end"].group(1).strip()) if values["end"] else None
        if start and end and end < start:
            raise AnalysisDatasetError("incident timestamp range is invalid")
        root_text = _section(body, "Technical root cause")
        followup = _section(body, "Owners and follow-up status")
        rows.append(
            IncidentAnalysisRow(
                document_id=document.document_id,
                incident_id=values["incident_id"].group(1).strip()
                if values["incident_id"]
                else None,
                title=document.title,
                department=document.department,
                access_level=document.access_level,
                allowed_roles=document.allowed_roles,
                status=str(metadata["status"]),
                created_date=document.created_date,
                source_file=str(entry["file_path"]),
                severity=values["severity"].group(1).strip() if values["severity"] else None,
                start_time=start,
                end_time=end,
                duration_minutes=(end - start).total_seconds() / 60 if start and end else None,
                affected_services=tuple(
                    part.strip() for part in values["services"].group(1).split(",")
                )
                if values["services"]
                else (),
                root_cause_category=str(
                    entry.get("root_cause_category") or classify_root_cause(root_text)
                ),
                corrective_action_status=(
                    followup.split("status is **", 1)[1].split("**", 1)[0]
                    if followup and "status is **" in followup
                    else None
                ),
            )
        )
    return tuple(rows), excluded
