"""Local transaction evidence and the existing SKILL receipt wire format.

This module never connects to Virtuoso. Request snapshots are immutable;
mutable journal records are replaced atomically. It is not a cross-process lock.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .model import LiteError, Workspace, digest


def checked_id(value: str, *, code: str = "INVALID_REQUEST_ID") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise LiteError(code)
    return value


def payload_hash(workspace: Workspace) -> str:
    """Keep the established hash contract; UI state is not transaction content."""
    return digest(
        {
            "library": workspace.baseline.library,
            "cell": workspace.baseline.cell,
            "baseline": workspace.baseline.semantic(),
            "operations": [op.model_dump() for op in workspace.operations],
        }
    )


def write_json_atomic(path: Path, value: Any, *, compact: bool = False) -> None:
    write_text_atomic(path,json.dumps(value,ensure_ascii=False,
        separators=(',',':') if compact else None,indent=None if compact else 2))


def write_text_atomic(path: Path, text: str) -> None:
    """Durably replace one file; callers may use a model's direct JSON encoder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Receipt:
    request_id: str
    payload_hash: str
    status: str
    library: str
    cell: str
    backup: str
    phase: Any = None

    @classmethod
    def parse(cls, raw, *, request_id, expected_hash, library, cell):
        """Decode nil or a 7/8-field colayout-lite-receipt-1 response."""
        if raw is None:
            return None
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) not in (7, 8)
            or raw[0] != "colayout-lite-receipt-1"
            or any(not isinstance(item, str) or not item for item in raw[1:7])
            or raw[3] not in {"applying", "saved", "rolled_back", "recovery_required"}
        ):
            raise LiteError("INVALID_RECEIPT", "服务器回执格式或状态不合法。")
        result = cls(*raw[1:7], phase=raw[7] if len(raw) == 8 else None)
        if (result.request_id, result.payload_hash, result.library, result.cell) != (
            request_id,
            expected_hash,
            library,
            cell,
        ):
            raise LiteError("RECEIPT_MISMATCH", "回执不属于当前请求、内容或目标。")
        return result


class TransactionJournal:
    """One immutable input snapshot and one mutable record per request ID."""

    def __init__(self, state: Path, request_id: str):
        self.request_id = checked_id(request_id)
        self.path = Path(state) / "transactions" / f"{request_id}.json"
        self.workspace_path = self.path.with_suffix(".workspace.json")

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(record, dict)
                or record.get("request_id") != self.request_id
                or not isinstance(record.get("hash"), str)
                or not record["hash"]
            ):
                raise ValueError("invalid transaction identity")
            return record
        except (ValueError, OSError) as exc:
            raise LiteError("INVALID_TRANSACTION_JOURNAL", str(self.path)) from exc

    def check(self, expected_hash: str) -> dict | None:
        record = self.read()
        if record is not None and record["hash"] != expected_hash:
            raise LiteError("REQUEST_ID_REUSED")
        # A crash may leave the snapshot before the journal is published.
        # Validate it as well, and never overwrite an incompatible snapshot.
        if self.workspace_path.exists():
            try:
                original = Workspace.model_validate_json(
                    self.workspace_path.read_text(encoding="utf-8")
                )
            except (ValueError, OSError) as exc:
                raise LiteError(
                    "INVALID_TRANSACTION_SNAPSHOT", str(self.workspace_path)
                ) from exc
            if payload_hash(original) != expected_hash:
                raise LiteError("REQUEST_ID_REUSED")
        return record

    def prepare(self, workspace: Workspace, expected_hash: str, backup: str) -> dict:
        self.check(expected_hash)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.workspace_path.exists():
            workspace.save(self.workspace_path)
        record = {
            "request_id": self.request_id,
            "hash": expected_hash,
            "status": "prepared",
            "workspace_path": str(self.workspace_path.resolve()),
            "workspace_id": workspace.id,
            "library": workspace.baseline.library,
            "cell": workspace.baseline.cell,
            "backup": backup,
        }
        self.write(record)
        return record

    def write(self, record: dict) -> None:
        write_json_atomic(self.path, record)
