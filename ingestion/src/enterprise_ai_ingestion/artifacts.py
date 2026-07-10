"""Canonical serialization and transactional managed-artifact replacement."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel

from enterprise_ai_ingestion.exceptions import TransactionalWriteError
from enterprise_ai_ingestion.models import ArtifactBundle

MANAGED_ARTIFACTS = {"documents.jsonl", "chunks.jsonl", "ingestion_manifest.json"}


def canonical_json(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def jsonl(records: tuple[BaseModel, ...]) -> bytes:
    return ("\n".join(canonical_json(record) for record in records) + "\n").encode("utf-8")


def write_transactionally(bundle: ArtifactBundle, output_root: Path) -> None:
    """Validate-before-call bundle swap with rollback on directory replacement failure."""
    parent = output_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".processed-build-", dir=parent))
    backup = parent / f".{output_root.name}-backup"
    try:
        if output_root.exists():
            for existing in output_root.iterdir():
                if existing.name in MANAGED_ARTIFACTS:
                    continue
                destination = temp / existing.name
                if existing.is_dir():
                    shutil.copytree(existing, destination, symlinks=True)
                else:
                    shutil.copy2(existing, destination, follow_symlinks=False)
        for filename, content in bundle.files.items():
            if filename not in MANAGED_ARTIFACTS:
                raise TransactionalWriteError("attempted to write an unmanaged artifact")
            (temp / filename).write_bytes(content)
        if backup.exists():
            shutil.rmtree(backup)
        if output_root.exists():
            os.replace(output_root, backup)
        try:
            os.replace(temp, output_root)
        except OSError:
            if backup.exists() and not output_root.exists():
                os.replace(backup, output_root)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except (OSError, TransactionalWriteError) as error:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise TransactionalWriteError("transactional artifact replacement failed") from error
