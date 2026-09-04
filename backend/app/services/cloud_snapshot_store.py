"""Persistent full-log snapshots downloaded from remote providers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..core.runtime import user_data_root


class CloudSnapshotStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or user_data_root()) / "cloud_snapshots"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str) -> Path:
        return self.root / f"{provider.lower()}.json"

    def save(self, provider: str, records: Iterable[Dict[str, Any]], metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        rows = list(records)
        payload = {
            "provider": provider.upper(),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "records": rows,
            "metadata": metadata or {},
        }
        path = self._path(provider)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        temp.replace(path)
        return self.summary(provider)

    def load(self, provider: str) -> Dict[str, Any]:
        path = self._path(provider)
        if not path.exists():
            return {"provider": provider.upper(), "downloaded_at": None, "records": [], "metadata": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def summary(self, provider: str) -> Dict[str, Any]:
        payload = self.load(provider)
        return {
            "provider": provider.upper(),
            "downloaded_at": payload.get("downloaded_at"),
            "records": len(payload.get("records") or []),
            "metadata": payload.get("metadata") or {},
        }

    def all_summaries(self, providers: Iterable[str]) -> List[Dict[str, Any]]:
        return [self.summary(provider) for provider in providers]

    def backup(self, provider: str) -> Path | None:
        path = self._path(provider)
        if not path.exists():
            return None
        backup_dir = self.root / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{provider.lower()}-{stamp}.json"
        target.write_bytes(path.read_bytes())
        return target
