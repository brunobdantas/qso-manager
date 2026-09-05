"""Small persistent activity history for connected QSO Manager workflows."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.runtime import user_data_root


class QSOManagerActivityStore:
    _lock = threading.RLock()

    def __init__(self, root: Optional[Path] = None) -> None:
        base = Path(root or user_data_root()) / "activity"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "qso-manager.jsonl"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def append(self, kind: str, summary: str, details: Optional[Dict[str, Any]] = None, status: str = "OK") -> Dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex,
            "timestamp": self._now(),
            "kind": str(kind).upper(),
            "summary": summary,
            "status": status,
            "details": details or {},
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return event

    def list(self, limit: int = 200, kind: str = "") -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        events: List[Dict[str, Any]] = []
        kind = kind.strip().upper()
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except Exception:
                continue
            if kind and str(item.get("kind") or "").upper() != kind:
                continue
            events.append(item)
            if len(events) >= max(1, min(int(limit), 1000)):
                break
        return events
