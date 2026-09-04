"""Performance-oriented subclass for large two-ADIF comparisons."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from .adif_comparison_service import ADIFComparisonService, QSO


class FastADIFComparisonService(ADIFComparisonService):
    """Keep comparison semantics while avoiding O(n²) duplicate scans."""

    def _probable_duplicates(self, rows: List[QSO]) -> List[Dict[str, Any]]:
        buckets = defaultdict(list)
        for q in rows:
            buckets[(q.call, q.date, q.band)].append(q)

        groups: List[Dict[str, Any]] = []
        for bucket in buckets.values():
            bucket.sort(key=lambda q: (q.seconds if q.seconds is not None else 10**9, q.index))
            used = set()
            for i, q in enumerate(bucket):
                if q.index in used or q.seconds is None:
                    continue
                members = [q]
                for other in bucket[i + 1:]:
                    if other.index in used or other.seconds is None:
                        continue
                    delta = other.seconds - q.seconds
                    if delta > 2:
                        break
                    if delta < 0:
                        continue
                    if not self._mode_compatible(q, other):
                        continue
                    if q.freq_hz is not None and other.freq_hz is not None:
                        if abs(q.freq_hz - other.freq_hz) > self._freq_tolerance(q, other):
                            continue
                    if q.rst_sent != other.rst_sent or q.rst_rcvd != other.rst_rcvd:
                        continue
                    if (q.grid or "").upper() != (other.grid or "").upper():
                        continue
                    members.append(other)

                if len(members) > 1:
                    for member in members:
                        used.add(member.index)
                    groups.append({"indexes": [member.index for member in members], "records": members})
        return groups
