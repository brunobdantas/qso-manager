"""Persistent full-log snapshots downloaded from remote providers."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..core.runtime import user_data_root


class CloudSnapshotStore:
    _shared_summaries = {}
    _shared_lock = threading.RLock()

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or user_data_root()) / "cloud_snapshots"
        self.root.mkdir(parents=True, exist_ok=True)
        self._summary_cache: Dict[str, tuple[tuple[int, int] | None, Dict[str, Any]]] = {}

    def _path(self, provider: str) -> Path:
        return self.root / f"{provider.lower()}.json"

    def _summary_path(self, provider: str) -> Path:
        return self.root / f"{provider.lower()}.summary.json"

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
        summary = {"provider": provider.upper(), "downloaded_at": payload["downloaded_at"], "records": len(rows), "metadata": payload["metadata"]}
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        meta = self._summary_path(provider)
        tmp = meta.with_suffix(".tmp")
        tmp.write_text(json.dumps({"signature": signature, "summary": summary}, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(meta)
        self._summary_cache[provider.upper()] = (signature, summary)
        with self._shared_lock:
            self._shared_summaries[str(path.resolve())] = (signature, summary)
        return dict(summary)

    def load(self, provider: str) -> Dict[str, Any]:
        path = self._path(provider)
        if not path.exists():
            return {"provider": provider.upper(), "downloaded_at": None, "records": [], "metadata": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def summary(self, provider: str) -> Dict[str, Any]:
        provider = provider.upper()
        path = self._path(provider)
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            signature = None
        key = str(path.resolve())
        cached = self._summary_cache.get(provider)
        if cached is None or cached[0] != signature:
            with self._shared_lock:
                cached = self._shared_summaries.get(key)
        if cached is not None and cached[0] == signature:
            self._summary_cache[provider] = cached
            return dict(cached[1])
        summary = None
        meta = self._summary_path(provider)
        if signature is not None and meta.exists():
            try:
                content = json.loads(meta.read_text(encoding="utf-8"))
                if tuple(content.get("signature") or ()) == signature:
                    summary = content.get("summary")
            except (ValueError, OSError, TypeError):
                pass
        if summary is None:
            payload = self.load(provider)
            summary = {
                "provider": provider,
                "downloaded_at": payload.get("downloaded_at"),
                "records": len(payload.get("records") or []),
                "metadata": payload.get("metadata") or {},
            }
            if signature is not None:
                try:
                    temp = meta.with_suffix(".tmp")
                    temp.write_text(json.dumps({"signature": signature, "summary": summary}, ensure_ascii=False, default=str), encoding="utf-8")
                    temp.replace(meta)
                except OSError:
                    pass
        cached = (signature, dict(summary))
        self._summary_cache[provider] = cached
        with self._shared_lock:
            self._shared_summaries[key] = cached
        return dict(summary)

    def all_summaries(self, providers: Iterable[str]) -> List[Dict[str, Any]]:
        return [self.summary(provider) for provider in providers]

    def clear(self, provider: str) -> Dict[str, Any]:
        """Remove only the active local snapshot for a provider.

        Credentials, remote data and historical backups are intentionally left
        untouched. This makes the operation reversible from a UX perspective:
        the user can simply synchronize the provider again.
        """
        provider = provider.upper()
        before = self.summary(provider)
        path = self._path(provider)
        existed = path.exists()
        if existed:
            path.unlink()
        self._summary_path(provider).unlink(missing_ok=True)
        self._summary_cache.pop(provider, None)
        with self._shared_lock:
            self._shared_summaries.pop(str(path.resolve()), None)
        return {
            "provider": provider,
            "cleared": existed,
            "records_removed": before.get("records", 0),
            "remote_affected": False,
            "credentials_affected": False,
            "backups_affected": False,
            "snapshot": self.summary(provider),
        }

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
