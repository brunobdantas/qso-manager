"""Persistent, local-only cache for expensive product bootstrap analysis.

Only derived workspace/QSL data is cached; credentials and status are always
read fresh. A cache is valid only for the exact set of snapshot file signatures.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .cloud_snapshot_store import CloudSnapshotStore


class BootstrapCache:
    PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD")
    _lock = threading.RLock()

    def __init__(self, snapshots: CloudSnapshotStore) -> None:
        self.snapshots = snapshots
        self.path: Path = snapshots.root / "bootstrap-analysis.v1.json.gz"

    def signature(self) -> list[list[Any]]:
        signatures: list[list[Any]] = []
        for provider in self.PROVIDERS:
            path = self.snapshots._path(provider)
            try:
                stat = path.stat()
                signatures.append([provider, stat.st_mtime_ns, stat.st_size])
            except FileNotFoundError:
                signatures.append([provider, None, None])
        return signatures

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.path.exists() or self.path.stat().st_size > 50_000_000:
                return None
            with gzip.open(self.path, "rt", encoding="utf-8") as stream:
                stored = json.load(stream)
            if stored.get("signature") != self.signature():
                return None
            payload = stored.get("payload")
            if not isinstance(payload, dict) or not all(
                key in payload for key in ("dashboard", "workspace", "qsl", "issues")
            ):
                return None
            return payload
        except (OSError, EOFError, ValueError, TypeError, KeyError):
            return None

    def save(self, payload: Dict[str, Any], expected_signature: list[list[Any]]) -> None:
        if self.signature() != expected_signature:
            return  # A remote sync changed a snapshot while we were analyzing it.
        temp = self.path.with_suffix(".tmp")
        try:
            with gzip.open(temp, "wt", encoding="utf-8", compresslevel=2) as stream:
                json.dump({"signature": expected_signature, "payload": payload},
                          stream, ensure_ascii=False, default=str)
            if self.signature() == expected_signature:
                os.replace(temp, self.path)
            else:
                temp.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            temp.unlink(missing_ok=True)
