"""Persistent comparison scope for logbook sources.

Scope is intentionally independent from connection and snapshot state: a source
can stay configured and preserved locally while being excluded from comparison.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from ..core.runtime import user_data_root


class SourceScopeStore:
    ACTIVE = "ACTIVE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    VALID = {ACTIVE, OUT_OF_SCOPE}
    DEFAULTS = {"HRD": OUT_OF_SCOPE}
    _lock = threading.RLock()

    def __init__(self, root: Optional[Path] = None) -> None:
        folder = Path(root or user_data_root()) / "settings"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "source-scopes.json"

    def _read(self) -> Dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(provider).upper(): str(scope).upper()
            for provider, scope in payload.items()
            if str(scope).upper() in self.VALID
        }

    def get(self, provider: str) -> str:
        provider = str(provider or "").strip().upper()
        with self._lock:
            return self._read().get(provider, self.DEFAULTS.get(provider, self.ACTIVE))

    def set(self, provider: str, scope: str) -> str:
        provider = str(provider or "").strip().upper()
        scope = str(scope or "").strip().upper()
        if scope not in self.VALID:
            raise ValueError("Escopo inválido; use ACTIVE ou OUT_OF_SCOPE")
        if provider == "QRZ" and scope != self.ACTIVE:
            raise ValueError("O QRZ é a referência e não pode ser retirado do escopo")
        with self._lock:
            payload = self._read()
            payload[provider] = scope
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)
        return scope

    def signature(self) -> tuple[int | None, int | None]:
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None, None
