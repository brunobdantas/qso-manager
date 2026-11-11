"""Shared snapshot freshness semantics for UI and issue prioritization."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional


def _timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_snapshot_freshness(
    summaries: Mapping[str, Mapping[str, Any]],
    providers: Iterable[str],
    *,
    now: Optional[datetime] = None,
    max_age_hours: float = 24.0,
    max_lag_hours: float = 6.0,
) -> Dict[str, Dict[str, Any]]:
    """Classify snapshots without treating an old comparison as a live gap.

    A source is stale when it is older than the wall-clock threshold or trails
    the newest loaded comparison snapshot by more than the lag threshold.
    """
    names = [str(provider).upper() for provider in providers]
    parsed = {name: _timestamp((summaries.get(name) or {}).get("downloaded_at")) for name in names}
    loaded = [stamp for stamp in parsed.values() if stamp is not None]
    latest = max(loaded) if loaded else None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: Dict[str, Dict[str, Any]] = {}
    for name in names:
        stamp = parsed[name]
        if stamp is None:
            out[name] = {
                "state": "NOT_LOADED",
                "age_hours": None,
                "lag_hours": None,
                "stale_by_age": False,
                "stale_by_lag": False,
            }
            continue
        age = max(0.0, (current - stamp).total_seconds() / 3600.0)
        lag = max(0.0, ((latest - stamp).total_seconds() / 3600.0) if latest else 0.0)
        stale_by_age = age > max_age_hours
        stale_by_lag = lag > max_lag_hours
        out[name] = {
            "state": "STALE" if stale_by_age or stale_by_lag else "CURRENT",
            "age_hours": round(age, 1),
            "lag_hours": round(lag, 1),
            "stale_by_age": stale_by_age,
            "stale_by_lag": stale_by_lag,
        }
    return out
