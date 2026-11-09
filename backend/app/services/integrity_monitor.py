"""Opt-in continuous integrity monitoring while the desktop backend is running.

No remote mutation is performed by the scheduler. Repeated provider failures
are held for manual review instead of retrying indefinitely.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from .integrity_service import IntegrityStore, IntegrityService


class IntegrityMonitor:
    _guard = threading.RLock()
    _thread: Optional[threading.Thread] = None
    _stop = threading.Event()

    @classmethod
    def settings(cls):
        store = IntegrityStore()
        enabled = bool(store.setting("monitor_enabled", False))
        hours = max(6, min(168, int(store.setting("monitor_interval_hours", 12))))
        last_started = float(store.setting("monitor_last_started", 0) or 0)
        cooldown = max(0, hours * 3600 - (time.time() - last_started))
        errors = store.errors()
        blocked = [p for p, e in errors.items()
                   if e["active"] and
                   (e["classification"] in {"AUTH", "UNSUPPORTED", "RATE_LIMIT"} or e["failures"] >= 3)]
        return {
            "enabled": enabled, "interval_hours": hours,
            "last_started": datetime.fromtimestamp(last_started, timezone.utc).isoformat() if last_started else None,
            "next_due_seconds": round(cooldown) if enabled else None,
            "blocked_providers": blocked,
            "scope": "Apenas enquanto o QSO Manager estiver aberto; sincronização somente leitura.",
        }

    @classmethod
    def configure(cls, enabled: bool, interval_hours: int = 12):
        hours = max(6, min(168, int(interval_hours)))
        store = IntegrityStore()
        was_enabled = bool(store.setting("monitor_enabled", False))
        store.set_setting("monitor_enabled", bool(enabled))
        store.set_setting("monitor_interval_hours", hours)
        if enabled and not was_enabled:
            # Schedule the first remote read after the selected interval.
            store.set_setting("monitor_last_started", time.time())
        if enabled:
            cls.start()
        return cls.settings()

    @classmethod
    def start(cls):
        with cls._guard:
            if cls._thread is not None and cls._thread.is_alive():
                return
            cls._stop.clear()
            cls._thread = threading.Thread(target=cls._loop, daemon=True, name="qso-integrity-monitor")
            cls._thread.start()

    @classmethod
    def _loop(cls):
        # No network request at app startup; first automatic refresh is due
        # interval_hours after the user opts in.
        while not cls._stop.wait(90):
            try:
                if cls.settings()["enabled"]:
                    engine = IntegrityService()
                    last = engine.store.scans(limit=1)
                    current = engine.signature()
                    if not last or last[0]["signature"] != current:
                        # Rebuild only after a changed local snapshot; no remote write.
                        engine.report(page=1, page_size=10)
                cls.tick()
            except Exception:
                # Monitoring must never bring down the local API.
                continue

    @classmethod
    def tick(cls):
        settings = cls.settings()
        if not settings["enabled"] or settings["next_due_seconds"] > 0:
            return {"started": False, "reason": "not_due_or_disabled"}
        from .parallel_sync_service import parallel_sync
        if parallel_sync.active():
            return {"started": False, "reason": "sync_in_progress"}
        from .v9_product_service import V9ProductService
        service = V9ProductService()
        errors = IntegrityStore().errors()
        blocked = set(settings["blocked_providers"])
        targets = [
            p for p in service.SYNC_PROVIDERS
            if p not in blocked and service._configured(p)
        ]
        if not targets:
            return {"started": False, "reason": "all_sources_blocked_or_unconfigured"}
        store = IntegrityStore()
        store.set_setting("monitor_last_started", time.time())
        started = parallel_sync.start(targets)
        return {"started": True, "job_id": started.get("job_id"), "targets": targets}

    @classmethod
    def snapshot_status(cls):
        # A lightweight signature check can be polled without parsing snapshots.
        engine = IntegrityService()
        latest = engine.store.scans(limit=1)
        signature = engine.signature()
        history = engine.store.scans(limit=2)
        delta = (int(history[0]["summary"].get("cases", 0)) -
                 int(history[1]["summary"].get("cases", 0))) if len(history) > 1 else None
        return {"current_signature": signature,
                "last_scanned_signature": latest[0]["signature"] if latest else None,
                "snapshot_changes_pending": not latest or latest[0]["signature"] != signature,
                "last_cases": latest[0]["summary"].get("cases") if latest else None,
                "net_case_variation": delta,
                "monitor": cls.settings()}
