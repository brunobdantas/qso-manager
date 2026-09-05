"""Unified QSO Manager workspace over QRZ, WRL, Club Log and eQSL snapshots.

The workspace intentionally works from the locally downloaded snapshots.  It
builds one logical QSO row from matching provider records, keeps the exact
provider/index references needed for safe remote actions, and exposes the
search/filter/sort/export primitives used by the desktop UI.
"""
from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..adapters.cloud_logs import PROVIDERS, records_to_adif
from .cloud_hub_fast_service import CloudHubService
from .fast_adif_comparison_service import FastADIFComparisonService


class QSOManagerWorkspace:
    PROVIDER_ORDER = ("QRZ", "WRL", "CLUBLOG", "EQSL")
    CANONICAL_FIELDS = (
        "CALL", "QSO_DATE", "TIME_ON", "BAND", "FREQ", "MODE", "SUBMODE",
        "RST_SENT", "RST_RCVD", "GRIDSQUARE", "STATE", "CNTY", "COUNTRY",
        "NAME", "QTH", "COMMENT", "QSL_SENT", "QSL_RCVD", "STATION_CALLSIGN",
        "MY_GRIDSQUARE",
    )
    DIFFERENCE_FIELDS = (
        "RST_SENT", "RST_RCVD", "GRIDSQUARE", "STATE", "CNTY", "COUNTRY",
        "NAME", "QTH", "COMMENT", "QSL_SENT", "QSL_RCVD",
    )
    _cache_lock = threading.RLock()
    _cache_signature: Optional[Tuple[Any, ...]] = None
    _cache_rows: List[Dict[str, Any]] = []
    _cache_options: Dict[str, Any] = {}

    def __init__(self, hub: Optional[CloudHubService] = None) -> None:
        self.hub = hub or CloudHubService()
        self.comparator = FastADIFComparisonService()

    def _signature(self) -> Tuple[Any, ...]:
        values: List[Any] = []
        for provider in self.PROVIDER_ORDER:
            summary = self.hub.snapshots.summary(provider)
            values.extend((provider, summary.get("downloaded_at"), summary.get("records")))
        return tuple(values)

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _upper(value: Any) -> str:
        return QSOManagerWorkspace._text(value).upper()

    @staticmethod
    def _mode(record: Dict[str, Any]) -> str:
        return QSOManagerWorkspace._upper(record.get("SUBMODE") or record.get("MODE"))

    @staticmethod
    def _date_key(value: Any) -> str:
        text = QSOManagerWorkspace._text(value).replace("/", "-")
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text

    @staticmethod
    def _logical_id(refs: Dict[str, int], record: Dict[str, Any]) -> str:
        stable = "|".join(
            f"{provider}:{refs[provider]}" for provider in QSOManagerWorkspace.PROVIDER_ORDER if provider in refs
        )
        identity = "|".join([
            QSOManagerWorkspace._upper(record.get("CALL")),
            QSOManagerWorkspace._date_key(record.get("QSO_DATE")),
            QSOManagerWorkspace._text(record.get("TIME_ON"))[:5],
            QSOManagerWorkspace._upper(record.get("BAND")),
            QSOManagerWorkspace._mode(record),
            stable,
        ])
        return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]

    @classmethod
    def invalidate_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache_signature = None
            cls._cache_rows = []
            cls._cache_options = {}

    def _source_payload(self, provider: str, index: int, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": provider,
            "index": index,
            "external_id": self.hub._external_id(provider, record),
            "capabilities": dict(PROVIDERS[provider].capabilities),
            "record": record,
        }

    def _confirmation_sources(self, refs: Dict[str, int], snapshots: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        confirmed: List[str] = []
        yes_values = {"Y", "YES", "TRUE", "V", "CONFIRMED", "1"}
        for provider, index in refs.items():
            rows = snapshots.get(provider) or []
            if index < 0 or index >= len(rows):
                continue
            record = rows[index]
            candidates = [
                record.get("QSL_RCVD"), record.get("LOTW_QSL_RCVD"), record.get("EQSL_QSL_RCVD"),
                record.get("APP_QRZLOG_QSL_RCVD"), record.get("APP_WRL_CONFIRMED"),
            ]
            if any(self._upper(value) in yes_values for value in candidates if value not in (None, "")):
                confirmed.append(provider)
        return confirmed

    def _field_differences(self, refs: Dict[str, int], snapshots: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        differences: List[str] = []
        for field in self.DIFFERENCE_FIELDS:
            values = set()
            for provider, index in refs.items():
                rows = snapshots.get(provider) or []
                if index < 0 or index >= len(rows):
                    continue
                value = rows[index].get(field)
                if value not in (None, ""):
                    values.add(self._upper(value))
            if len(values) > 1:
                differences.append(field)
        return differences

    def _build_rows(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        snapshots: Dict[str, List[Dict[str, Any]]] = {
            provider: list((self.hub.snapshots.load(provider).get("records") or []))
            for provider in self.PROVIDER_ORDER
        }
        available = [
            provider for provider in self.PROVIDER_ORDER
            if self.hub.snapshots.summary(provider).get("downloaded_at") is not None
        ]
        normalized = {
            provider: self.comparator._normalize(rows, provider)
            for provider, rows in snapshots.items()
        }

        duplicate_refs = set()
        for provider, qsos in normalized.items():
            for group in self.comparator._probable_duplicates(qsos):
                for index in group.get("indexes") or []:
                    duplicate_refs.add((provider, index))

        nodes: List[Dict[str, Any]] = []
        qrz_by_index: Dict[int, Dict[str, Any]] = {}
        qrz_norm = normalized.get("QRZ") or []
        for q in qrz_norm:
            node = {"refs": {"QRZ": q.index}, "representative": q}
            nodes.append(node)
            qrz_by_index[q.index] = node

        orphan_buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

        for provider in self.PROVIDER_ORDER:
            if provider == "QRZ":
                continue
            provider_norm = normalized.get(provider) or []
            matched_indexes = set()
            if qrz_norm and provider_norm:
                matched, _unmatched_qrz, unmatched_provider, _reviews = self.comparator._match(qrz_norm, provider_norm)
                for left, right, _evidence in matched:
                    node = qrz_by_index.get(left.index)
                    if node is not None:
                        node["refs"][provider] = right.index
                        matched_indexes.add(right.index)
                remaining = unmatched_provider
            else:
                remaining = provider_norm

            for q in remaining:
                if q.index in matched_indexes:
                    continue
                bucket_key = (q.call, q.date)
                best_node = None
                best_score = -10_000.0
                for candidate_node in orphan_buckets.get(bucket_key, []):
                    if provider in candidate_node["refs"]:
                        continue
                    evidence = self.comparator._candidate(candidate_node["representative"], q)
                    if not evidence or evidence.get("kind") != "auto":
                        continue
                    score = float(evidence.get("score") or 0)
                    if score > best_score:
                        best_score = score
                        best_node = candidate_node
                if best_node is not None:
                    best_node["refs"][provider] = q.index
                else:
                    node = {"refs": {provider: q.index}, "representative": q}
                    nodes.append(node)
                    orphan_buckets[bucket_key].append(node)

        rows: List[Dict[str, Any]] = []
        bands, modes, countries = set(), set(), set()
        for node in nodes:
            refs: Dict[str, int] = node["refs"]
            canonical_provider = next((p for p in self.PROVIDER_ORDER if p in refs), None)
            if canonical_provider is None:
                continue
            canonical_index = refs[canonical_provider]
            canonical_rows = snapshots[canonical_provider]
            if canonical_index < 0 or canonical_index >= len(canonical_rows):
                continue
            canonical = canonical_rows[canonical_index]
            call = self._upper(canonical.get("CALL"))
            qso_date = self._date_key(canonical.get("QSO_DATE"))
            time_on = self._text(canonical.get("TIME_ON"))
            band = self._upper(canonical.get("BAND"))
            mode = self._mode(canonical)
            country = self._text(canonical.get("COUNTRY"))
            source_payloads = {
                provider: self._source_payload(provider, index, snapshots[provider][index])
                for provider, index in refs.items()
                if 0 <= index < len(snapshots.get(provider) or [])
            }
            missing_in = [provider for provider in available if provider not in refs]
            differences = self._field_differences(refs, snapshots)
            confirmation_sources = self._confirmation_sources(refs, snapshots)
            duplicate = any((provider, index) in duplicate_refs for provider, index in refs.items())
            logical_id = self._logical_id(refs, canonical)
            search_blob = " ".join(
                self._text(canonical.get(field))
                for field in ("CALL", "NAME", "QTH", "COUNTRY", "STATE", "CNTY", "GRIDSQUARE", "COMMENT")
            ).upper()
            row = {
                "logical_id": logical_id,
                "call": call,
                "date": qso_date,
                "time": time_on,
                "band": band,
                "mode": mode,
                "freq": canonical.get("FREQ"),
                "country": country,
                "state": canonical.get("STATE"),
                "county": canonical.get("CNTY") or canonical.get("COUNTY"),
                "grid": canonical.get("GRIDSQUARE") or canonical.get("GRID"),
                "name": canonical.get("NAME"),
                "qth": canonical.get("QTH"),
                "rst_sent": canonical.get("RST_SENT"),
                "rst_rcvd": canonical.get("RST_RCVD"),
                "comment": canonical.get("COMMENT"),
                "qsl_sent": canonical.get("QSL_SENT"),
                "qsl_rcvd": canonical.get("QSL_RCVD"),
                "station_callsign": canonical.get("STATION_CALLSIGN"),
                "canonical_provider": canonical_provider,
                "canonical_index": canonical_index,
                "providers": [p for p in self.PROVIDER_ORDER if p in refs],
                "missing_in": missing_in,
                "provider_count": len(refs),
                "refs": refs,
                "source_records": source_payloads,
                "duplicate": duplicate,
                "difference_fields": differences,
                "difference_count": len(differences),
                "confirmation_sources": confirmation_sources,
                "confirmed": bool(confirmation_sources),
                "search_blob": search_blob,
                "canonical_record": canonical,
            }
            rows.append(row)
            if band:
                bands.add(band)
            if mode:
                modes.add(mode)
            if country:
                countries.add(country)

        rows.sort(key=lambda row: (row.get("date") or "", row.get("time") or "", row.get("call") or ""), reverse=True)
        options = {
            "providers": list(self.PROVIDER_ORDER),
            "available_providers": available,
            "bands": sorted(bands),
            "modes": sorted(modes),
            "countries": sorted(countries),
            "columns": [
                "date", "time", "call", "band", "mode", "freq", "country", "state", "county", "grid",
                "name", "qth", "rst", "comment", "qsl", "sources", "missing", "differences", "duplicate",
            ],
        }
        return rows, options

    def _cached(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        signature = self._signature()
        with self._cache_lock:
            if self._cache_signature == signature and self._cache_rows:
                return self._cache_rows, self._cache_options
        rows, options = self._build_rows()
        with self._cache_lock:
            self.__class__._cache_signature = signature
            self.__class__._cache_rows = rows
            self.__class__._cache_options = options
        return rows, options

    def options(self) -> Dict[str, Any]:
        rows, options = self._cached()
        summary = {
            "logical_qsos": len(rows),
            "qrz_missing": sum(1 for row in rows if "QRZ" not in row["providers"]),
            "multi_source": sum(1 for row in rows if row["provider_count"] >= 2),
            "duplicates": sum(1 for row in rows if row["duplicate"]),
            "with_differences": sum(1 for row in rows if row["difference_count"]),
            "confirmed": sum(1 for row in rows if row["confirmed"]),
        }
        return {**options, "summary": summary}

    @staticmethod
    def _bool_filter(value: Optional[str]) -> Optional[bool]:
        if value is None or value == "":
            return None
        return str(value).lower() in {"1", "true", "yes", "y"}

    def _filtered(
        self,
        *,
        q: str = "",
        call: str = "",
        band: str = "",
        mode: str = "",
        country: str = "",
        date_from: str = "",
        date_to: str = "",
        provider: str = "",
        missing_in: str = "",
        qrz: str = "",
        duplicate: Optional[str] = None,
        differences: Optional[str] = None,
        confirmed: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows, _ = self._cached()
        q = q.strip().upper()
        call = call.strip().upper()
        band = band.strip().upper()
        mode = mode.strip().upper()
        country = country.strip().upper()
        provider = provider.strip().upper()
        missing_in = missing_in.strip().upper()
        qrz = qrz.strip().lower()
        dup_value = self._bool_filter(duplicate)
        diff_value = self._bool_filter(differences)
        conf_value = self._bool_filter(confirmed)

        out: List[Dict[str, Any]] = []
        for row in rows:
            if q and q not in row.get("search_blob", ""):
                continue
            if call and call not in row.get("call", ""):
                continue
            if band and row.get("band", "").upper() != band:
                continue
            if mode and row.get("mode", "").upper() != mode:
                continue
            if country and self._upper(row.get("country")) != country:
                continue
            if date_from and (row.get("date") or "") < date_from:
                continue
            if date_to and (row.get("date") or "") > date_to:
                continue
            if provider and provider not in row.get("providers", []):
                continue
            if missing_in and missing_in not in row.get("missing_in", []):
                continue
            if qrz == "present" and "QRZ" not in row.get("providers", []):
                continue
            if qrz == "missing" and "QRZ" in row.get("providers", []):
                continue
            if dup_value is not None and bool(row.get("duplicate")) != dup_value:
                continue
            if diff_value is not None and bool(row.get("difference_count")) != diff_value:
                continue
            if conf_value is not None and bool(row.get("confirmed")) != conf_value:
                continue
            out.append(row)
        return out

    def query(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        sort: str = "date",
        direction: str = "desc",
        **filters: Any,
    ) -> Dict[str, Any]:
        rows = self._filtered(**filters)
        sort_map = {
            "date": lambda r: (r.get("date") or "", r.get("time") or ""),
            "call": lambda r: r.get("call") or "",
            "band": lambda r: r.get("band") or "",
            "mode": lambda r: r.get("mode") or "",
            "country": lambda r: self._upper(r.get("country")),
            "sources": lambda r: int(r.get("provider_count") or 0),
            "differences": lambda r: int(r.get("difference_count") or 0),
        }
        key_fn = sort_map.get(sort, sort_map["date"])
        rows = sorted(rows, key=key_fn, reverse=direction.lower() != "asc")
        total = len(rows)
        page = max(1, int(page))
        page_size = max(10, min(int(page_size), 500))
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "items": [self._public_row(row) for row in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "sort": sort,
            "direction": direction,
        }

    def ids(self, limit: int = 50000, **filters: Any) -> Dict[str, Any]:
        rows = self._filtered(**filters)
        limit = max(1, min(int(limit), 50000))
        ids = [row["logical_id"] for row in rows[:limit]]
        return {"ids": ids, "total": len(rows), "truncated": len(rows) > len(ids)}

    def get(self, logical_id: str) -> Dict[str, Any]:
        rows, _ = self._cached()
        for row in rows:
            if row["logical_id"] == logical_id:
                return self._public_row(row, include_records=True)
        raise LookupError("Logical QSO not found in current snapshots")

    def _raw(self, logical_id: str) -> Dict[str, Any]:
        rows, _ = self._cached()
        for row in rows:
            if row["logical_id"] == logical_id:
                return row
        raise LookupError("Logical QSO not found in current snapshots")

    @staticmethod
    def _public_row(row: Dict[str, Any], include_records: bool = False) -> Dict[str, Any]:
        hidden = {"search_blob", "canonical_record"}
        if not include_records:
            hidden.add("source_records")
        return {key: value for key, value in row.items() if key not in hidden}

    def canonical_ref(self, logical_id: str, preferred_source: Optional[str] = None) -> Tuple[str, int]:
        row = self._raw(logical_id)
        if preferred_source:
            source = preferred_source.strip().upper()
            if source in row["refs"]:
                return source, int(row["refs"][source])
        for provider in self.PROVIDER_ORDER:
            if provider in row["refs"]:
                return provider, int(row["refs"][provider])
        raise LookupError("Logical QSO has no source record")

    def canonical_record(self, logical_id: str) -> Dict[str, Any]:
        return dict(self._raw(logical_id)["canonical_record"])

    def export_adif(self, logical_ids: Sequence[str]) -> str:
        records = [self.canonical_record(logical_id) for logical_id in logical_ids]
        return records_to_adif(records, program_id="PU2BRU-QSO-Manager-6")

    def plan_bulk(
        self,
        action: str,
        logical_ids: Sequence[str],
        target: Optional[str] = None,
        source: Optional[str] = None,
        changes: Optional[Dict[str, Any]] = None,
        delete_source: bool = False,
    ) -> Dict[str, Any]:
        action = action.strip().upper()
        ids = list(dict.fromkeys(str(x) for x in logical_ids if str(x)))
        if not ids:
            raise ValueError("Selecione ao menos um QSO")
        if len(ids) > 10000:
            raise ValueError("Operações remotas são limitadas a 10.000 QSOs por lote")

        target_name = self.hub._provider(target) if target else None
        source_name = self.hub._provider(source) if source else None
        normalized_changes = {str(k).upper(): v for k, v in (changes or {}).items() if v not in (None, "")}
        actionable = 0
        skipped = 0
        unsupported = 0
        rows: List[Dict[str, Any]] = []

        for logical_id in ids:
            row = self._raw(logical_id)
            refs = row["refs"]
            item = {"logical_id": logical_id, "call": row["call"], "date": row["date"], "time": row["time"], "providers": row["providers"]}
            if action == "PUBLISH":
                if not target_name or not PROVIDERS[target_name].capabilities.get("add"):
                    unsupported += 1
                    item["status"] = "unsupported"
                elif target_name in refs:
                    skipped += 1
                    item["status"] = "already_present"
                else:
                    actionable += 1
                    item["status"] = "ready"
            elif action == "UPDATE":
                if not target_name or not PROVIDERS[target_name].capabilities.get("update"):
                    unsupported += 1
                    item["status"] = "unsupported"
                elif target_name not in refs:
                    skipped += 1
                    item["status"] = "not_present"
                elif not normalized_changes:
                    unsupported += 1
                    item["status"] = "no_changes"
                else:
                    actionable += 1
                    item["status"] = "ready"
            elif action == "DELETE":
                if not target_name or not PROVIDERS[target_name].capabilities.get("delete"):
                    unsupported += 1
                    item["status"] = "unsupported"
                elif target_name not in refs:
                    skipped += 1
                    item["status"] = "not_present"
                else:
                    actionable += 1
                    item["status"] = "ready"
            elif action == "MOVE":
                if not source_name or not target_name or source_name == target_name:
                    unsupported += 1
                    item["status"] = "invalid_route"
                elif source_name not in refs:
                    skipped += 1
                    item["status"] = "source_missing"
                elif target_name in refs:
                    skipped += 1
                    item["status"] = "target_already_present"
                elif not PROVIDERS[target_name].capabilities.get("add"):
                    unsupported += 1
                    item["status"] = "target_unsupported"
                elif delete_source and not PROVIDERS[source_name].capabilities.get("delete"):
                    unsupported += 1
                    item["status"] = "source_delete_unsupported"
                else:
                    actionable += 1
                    item["status"] = "ready"
            else:
                raise ValueError(f"Ação em lote não suportada: {action}")
            rows.append(item)

        return {
            "action": action,
            "selected": len(ids),
            "actionable": actionable,
            "skipped": skipped,
            "unsupported": unsupported,
            "target": target_name,
            "source": source_name,
            "delete_source": bool(delete_source),
            "changes": normalized_changes,
            "sample": rows[:20],
            "capability_matrix": {
                provider: dict(PROVIDERS[provider].capabilities) for provider in self.PROVIDER_ORDER
            },
        }
