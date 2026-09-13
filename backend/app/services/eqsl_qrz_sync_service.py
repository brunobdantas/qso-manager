"""Safe eQSL Inbox -> QRZ confirmation synchronization.

This workflow is intentionally narrower than a generic QRZ edit feature.  It
only writes EQSL_QSL_RCVD and EQSL_QSLRDATE, targets an exact QRZ LOGID, uses
live preconditions, backs up the live ADIF, and verifies protected QRZ fields
after every REPLACE.

Matching policy mirrors the conservative workflow validated against PU2BRU's
real logs:
- same CALL (trimmed/case-insensitive), QSO_DATE and BAND;
- compatible effective mode;
- <= 120 seconds;
- strict 1:1 relationship inside that candidate graph;
- explicit eQSL receive date is mandatory;
- ambiguous/card-collision cases are never auto-written.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..adapters.cloud_logs import CloudProviderError
from ..adapters.qrz_cloud_v501 import QRZCloudAdapterV501
from ..adif.parser import ADIFParser
from .cloud_snapshot_store import CloudSnapshotStore
from .credential_store import CredentialStore
from .qso_manager_workspace import QSOManagerWorkspace


class EqslQrzSyncService:
    MAX_DELTA_SECONDS = 120
    REVIEW_DELTA_SECONDS = 300
    MAX_APPLY = 500

    PROTECTED_FIELDS = (
        "CALL",
        "QSO_DATE",
        "TIME_ON",
        "BAND",
        "FREQ",
        "MODE",
        "SUBMODE",
        "CONTEST_ID",
        "LOTW_QSL_RCVD",
        "LOTW_QSLRDATE",
        "QSL_RCVD",
        "QSLRDATE",
    )

    def __init__(
        self,
        credentials: Optional[CredentialStore] = None,
        snapshots: Optional[CloudSnapshotStore] = None,
        adapter_factory: Optional[Callable[[Dict[str, Any]], QRZCloudAdapterV501]] = None,
    ) -> None:
        self.credentials = credentials or CredentialStore()
        self.snapshots = snapshots or CloudSnapshotStore()
        self._adapter_factory = adapter_factory or (lambda creds: QRZCloudAdapterV501(creds))
        self._adif = ADIFParser()

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _call(cls, record: Dict[str, Any]) -> str:
        return cls._text(record.get("CALL")).upper()

    @classmethod
    def _date(cls, record: Dict[str, Any]) -> str:
        value = cls._text(record.get("QSO_DATE")).replace("-", "")
        return value if len(value) == 8 and value.isdigit() else value

    @classmethod
    def _band(cls, record: Dict[str, Any]) -> str:
        return cls._text(record.get("BAND")).upper()

    @classmethod
    def _time_seconds(cls, record: Dict[str, Any]) -> Optional[int]:
        raw = "".join(ch for ch in cls._text(record.get("TIME_ON")) if ch.isdigit())
        if len(raw) < 4:
            return None
        try:
            hh, mm = int(raw[:2]), int(raw[2:4])
            ss = int(raw[4:6]) if len(raw) >= 6 else 0
        except ValueError:
            return None
        if hh > 23 or mm > 59 or ss > 59:
            return None
        return hh * 3600 + mm * 60 + ss

    @classmethod
    def _time_hhmm(cls, record: Dict[str, Any]) -> str:
        seconds = cls._time_seconds(record)
        if seconds is None:
            return ""
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"

    def _effective_mode(self, record: Dict[str, Any]) -> str:
        mode = self._text(record.get("MODE")).upper()
        submode = self._text(record.get("SUBMODE")).upper()
        operating, _family = self._adif.classify_mode(mode, submode or None)
        return self._text(operating or submode or mode).upper()

    def _mode_compatible(self, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        left, right = self._effective_mode(a), self._effective_mode(b)
        if not left or not right:
            return False
        if left == right:
            return True
        return {left, right} <= {"PSK", "PSK31"}

    @classmethod
    def _qsl_date(cls, record: Dict[str, Any]) -> Optional[str]:
        for field in ("EQSL_QSLRDATE", "QSLRDATE"):
            value = cls._text(record.get(field)).replace("-", "")
            if len(value) == 8 and value.isdigit():
                return value
        return None

    @classmethod
    def _yes(cls, value: Any) -> bool:
        return cls._text(value).upper() == "Y"

    @classmethod
    def _logid(cls, record: Dict[str, Any]) -> str:
        return cls._text(record.get("APP_QRZLOG_LOGID") or record.get("QSO_ID"))

    def _identity_key(self, record: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        return (
            self._call(record),
            self._date(record),
            self._time_hhmm(record),
            self._band(record),
            self._effective_mode(record),
        )

    def _base_key(self, record: Dict[str, Any]) -> Tuple[str, str, str]:
        return (self._call(record), self._date(record), self._band(record))

    def _normalize_eqsl(self, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        groups: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[self._identity_key(row)].append(row)

        usable: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        missing_date: List[Dict[str, Any]] = []

        for key, members in groups.items():
            dates = sorted({d for d in (self._qsl_date(row) for row in members) if d})
            if not dates:
                missing_date.append({
                    "identity": key,
                    "records": len(members),
                    "reason": "eQSL não forneceu data explícita de recebimento.",
                })
                continue
            if len(dates) > 1:
                conflicts.append({
                    "identity": key,
                    "dates": dates,
                    "records": len(members),
                    "reason": "O mesmo cartão/identidade aparece com mais de uma data de recebimento.",
                })
                continue
            representative = dict(members[-1])
            representative["_EQSL_TARGET_DATE"] = dates[0]
            representative["_EQSL_DUPLICATE_COUNT"] = len(members)
            usable.append(representative)

        return {
            "usable": usable,
            "date_conflicts": conflicts,
            "missing_explicit_date": missing_date,
        }

    def _candidate_edges(
        self,
        qrz_rows: List[Dict[str, Any]],
        eqsl_rows: List[Dict[str, Any]],
        delta_limit: int,
    ) -> Tuple[Dict[int, List[Tuple[int, int]]], Dict[int, List[Tuple[int, int]]]]:
        q_by_key: Dict[Tuple[str, str, str], List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
        for q_index, qso in enumerate(qrz_rows):
            q_by_key[self._base_key(qso)].append((q_index, qso))

        left: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        right: Dict[int, List[Tuple[int, int]]] = defaultdict(list)

        for e_index, evidence in enumerate(eqsl_rows):
            e_seconds = self._time_seconds(evidence)
            if e_seconds is None:
                continue
            for q_index, qso in q_by_key.get(self._base_key(evidence), []):
                q_seconds = self._time_seconds(qso)
                if q_seconds is None or not self._mode_compatible(qso, evidence):
                    continue
                delta = abs(q_seconds - e_seconds)
                if delta > delta_limit:
                    continue
                left[q_index].append((e_index, delta))
                right[e_index].append((q_index, delta))

        return left, right

    def _candidate_view(
        self,
        qrz_index: int,
        qso: Dict[str, Any],
        evidence_index: int,
        evidence: Dict[str, Any],
        delta: int,
    ) -> Dict[str, Any]:
        target = str(evidence["_EQSL_TARGET_DATE"])
        current_received = "Y" if self._yes(qso.get("EQSL_QSL_RCVD")) else self._text(qso.get("EQSL_QSL_RCVD")).upper()
        current_date = self._text(qso.get("EQSL_QSLRDATE")).replace("-", "")
        if current_received != "Y":
            kind = "NEW_CONFIRMATION"
        elif current_date != target:
            kind = "ALIGN_DATE"
        else:
            kind = "ALREADY_ALIGNED"

        return {
            "kind": kind,
            "qrz_index": qrz_index,
            "eqsl_index": evidence_index,
            "logid": self._logid(qso),
            "call": self._call(qso),
            "qso_date": self._date(qso),
            "time_qrz": self._time_hhmm(qso),
            "time_eqsl": self._time_hhmm(evidence),
            "delta_seconds": delta,
            "band": self._band(qso),
            "mode_qrz": self._effective_mode(qso),
            "mode_eqsl": self._effective_mode(evidence),
            "current_received": current_received,
            "current_date": current_date,
            "target_date": target,
            "contest_id": self._text(qso.get("CONTEST_ID")),
            "lotw_received": self._text(qso.get("LOTW_QSL_RCVD")).upper(),
            "lotw_date": self._text(qso.get("LOTW_QSLRDATE")),
            "qrz_status": self._text(qso.get("APP_QRZLOG_STATUS")).upper(),
            "evidence_duplicates_collapsed": int(evidence.get("_EQSL_DUPLICATE_COUNT") or 1),
        }

    def plan(self) -> Dict[str, Any]:
        qrz_payload = self.snapshots.load("QRZ")
        eqsl_payload = self.snapshots.load("EQSL_INBOX")
        qrz_rows = list(qrz_payload.get("records") or [])
        eqsl_raw = list(eqsl_payload.get("records") or [])

        if not qrz_rows:
            raise CloudProviderError("Sincronize o QRZ antes de analisar eQSL → QRZ.")
        if not eqsl_raw:
            raise CloudProviderError("Sincronize o eQSL Inbox antes de analisar eQSL → QRZ.")

        normalized = self._normalize_eqsl(eqsl_raw)
        eqsl_rows = normalized["usable"]
        q_edges, e_edges = self._candidate_edges(qrz_rows, eqsl_rows, self.MAX_DELTA_SECONDS)

        safe: List[Dict[str, Any]] = []
        already: List[Dict[str, Any]] = []
        collisions = set()
        matched_eqsl = set()

        for q_index, candidates in q_edges.items():
            if len(candidates) != 1:
                collisions.add(("QRZ", q_index))
                continue
            e_index, delta = candidates[0]
            if len(e_edges.get(e_index, [])) != 1:
                collisions.add(("EQSL", e_index))
                continue
            item = self._candidate_view(q_index, qrz_rows[q_index], e_index, eqsl_rows[e_index], delta)
            matched_eqsl.add(e_index)
            if not item["logid"]:
                collisions.add(("NO_LOGID", q_index))
                continue
            if item["kind"] == "ALREADY_ALIGNED":
                already.append(item)
            else:
                safe.append(item)

        # Anything with strict candidate relationships that are not 1:1 is a collision.
        collision_items: List[Dict[str, Any]] = []
        for side, index in sorted(collisions, key=lambda row: (row[0], row[1])):
            if side in {"QRZ", "NO_LOGID"}:
                qso = qrz_rows[index]
                collision_items.append({
                    "side": side,
                    "call": self._call(qso),
                    "qso_date": self._date(qso),
                    "time": self._time_hhmm(qso),
                    "band": self._band(qso),
                    "reason": "Mais de um cartão/QSO compete pelo pareamento seguro." if side == "QRZ" else "QSO QRZ sem LOGID estável.",
                })
            else:
                evidence = eqsl_rows[index]
                collision_items.append({
                    "side": side,
                    "call": self._call(evidence),
                    "qso_date": self._date(evidence),
                    "time": self._time_hhmm(evidence),
                    "band": self._band(evidence),
                    "reason": "Cartão eQSL possui mais de um QSO QRZ candidato dentro da janela segura.",
                })

        # Build review hints with a wider 5-minute window, but never auto-write them.
        wide_q, wide_e = self._candidate_edges(qrz_rows, eqsl_rows, self.REVIEW_DELTA_SECONDS)
        manual: List[Dict[str, Any]] = []
        safe_pairs = {(row["qrz_index"], row["eqsl_index"]) for row in safe + already}
        seen_manual = set()
        for q_index, candidates in wide_q.items():
            for e_index, delta in candidates:
                if (q_index, e_index) in safe_pairs or delta <= self.MAX_DELTA_SECONDS:
                    continue
                key = (q_index, e_index)
                if key in seen_manual:
                    continue
                seen_manual.add(key)
                qso, evidence = qrz_rows[q_index], eqsl_rows[e_index]
                manual.append({
                    "call": self._call(qso),
                    "qso_date": self._date(qso),
                    "time_qrz": self._time_hhmm(qso),
                    "time_eqsl": self._time_hhmm(evidence),
                    "delta_seconds": delta,
                    "band": self._band(qso),
                    "mode_qrz": self._effective_mode(qso),
                    "mode_eqsl": self._effective_mode(evidence),
                    "target_date": evidence["_EQSL_TARGET_DATE"],
                    "reason": "Pareamento próximo, mas fora da janela automática de 2 minutos.",
                })

        matched_or_candidate_eqsl = set(e_edges)
        unmatched_evidence = [
            {
                "call": self._call(row),
                "qso_date": self._date(row),
                "time": self._time_hhmm(row),
                "band": self._band(row),
                "mode": self._effective_mode(row),
                "target_date": row.get("_EQSL_TARGET_DATE"),
            }
            for i, row in enumerate(eqsl_rows)
            if i not in matched_or_candidate_eqsl
        ]

        safe.sort(key=lambda x: (0 if x["kind"] == "NEW_CONFIRMATION" else 1, x["qso_date"], x["time_qrz"], x["call"]))
        already.sort(key=lambda x: (x["qso_date"], x["time_qrz"], x["call"]))
        manual.sort(key=lambda x: (x["qso_date"], x["time_qrz"], x["call"]))

        new_count = sum(1 for row in safe if row["kind"] == "NEW_CONFIRMATION")
        align_count = sum(1 for row in safe if row["kind"] == "ALIGN_DATE")
        return {
            "ready": True,
            "policy": {
                "max_delta_seconds": self.MAX_DELTA_SECONDS,
                "strict_one_to_one": True,
                "same_call_date_band": True,
                "mode_compatible": True,
                "explicit_receive_date_required": True,
                "date_source": "eQSL Inbox only; QSO_DATE is never substituted",
                "write_fields": ["EQSL_QSL_RCVD", "EQSL_QSLRDATE"],
                "remote_delete": False,
            },
            "snapshot_freshness": {
                "QRZ": qrz_payload.get("downloaded_at"),
                "EQSL_INBOX": eqsl_payload.get("downloaded_at"),
            },
            "summary": {
                "qrz_records": len(qrz_rows),
                "eqsl_records": len(eqsl_raw),
                "eqsl_usable_identities": len(eqsl_rows),
                "safe_updates": len(safe),
                "new_confirmations": new_count,
                "date_alignments": align_count,
                "already_aligned": len(already),
                "collisions": len(collision_items),
                "manual_review": len(manual),
                "unmatched_evidence": len(unmatched_evidence),
                "date_conflicts": len(normalized["date_conflicts"]),
                "missing_explicit_date": len(normalized["missing_explicit_date"]),
            },
            "candidates": safe,
            "already_aligned": already,
            "collisions": collision_items,
            "manual_review": manual,
            "unmatched_evidence": unmatched_evidence[:500],
            "date_conflicts": normalized["date_conflicts"][:200],
            "missing_explicit_date": normalized["missing_explicit_date"][:200],
        }

    def _credentials(self) -> Dict[str, Any]:
        values = self.credentials.get("QRZ")
        if not values or not self._text(values.get("api_key")):
            raise CloudProviderError("Configure a QRZ Logbook API Key antes de aplicar eQSL → QRZ.")
        return values

    def _validate_identity(self, candidate: Dict[str, Any], live: Dict[str, Any]) -> None:
        problems = []
        if self._call(live) != candidate["call"]:
            problems.append("CALL")
        if self._date(live) != candidate["qso_date"]:
            problems.append("QSO_DATE")
        if self._time_hhmm(live) != candidate["time_qrz"]:
            problems.append("TIME_ON")
        if self._band(live) != candidate["band"]:
            problems.append("BAND")
        if not self._mode_compatible(
            live,
            {"MODE": candidate["mode_qrz"], "SUBMODE": candidate["mode_qrz"]},
        ):
            problems.append("MODE")
        if problems:
            raise CloudProviderError(
                f"{candidate['call']} LOGID {candidate['logid']} mudou de identidade: "
                + ", ".join(problems)
            )

    def _live_state(self, record: Dict[str, Any]) -> Tuple[str, str]:
        received = "Y" if self._yes(record.get("EQSL_QSL_RCVD")) else self._text(record.get("EQSL_QSL_RCVD")).upper()
        date = self._text(record.get("EQSL_QSLRDATE")).replace("-", "")
        return received, date

    def _live_backup(self, records: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Path:
        backup_dir = self.snapshots.root / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = backup_dir / f"qrz-eqsl-live-{stamp}.adi"
        header = "<ADIF_VER:5>3.1.4<PROGRAMID:23>PU2BRU_EQSL_QRZ_SYNC<EOH>\n"
        body = "\n".join(fetch["raw_adif"] for _candidate, fetch in records)
        path.write_text(header + body + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _select_canary(candidates: List[Dict[str, Any]]) -> int:
        for i, row in enumerate(candidates):
            if row.get("qrz_status") in {"", "N"} and row.get("lotw_received") != "Y":
                return i
        return 0

    def _expected_live_fields(self, live: Dict[str, Any]) -> Dict[str, Any]:
        fields = {
            "EQSL_QSL_RCVD": live.get("EQSL_QSL_RCVD"),
            "EQSL_QSLRDATE": live.get("EQSL_QSLRDATE"),
        }
        for name in self.PROTECTED_FIELDS:
            fields[name] = live.get(name)
        return fields

    def _merge_verified_snapshot(
        self,
        before_rows: List[Dict[str, Any]],
        verified: List[Dict[str, Any]],
        old_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        by_logid = {
            self._logid(row): dict(row)
            for row in before_rows
            if self._logid(row)
        }
        for row in verified:
            logid = self._logid(row)
            if logid:
                by_logid[logid] = dict(row)
        merged = []
        used = set()
        for row in before_rows:
            logid = self._logid(row)
            if logid and logid in by_logid:
                merged.append(by_logid[logid])
                used.add(logid)
            else:
                merged.append(row)
        for logid, row in by_logid.items():
            if logid not in used:
                merged.append(row)

        metadata = {
            **dict(old_metadata or {}),
            "source": "eqsl_qrz_verified_exact_updates",
            "coverage": "API_FULL_SYNC",
            "exact_updates_verified": len(verified),
            "full_resync_required": True,
        }
        return self.snapshots.save("QRZ", merged, metadata)

    def apply(self, confirm: bool = False, limit: int = 500) -> Dict[str, Any]:
        plan = self.plan()
        candidates = list(plan["candidates"])
        limit = max(1, min(int(limit), self.MAX_APPLY))
        candidates = candidates[:limit]

        if not confirm:
            return {
                "dry_run": True,
                "attempted": len(candidates),
                "plan": plan,
            }
        if not candidates:
            return {
                "ok": True,
                "attempted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [],
                "message": "Nenhuma atualização eQSL segura está pendente.",
                "plan": plan,
            }

        canary_index = self._select_canary(candidates)
        if canary_index:
            candidates.insert(0, candidates.pop(canary_index))

        qrz_payload = self.snapshots.load("QRZ")
        qrz_rows = list(qrz_payload.get("records") or [])
        local_backup = self.snapshots.backup("QRZ")

        adapter = self._adapter_factory(self._credentials())
        preflight: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        verified_after: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        skipped = 0
        live_backup = None
        full_resync = False
        resync_error = None

        try:
            # Full preflight before the first remote mutation.
            for candidate in candidates:
                fetched = adapter.fetch_exact(candidate["logid"])
                live = fetched["record"]
                self._validate_identity(candidate, live)
                received, date = self._live_state(live)
                if received == "Y" and date == candidate["target_date"]:
                    results.append({
                        "call": candidate["call"],
                        "logid": candidate["logid"],
                        "status": "ALREADY_ALIGNED",
                        "target_date": candidate["target_date"],
                    })
                    skipped += 1
                    continue

                expected_received = candidate["current_received"]
                expected_date = candidate["current_date"]
                if received != expected_received or date != expected_date:
                    raise CloudProviderError(
                        f"{candidate['call']} LOGID {candidate['logid']} mudou desde o snapshot: "
                        f"eQSL live={received or '(vazio)'}/{date or '(vazia)'}; "
                        f"snapshot={expected_received or '(vazio)'}/{expected_date or '(vazia)'}"
                    )
                preflight.append((candidate, fetched))

            if not preflight:
                return {
                    "ok": True,
                    "attempted": len(candidates),
                    "updated": 0,
                    "skipped": skipped,
                    "errors": [],
                    "backup": str(local_backup) if local_backup else None,
                    "message": "Os candidatos já estavam alinhados no QRZ.",
                }

            live_backup = self._live_backup(preflight)

            # Canary then the remaining records. The adapter performs another
            # exact FETCH and enforces our live precondition immediately before
            # each INSERT/REPLACE.
            for position, (candidate, fetched) in enumerate(preflight):
                live = fetched["record"]
                expected = self._expected_live_fields(live)
                changes = {
                    "EQSL_QSL_RCVD": "Y",
                    "EQSL_QSLRDATE": candidate["target_date"],
                }
                result = adapter.replace_exact_fields(
                    candidate["logid"],
                    changes,
                    protected_fields=self.PROTECTED_FIELDS,
                    expected_fields=expected,
                )
                after = dict(result["after"])
                verified_after.append(after)
                results.append({
                    "call": candidate["call"],
                    "logid_before": result["logid_before"],
                    "logid_after": result["logid_after"],
                    "status": "UPDATED",
                    "kind": candidate["kind"],
                    "target_date": candidate["target_date"],
                    "canary": position == 0,
                })

            # Prefer a complete remote refresh. If QRZ is temporarily unable to
            # deliver the whole log, preserve the exact verified records locally
            # and mark the snapshot for a later full sync.
            try:
                refreshed = adapter.fetch_all()
                metadata = dict(refreshed.get("metadata") or {})
                metadata["source"] = "eqsl_qrz_post_write_full_sync"
                self.snapshots.save("QRZ", refreshed.get("records") or [], metadata)
                full_resync = True
            except Exception as exc:
                resync_error = str(exc)
                self._merge_verified_snapshot(
                    qrz_rows,
                    verified_after,
                    qrz_payload.get("metadata") or {},
                )
        except Exception as exc:
            # A failed post-write verification is fail-stop.  Any records that
            # were already verified are merged into the local snapshot so the UI
            # never pretends they were untouched.
            if verified_after:
                self._merge_verified_snapshot(
                    qrz_rows,
                    verified_after,
                    qrz_payload.get("metadata") or {},
                )
            raise CloudProviderError(
                f"eQSL → QRZ interrompido após {len(verified_after)} atualização(ões) verificadas: {exc}"
            ) from exc
        finally:
            try:
                adapter.close()
            except Exception:
                pass

        QSOManagerWorkspace.invalidate_cache()
        return {
            "ok": True,
            "attempted": len(candidates),
            "updated": len(verified_after),
            "skipped": skipped,
            "errors": [],
            "items": results,
            "backup": str(local_backup) if local_backup else None,
            "live_backup": str(live_backup) if live_backup else None,
            "full_resync": full_resync,
            "resync_error": resync_error,
            "remaining_hint": max(0, int(plan["summary"]["safe_updates"]) - len(candidates)),
        }
