"""Conservative QRZ + LoTW master ADIF builder for award applications.

The service is intentionally read-only with respect to remote logbooks. It
builds an in-memory ADIF and refuses a certified export when the merge can
reduce measurable award coverage or when a potential duplicate cannot be
resolved safely.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import csv
import hashlib
import io
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..adapters.cloud_logs import records_to_adif
from ..adif.parser import ADIFParser
from ..core.version import __version__
from .cloud_snapshot_store import CloudSnapshotStore


US_STATES = {
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD",
    "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH",
    "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}

IDENTITY_FIELDS = ("CALL", "QSO_DATE", "TIME_ON", "BAND", "MODE", "SUBMODE", "FREQ")
LOTW_AUTHORITY_FIELDS = ("STATE", "CNTY", "DXCC", "COUNTRY", "PFX", "CONT")
ZONE_FIELDS = ("CQZ", "ITUZ")
INVALID_IOTA_VALUES = {"NONE", "BLANK", "- NONE", "-NONE", "N/A", "NA", "UNKNOWN", "NULL", "-"}
GRID_PATTERNS = {
    4: re.compile(r"^[A-R]{2}[0-9]{2}$", re.IGNORECASE),
    6: re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}$", re.IGNORECASE),
    8: re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}[0-9]{2}$", re.IGNORECASE),
}


@dataclass(frozen=True)
class Pair:
    qrz_index: int
    lotw_index: int
    kind: str
    delta_seconds: int


class AwardMasterError(ValueError):
    """Raised when a master ADIF cannot be certified safely."""


class AwardMasterService:
    MATCH_WINDOW_SECONDS = 120
    MAX_AUDIT_ITEMS = 500

    def build(self, qrz_content: str, lotw_content: str) -> Dict[str, Any]:
        self._sanitization = defaultdict(int)
        self._source_sanitization_conflicts: List[Dict[str, Any]] = []
        qrz_records, qrz_errors = self._parse(qrz_content, "QRZ")
        lotw_records, lotw_errors = self._parse(lotw_content, "LoTW")
        lotw_consensus = self._build_lotw_location_consensus(lotw_records)
        pairs, qrz_unmatched, lotw_unmatched, ambiguous = self._match(qrz_records, lotw_records)

        merged: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = list(self._source_sanitization_conflicts)
        field_sources = defaultdict(int)

        for pair in pairs:
            record, pair_conflicts, source_counts = self._merge_pair(
                qrz_records[pair.qrz_index], lotw_records[pair.lotw_index], pair
            )
            merged.append(record)
            conflicts.extend(pair_conflicts)
            for source, count in source_counts.items():
                field_sources[source] += count

        for index in sorted(qrz_unmatched):
            record = dict(qrz_records[index])
            record["APP_QSOMGR_SOURCES"] = "QRZ"
            for field in ZONE_FIELDS:
                if not self._empty(record.get(field)):
                    record[f"APP_QSOMGR_{field}_SOURCE"] = "QRZ"
            merged.append(record)
            field_sources["QRZ"] += len(record)

        lotw_only_records: List[Dict[str, Any]] = []
        for index in sorted(lotw_unmatched):
            record = self._normalize_lotw_confirmation(dict(lotw_records[index]))
            record["APP_QSOMGR_SOURCES"] = "LOTW"
            for field in ZONE_FIELDS:
                if not self._empty(record.get(field)):
                    record[f"APP_QSOMGR_{field}_SOURCE"] = "LOTW"
            lotw_only_records.append(record)

        lotw_only_records, collapsed_lotw_near_duplicates = self._collapse_lotw_only_near_duplicates(
            merged, lotw_only_records, conflicts
        )
        for record in lotw_only_records:
            merged.append(record)
            field_sources["LOTW"] += len(record)

        self._apply_lotw_location_consensus(merged, lotw_consensus, conflicts)
        merged.sort(key=self._sort_key)

        source_metrics = {
            "QRZ": self._metrics(qrz_records),
            "LOTW": self._metrics(lotw_records),
        }
        master_metrics = self._metrics(merged)
        regressions = self._coverage_regressions(source_metrics, master_metrics)
        blocking_regressions = [r for r in regressions if r.get("severity") == "critical"]
        coverage_warnings = [r for r in regressions if r.get("severity") != "critical"]
        identity_conflicts = [c for c in conflicts if c.get("severity") == "critical"]
        safe_to_export = not blocking_regressions and not ambiguous and not identity_conflicts

        report = {
            "safe_to_export": safe_to_export,
            "certification": (
                "SAFE_WITH_WARNINGS" if safe_to_export and coverage_warnings
                else "SAFE" if safe_to_export
                else "REVIEW_REQUIRED"
            ),
            "policy": {
                "remote_writes": False,
                "qrz_role": "metadata_enrichment",
                "lotw_role": "award_identity_and_location_authority",
                "matching": "exact first; reciprocal unique <=120s fallback",
                "ambiguous_pairs_are_never_merged": True,
                "export_blocked_on_critical_coverage_regression": True,
                "conflicting_grid_regression_is_audited_warning": True,
                "ultimateaac_is_validator_not_source": True,
                "lotw_explicit_invalid_flags_are_authoritative": True,
                "unexplained_source_conflicts_are_audited": True,
                "invalid_iota_placeholders_are_omitted": True,
                "source_consensus_is_never_overridden_by_history": True,
                "history_normalization_requires_same_call_dxcc_and_grid": True,
                "cross_callsign_dxcc_grid_consensus_only_for_qrz_derived_zones": True,
                "cross_callsign_grid6_requires_two_unanimous_lotw": True,
                "cross_callsign_grid8_requires_two_unanimous_lotw": True,
                "cross_callsign_grid4_requires_five_unanimous_lotw": True,
                "precise_grid_never_falls_back_to_coarser_consensus": True,
                "malformed_grid_is_reduced_only_to_longest_valid_prefix": True,
                "same_call_grid4_history_may_normalize_precise_grid_zone": True,
                "lotw_only_near_duplicate_requires_unique_reciprocal_match": True,
            },
            "sources": {
                "QRZ": {
                    "records": len(qrz_records),
                    "sha256": hashlib.sha256(qrz_content.encode("utf-8", errors="replace")).hexdigest(),
                    "parse_errors": qrz_errors[:20],
                },
                "LOTW": {
                    "records": len(lotw_records),
                    "sha256": hashlib.sha256(lotw_content.encode("utf-8", errors="replace")).hexdigest(),
                    "parse_errors": lotw_errors[:20],
                },
            },
            "merge": {
                "matched_pairs": len(pairs),
                "exact_pairs": sum(1 for p in pairs if p.kind == "EXACT"),
                "near_time_pairs": sum(1 for p in pairs if p.kind == "NEAR_TIME"),
                "qrz_only": len(qrz_unmatched),
                "lotw_only": len(lotw_only_records),
                "lotw_near_duplicates_collapsed": collapsed_lotw_near_duplicates,
                "ambiguous_groups": len(ambiguous),
                "master_records": len(merged),
                "field_sources": dict(field_sources),
            },
            "coverage": {
                "sources": source_metrics,
                "master": master_metrics,
                "regressions": regressions,
                "blocking_regressions": blocking_regressions,
                "warnings": coverage_warnings,
            },
            "conflicts": {
                "total": len(conflicts),
                "critical": len(identity_conflicts),
                "items": conflicts[: self.MAX_AUDIT_ITEMS],
            },
            "ambiguous": ambiguous[: self.MAX_AUDIT_ITEMS],
            "data_quality": dict(self._sanitization),
        }

        content = self._write_adif(merged)
        report["master_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return {
            "content": content,
            "report": report,
            "audit": {
                "conflicts": conflicts,
                "ambiguous": ambiguous,
                "regressions": regressions,
            },
        }

    def certified_export(self, qrz_content: str, lotw_content: str) -> Dict[str, Any]:
        result = self.build(qrz_content, lotw_content)
        if not result["report"]["safe_to_export"]:
            raise AwardMasterError(
                "O Master ADIF exige revisão: há regressão crítica de cobertura, conflito crítico "
                "ou pareamento ambíguo. Nenhum arquivo certificado foi gerado."
            )
        return result


    def build_from_snapshots(
        self,
        snapshots: Optional[CloudSnapshotStore] = None,
    ) -> Dict[str, Any]:
        store = snapshots or CloudSnapshotStore()
        qrz = store.load("QRZ")
        lotw = store.load("LOTW")
        qrz_records = list(qrz.get("records") or [])
        lotw_records = list(lotw.get("records") or [])
        if not qrz_records:
            raise AwardMasterError("O snapshot do QRZ está vazio. Atualize QRZ em Fontes antes de gerar o Master.")
        if not lotw_records:
            raise AwardMasterError("O snapshot do LoTW está vazio. Atualize LoTW em Fontes antes de gerar o Master.")
        lotw_meta = dict(lotw.get("metadata") or {})
        if lotw_meta.get("confirmations_only") is True:
            raise AwardMasterError(
                "O snapshot do LoTW foi criado por uma versão antiga e contém somente QSLs. "
                "Atualize LoTW em Fontes para baixar o log completo antes de gerar o Master."
            )

        qrz_content = records_to_adif(qrz_records, program_id="QSO-MANAGER-QRZ-SNAPSHOT")
        lotw_content = records_to_adif(lotw_records, program_id="QSO-MANAGER-LOTW-SNAPSHOT")
        result = self.build(qrz_content, lotw_content)
        result["report"]["source_mode"] = "snapshots"
        result["report"]["snapshot_sources"] = {
            "QRZ": {
                "records": len(qrz_records),
                "downloaded_at": qrz.get("downloaded_at"),
            },
            "LOTW": {
                "records": len(lotw_records),
                "downloaded_at": lotw.get("downloaded_at"),
                "accepted_qsos": lotw_meta.get("accepted_qsos"),
                "confirmed_qsos": lotw_meta.get("confirmed_qsos"),
                "incremental": lotw_meta.get("incremental"),
                "lotw_last_qso_rx": lotw_meta.get("lotw_last_qso_rx"),
                "lotw_last_qsl": lotw_meta.get("lotw_last_qsl"),
            },
        }
        return result

    def certified_export_from_snapshots(
        self,
        snapshots: Optional[CloudSnapshotStore] = None,
    ) -> Dict[str, Any]:
        result = self.build_from_snapshots(snapshots)
        if not result["report"]["safe_to_export"]:
            raise AwardMasterError(
                "O Master ADIF exige revisão: há regressão crítica de cobertura, conflito crítico "
                "ou pareamento ambíguo. Nenhum arquivo certificado foi gerado."
            )
        return result

    def audit_csv(self, payload: Dict[str, Any]) -> str:
        # The preview intentionally caps conflict rows to keep the UI responsive,
        # while the downloadable CSV receives the complete audit trail.
        if "report" in payload:
            report = payload["report"]
            audit = payload.get("audit") or {}
            conflict_items = audit.get("conflicts", [])
            ambiguous_items = audit.get("ambiguous", [])
            regression_items = audit.get("regressions", [])
        else:
            report = payload
            conflict_items = report.get("conflicts", {}).get("items", [])
            ambiguous_items = report.get("ambiguous", [])
            regression_items = report.get("coverage", {}).get("regressions", [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "call", "date", "band", "mode", "field", "qrz", "lotw", "resolution", "severity", "reason"])
        for item in conflict_items:
            writer.writerow([
                "conflict", item.get("call", ""), item.get("date", ""), item.get("band", ""),
                item.get("mode", ""), item.get("field", ""), item.get("qrz", ""),
                item.get("lotw", ""), item.get("resolution", ""), item.get("severity", ""),
                item.get("reason", ""),
            ])
        for item in ambiguous_items:
            writer.writerow([
                "ambiguous", item.get("call", ""), item.get("date", ""), item.get("band", ""),
                item.get("mode", ""), "", "", "", "", "review", item.get("reason", ""),
            ])
        for item in regression_items:
            writer.writerow([
                "coverage_regression", "", "", "", "", item.get("metric", ""),
                item.get("qrz", ""), item.get("lotw", ""), item.get("master", ""),
                item.get("severity", "critical"), item.get("reason", ""),
            ])
        return output.getvalue()

    def _parse(self, content: str, label: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        text = str(content or "")
        if not text.strip():
            raise AwardMasterError(f"O arquivo {label} está vazio")
        records, errors = ADIFParser().parse(text)
        records = [self._clean_record(record, label) for record in records if record and record.get("CALL")]
        if not records:
            raise AwardMasterError(f"Nenhum QSO válido foi encontrado no arquivo {label}")
        return records, errors

    def _clean_record(self, record: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                continue
            name = str(key).strip().upper()
            if not name:
                continue
            normalized = value.strip() if isinstance(value, str) else value
            if name == "IOTA" and self._text(normalized).upper() in INVALID_IOTA_VALUES:
                self._sanitization["iota_placeholder_removed"] += 1
                continue
            if name == "GRIDSQUARE":
                original = self._text(normalized).upper()
                repaired = self._sanitize_grid(original)
                if repaired != original:
                    if repaired:
                        self._sanitization["malformed_grid_reduced_to_valid_prefix"] += 1
                        reason = (
                            f"Grid Maidenhead malformado em {label}; preservado somente o maior prefixo válido "
                            f"({original} -> {repaired})."
                        )
                    else:
                        self._sanitization["malformed_grid_removed"] += 1
                        reason = (
                            f"Grid Maidenhead malformado em {label}; nenhum prefixo válido de 4/6/8 caracteres "
                            "foi encontrado e o campo foi omitido."
                        )
                    self._source_sanitization_conflicts.append({
                        "call": self._text(record.get("CALL")),
                        "date": self._text(record.get("QSO_DATE")),
                        "band": self._text(record.get("BAND")),
                        "mode": self._canonical_mode(record),
                        "field": "GRIDSQUARE",
                        "qrz": original if label.upper() == "QRZ" else "",
                        "lotw": original if label.upper() == "LOTW" else "",
                        "resolution": repaired,
                        "winner": "sanitizer",
                        "severity": "warning",
                        "reason": reason,
                    })
                if not repaired:
                    continue
                normalized = repaired
            cleaned[name] = normalized
        return cleaned

    @staticmethod
    def _sanitize_grid(value: Any) -> str:
        grid = str(value or "").strip().upper()
        if not grid:
            return ""
        pattern = GRID_PATTERNS.get(len(grid))
        if pattern and pattern.fullmatch(grid):
            return grid
        # Safe repair: never invent characters. Keep only the longest complete,
        # syntactically valid Maidenhead prefix already present in the source.
        for length in (8, 6, 4):
            if len(grid) > length and GRID_PATTERNS[length].fullmatch(grid[:length]):
                return grid[:length]
        return ""

    def _match(
        self, qrz_records: Sequence[Dict[str, Any]], lotw_records: Sequence[Dict[str, Any]]
    ) -> Tuple[List[Pair], set[int], set[int], List[Dict[str, Any]]]:
        qrz_unmatched = set(range(len(qrz_records)))
        lotw_unmatched = set(range(len(lotw_records)))
        pairs: List[Pair] = []
        ambiguous: List[Dict[str, Any]] = []

        qrz_exact = defaultdict(list)
        lotw_exact = defaultdict(list)
        for i, record in enumerate(qrz_records):
            qrz_exact[self._exact_key(record)].append(i)
        for i, record in enumerate(lotw_records):
            lotw_exact[self._exact_key(record)].append(i)

        for key in sorted(set(qrz_exact).intersection(lotw_exact), key=str):
            left, right = qrz_exact[key], lotw_exact[key]
            if len(left) == 1 and len(right) == 1:
                qi, li = left[0], right[0]
                pairs.append(Pair(qi, li, "EXACT", 0))
                qrz_unmatched.discard(qi)
                lotw_unmatched.discard(li)

        qrz_groups = defaultdict(list)
        lotw_groups = defaultdict(list)
        for i in qrz_unmatched:
            qrz_groups[self._group_key(qrz_records[i])].append(i)
        for i in lotw_unmatched:
            lotw_groups[self._group_key(lotw_records[i])].append(i)

        for key in sorted(set(qrz_groups).intersection(lotw_groups), key=str):
            left = qrz_groups[key]
            right = lotw_groups[key]
            edges: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
            reverse: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
            for qi in left:
                for li in right:
                    delta = self._time_delta(qrz_records[qi], lotw_records[li])
                    if delta is None or delta > self.MATCH_WINDOW_SECONDS:
                        continue
                    if not self._frequency_compatible(qrz_records[qi], lotw_records[li]):
                        continue
                    edges[qi].append((li, delta))
                    reverse[li].append((qi, delta))

            for qi in left:
                options = edges.get(qi, [])
                if len(options) != 1:
                    continue
                li, delta = options[0]
                if len(reverse.get(li, [])) != 1:
                    continue
                pairs.append(Pair(qi, li, "NEAR_TIME", delta))
                qrz_unmatched.discard(qi)
                lotw_unmatched.discard(li)

            risky_left = [qi for qi in left if qi in qrz_unmatched and edges.get(qi)]
            risky_right = [li for li in right if li in lotw_unmatched and reverse.get(li)]
            if risky_left or risky_right:
                sample = qrz_records[risky_left[0]] if risky_left else lotw_records[risky_right[0]]
                ambiguous.append({
                    "call": self._text(sample.get("CALL")),
                    "date": self._text(sample.get("QSO_DATE")),
                    "band": self._text(sample.get("BAND")),
                    "mode": self._canonical_mode(sample),
                    "qrz_candidates": len(risky_left),
                    "lotw_candidates": len(risky_right),
                    "reason": "Mais de um pareamento possível dentro da janela segura; registros foram preservados separadamente.",
                })

        pairs.sort(key=lambda p: (p.qrz_index, p.lotw_index))
        return pairs, qrz_unmatched, lotw_unmatched, ambiguous

    def _merge_pair(
        self, qrz: Dict[str, Any], lotw: Dict[str, Any], pair: Pair
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, int]]:
        result = dict(qrz)
        conflicts: List[Dict[str, Any]] = []
        source_counts = defaultdict(int)
        source_counts["QRZ"] += len(result)

        for field, value in lotw.items():
            if field not in result or self._empty(result.get(field)):
                result[field] = value
                source_counts["LOTW"] += 1

        for field in LOTW_AUTHORITY_FIELDS:
            qv, lv = qrz.get(field), lotw.get(field)
            if self._empty(lv):
                continue
            if not self._empty(qv) and not self._equivalent(field, qv, lv):
                conflicts.append(self._conflict(
                    qrz, lotw, field, qv, lv, lv, "lotw",
                    "LoTW confirmado prevalece para este metadado geográfico de award."
                ))
            result[field] = lv
            source_counts["LOTW"] += 1

        for field in ZONE_FIELDS:
            chosen_zone, zone_winner, zone_reason = self._choose_zone(field, qrz, lotw)
            qv, lv = qrz.get(field), lotw.get(field)
            if chosen_zone:
                result[field] = chosen_zone
                source_counts["LOTW" if zone_winner.startswith("lotw") else "QRZ"] += 1
                result[f"APP_QSOMGR_{field}_SOURCE"] = zone_winner.upper()
            else:
                result.pop(field, None)
                result[f"APP_QSOMGR_{field}_SOURCE"] = zone_winner.upper()
            if (not self._empty(qv) or not self._empty(lv)) and (
                not chosen_zone or
                (not self._empty(qv) and not self._equivalent(field, qv, chosen_zone)) or
                (not self._empty(lv) and not self._equivalent(field, lv, chosen_zone))
            ):
                conflicts.append(self._conflict(
                    qrz, lotw, field, qv, lv, chosen_zone, zone_winner,
                    zone_reason, severity="warning"
                ))

        q_grid, l_grid = self._text(qrz.get("GRIDSQUARE")).upper(), self._text(lotw.get("GRIDSQUARE")).upper()
        chosen_grid, grid_winner, grid_reason = self._choose_grid(q_grid, l_grid, lotw)
        if chosen_grid:
            result["GRIDSQUARE"] = chosen_grid
            source_counts["LOTW" if grid_winner == "lotw" else "QRZ"] += 1
        else:
            result.pop("GRIDSQUARE", None)
        if (q_grid or l_grid) and (chosen_grid != q_grid or (l_grid and chosen_grid != l_grid)):
            conflicts.append(self._conflict(
                qrz, lotw, "GRIDSQUARE", q_grid, l_grid, chosen_grid, grid_winner,
                grid_reason, severity="warning"
            ))

        q_iota = self._text(qrz.get("IOTA")).upper()
        l_iota = self._text(lotw.get("IOTA")).upper()
        if l_iota and self._lotw_confirmed(lotw):
            result["IOTA"] = lotw["IOTA"]
            if q_iota and q_iota != l_iota:
                conflicts.append(self._conflict(
                    qrz, lotw, "IOTA", qrz.get("IOTA"), lotw.get("IOTA"), lotw.get("IOTA"),
                    "lotw", "IOTA confirmado pelo LoTW prevalece sobre metadado conflitante do QRZ.",
                    severity="warning",
                ))
        elif q_iota:
            result["IOTA"] = qrz["IOTA"]
        elif l_iota:
            result["IOTA"] = lotw["IOTA"]
        else:
            result.pop("IOTA", None)

        # MODE may legitimately be encoded differently by providers
        # (e.g. QRZ MODE=FT4 versus LoTW MODE=MFSK/SUBMODE=FT4).
        # Compare canonical operating identity, never raw provider encoding.
        for field in ("CALL", "QSO_DATE", "BAND"):
            qv, lv = qrz.get(field), lotw.get(field)
            if self._empty(qv) or self._empty(lv):
                continue
            if not self._equivalent(field, qv, lv):
                conflicts.append(self._conflict(
                    qrz, lotw, field, qv, lv, qv, "qrz",
                    "Campos de identidade nunca são sobrescritos silenciosamente.",
                    severity="critical",
                ))

        if pair.kind == "EXACT" and self._time_key(qrz) != self._time_key(lotw):
            conflicts.append(self._conflict(
                qrz, lotw, "TIME_ON", qrz.get("TIME_ON"), lotw.get("TIME_ON"),
                qrz.get("TIME_ON"), "qrz",
                "Horário divergente em um pareamento que deveria ser exato.",
                severity="critical",
            ))

        q_mode, l_mode = self._canonical_mode(qrz), self._canonical_mode(lotw)
        if q_mode and l_mode and q_mode != l_mode:
            conflicts.append(self._conflict(
                qrz, lotw, "MODE", q_mode, l_mode, q_mode, "qrz",
                "Modos canônicos divergentes; pareamento exige revisão.",
                severity="critical",
            ))

        q_freq, l_freq = qrz.get("FREQ"), lotw.get("FREQ")
        if (
            not self._empty(q_freq)
            and not self._empty(l_freq)
            and not self._frequency_compatible(qrz, lotw)
        ):
            conflicts.append(self._conflict(
                qrz, lotw, "FREQ", q_freq, l_freq, q_freq, "qrz",
                "Frequências diferem mais de 20 kHz; QSO preservado e conflito auditado.",
                severity="warning",
            ))

        result = self._normalize_lotw_confirmation(result, lotw)
        result["APP_QSOMGR_SOURCES"] = "QRZ,LOTW"
        result["APP_QSOMGR_MATCH"] = pair.kind
        return result, conflicts, dict(source_counts)

    def _normalize_lotw_confirmation(
        self, record: Dict[str, Any], lotw_record: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        source = lotw_record or record
        if self._text(source.get("QSL_RCVD")).upper() == "Y":
            record["LOTW_QSL_RCVD"] = "Y"
        if not self._empty(source.get("QSLRDATE")):
            record["LOTW_QSLRDATE"] = source["QSLRDATE"]
        if self._text(source.get("QSL_SENT")).upper() == "Y":
            record["LOTW_QSL_SENT"] = "Y"
        return record

    def _choose_grid(
        self, qrz: str, lotw: str, lotw_record: Dict[str, Any]
    ) -> Tuple[str, str, str]:
        invalid = self._text(lotw_record.get("APP_LOTW_GRIDSQUARE_INVALID")).upper()
        if invalid and qrz and self._same_grid_value(qrz, invalid):
            self._sanitization["lotw_explicit_invalid_grid_removed"] += 1
            if lotw and not self._same_grid_value(lotw, invalid):
                return lotw, "lotw", "LoTW marcou explicitamente o grid do QRZ como inválido e forneceu substituto."
            return "", "lotw_invalid", "LoTW marcou explicitamente o grid do QRZ como inválido; nenhum substituto válido foi fornecido."
        if not qrz:
            return lotw, "lotw" if lotw else "none", "QRZ sem grid; usado LoTW quando disponível."
        if not lotw:
            return qrz, "qrz", "LoTW sem grid válido; preservado QRZ."
        if qrz[:4] == lotw[:4]:
            chosen = qrz if len(qrz) >= len(lotw) else lotw
            return chosen, "qrz" if chosen == qrz else "lotw", "Mesmo grid-base; preservada a maior precisão."
        if self._lotw_confirmed(lotw_record):
            return lotw, "lotw", "Grids válidos divergem; localização confirmada pelo LoTW prevalece e o conflito permanece auditado."
        return qrz, "qrz", "Grids divergem sem confirmação LoTW; preservado QRZ e o conflito permanece auditado."

    def _choose_zone(
        self, field: str, qrz: Dict[str, Any], lotw: Dict[str, Any]
    ) -> Tuple[str, str, str]:
        qv = self._zone_value(qrz.get(field))
        lv = self._zone_value(lotw.get(field))
        invalid_field = f"APP_LOTW_{field}_INVALID"
        inferred_field = f"APP_LOTW_{field}_INFERRED"
        invalid = self._zone_value(lotw.get(invalid_field))
        inferred = self._text(lotw.get(inferred_field)).upper() == "Y"

        if invalid and qv and qv == invalid:
            self._sanitization[f"lotw_explicit_invalid_{field.lower()}"] += 1
            if lv and lv != invalid:
                return lv, "lotw_corrected", f"LoTW marcou {field}={invalid} como inválido e forneceu {lv}."
            return "", "lotw_invalid", f"LoTW marcou {field}={invalid} como inválido e não forneceu substituto."

        if inferred and lv:
            if qv and qv != lv:
                self._sanitization[f"lotw_inferred_{field.lower()}_used"] += 1
            return lv, "lotw_inferred", f"LoTW forneceu {field} inferido explicitamente."

        if not qv:
            return lv, "lotw" if lv else "none", f"QRZ sem {field}; usado LoTW quando disponível."
        if not lv:
            return qv, "qrz", f"LoTW sem {field}; preservado QRZ."
        if qv == lv:
            return qv, "consensus", f"QRZ e LoTW concordam em {field}."

        q_grid = self._text(qrz.get("GRIDSQUARE")).upper()
        l_grid = self._text(lotw.get("GRIDSQUARE")).upper()
        same_grid = bool(q_grid and l_grid and q_grid[:4] == l_grid[:4])
        same_dxcc = bool(
            self._text(qrz.get("DXCC")) and
            self._text(qrz.get("DXCC")) == self._text(lotw.get("DXCC"))
        )
        if same_grid and same_dxcc and not invalid and not inferred:
            self._sanitization[f"unexplained_{field.lower()}_conflict_kept_qrz"] += 1
            return qv, "qrz_review", (
                f"QRZ e LoTW descrevem a mesma localização (DXCC/grid-base), mas divergem em {field}; "
                "sem sinalizador nativo de correção do LoTW, o QRZ foi preservado e o caso ficou auditado."
            )
        if self._lotw_confirmed(lotw):
            return lv, "lotw", f"Fontes divergem em {field}; LoTW confirmado prevalece e o conflito permanece auditado."
        return qv, "qrz", f"Fontes divergem em {field} sem confirmação LoTW; preservado QRZ."

    def _build_lotw_location_consensus(
        self, records: Sequence[Dict[str, Any]]
    ) -> Dict[str, Dict[Tuple[str, ...], Dict[str, str]]]:
        # Two evidence layers are built from confirmed LoTW metadata:
        # 1) same callsign + DXCC + grid (strongest historical evidence);
        # 2) same DXCC + grid across different callsigns (geographic evidence).
        #
        # The second layer is NEVER allowed to override QRZ+LoTW consensus.
        # It is only used when the selected zone still comes exclusively from QRZ.
        buckets: Dict[str, Dict[Tuple[str, ...], Dict[str, List[str]]]] = {
            "call_grid4": defaultdict(lambda: defaultdict(list)),
            "call_grid6": defaultdict(lambda: defaultdict(list)),
            "call_grid8": defaultdict(lambda: defaultdict(list)),
            "dxcc_grid4": defaultdict(lambda: defaultdict(list)),
            "dxcc_grid6": defaultdict(lambda: defaultdict(list)),
            "dxcc_grid8": defaultdict(lambda: defaultdict(list)),
        }
        for record in records:
            if not self._lotw_confirmed(record):
                continue
            grid = self._text(record.get("GRIDSQUARE")).upper()
            dxcc = self._text(record.get("DXCC"))
            call = self._text(record.get("CALL")).upper()
            if len(grid) < 4 or not dxcc:
                continue

            keys = [("dxcc_grid4", (dxcc, grid[:4]))]
            if call:
                keys.append(("call_grid4", (call, dxcc, grid[:4])))
            if len(grid) >= 6:
                keys.append(("dxcc_grid6", (dxcc, grid[:6])))
                if call:
                    keys.append(("call_grid6", (call, dxcc, grid[:6])))
            if len(grid) >= 8:
                keys.append(("dxcc_grid8", (dxcc, grid[:8])))
                if call:
                    keys.append(("call_grid8", (call, dxcc, grid[:8])))

            for field in ZONE_FIELDS:
                value = self._zone_value(record.get(field))
                invalid = self._zone_value(record.get(f"APP_LOTW_{field}_INVALID"))
                if not value or value == invalid:
                    continue
                for kind, key in keys:
                    buckets[kind][key][field].append(value)

        result: Dict[str, Dict[Tuple[str, ...], Dict[str, str]]] = {
            "call_grid4": {},
            "call_grid6": {},
            "call_grid8": {},
            "dxcc_grid4": {},
            "dxcc_grid6": {},
            "dxcc_grid8": {},
        }
        for kind, groups in buckets.items():
            minimum = 5 if kind == "dxcc_grid4" else 2
            for key, fields in groups.items():
                accepted: Dict[str, str] = {}
                for field, values in fields.items():
                    counts = defaultdict(int)
                    for value in values:
                        counts[value] += 1
                    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
                    value, count = ranked[0]
                    total = len(values)
                    if total >= minimum and count == total:
                        accepted[field] = value
                if accepted:
                    result[kind][key] = accepted
        return result

    def _apply_lotw_location_consensus(
        self,
        records: Sequence[Dict[str, Any]],
        consensus: Dict[str, Dict[Tuple[str, ...], Dict[str, str]]],
        conflicts: List[Dict[str, Any]],
    ) -> None:
        for record in records:
            grid = self._text(record.get("GRIDSQUARE")).upper()
            dxcc = self._text(record.get("DXCC"))
            call = self._text(record.get("CALL")).upper()
            if len(grid) < 4 or not dxcc:
                continue

            call_values: Dict[str, str] = {}
            call_scope = ""
            geo_values: Dict[str, str] = {}
            geo_scope = ""

            # Never fall back from a precise locator to a coarser geographic
            # consensus. A grid8 record may use only grid8 evidence; grid6 may
            # use only grid6; grid4 may use only grid4.
            if len(grid) >= 8:
                if call:
                    call_values = consensus.get("call_grid8", {}).get((call, dxcc, grid[:8]), {})
                    if call_values:
                        call_scope = "same-call/DXCC/grid8"
                    else:
                        # Same station + same DXCC may safely use its own
                        # confirmed grid4 history when the precise suffix
                        # changed over time. Cross-callsign evidence never
                        # receives this fallback.
                        call_values = consensus.get("call_grid4", {}).get((call, dxcc, grid[:4]), {})
                        if call_values:
                            call_scope = "same-call/DXCC/grid4-for-precise-grid"
                geo_values = consensus.get("dxcc_grid8", {}).get((dxcc, grid[:8]), {})
                if geo_values:
                    geo_scope = "DXCC/grid8"
            elif len(grid) >= 6:
                if call:
                    call_values = consensus.get("call_grid6", {}).get((call, dxcc, grid[:6]), {})
                    if call_values:
                        call_scope = "same-call/DXCC/grid6"
                    else:
                        call_values = consensus.get("call_grid4", {}).get((call, dxcc, grid[:4]), {})
                        if call_values:
                            call_scope = "same-call/DXCC/grid4-for-precise-grid"
                geo_values = consensus.get("dxcc_grid6", {}).get((dxcc, grid[:6]), {})
                if geo_values:
                    geo_scope = "DXCC/grid6"
            else:
                if call:
                    call_values = consensus.get("call_grid4", {}).get((call, dxcc, grid[:4]), {})
                    if call_values:
                        call_scope = "same-call/DXCC/grid4"
                geo_values = consensus.get("dxcc_grid4", {}).get((dxcc, grid[:4]), {})
                if geo_values:
                    geo_scope = "DXCC/grid4"

            for field in ZONE_FIELDS:
                current = self._zone_value(record.get(field))
                source = self._text(record.get(f"APP_QSOMGR_{field}_SOURCE")).upper()
                record_sources = self._text(record.get("APP_QSOMGR_SOURCES")).upper()

                # Values supplied by LoTW, agreed by QRZ+LoTW, explicitly
                # corrected/inferred by LoTW, or held for review are final.
                # Only a QRZ-derived zone may be normalized by historical/
                # geographic LoTW evidence.
                if source not in {"QRZ", ""}:
                    continue
                if source == "" and record_sources != "QRZ":
                    continue

                candidate = call_values.get(field)
                winner = "lotw_history"
                target_source = "LOTW_HISTORY"
                if candidate:
                    scope = call_scope
                    reason = (
                        f"{field} normalizado por {scope} com pelo menos duas confirmações LoTW unânimes."
                    )
                    metric = f"{field.lower()}_normalized_by_same_call_lotw_history"
                else:
                    candidate = geo_values.get(field)
                    if not candidate:
                        continue
                    scope = geo_scope
                    winner = "lotw_geo_consensus"
                    target_source = "LOTW_GEO_CONSENSUS"
                    threshold = "duas" if scope.endswith("grid6") else "cinco"
                    reason = (
                        f"{field} normalizado por {scope} no mesmo DXCC com pelo menos {threshold} "
                        "confirmações LoTW unânimes; somente valor derivado do QRZ pode ser alterado."
                    )
                    metric = f"{field.lower()}_normalized_by_lotw_geo_consensus"

                if candidate == current:
                    continue

                conflicts.append(self._conflict(
                    record, {}, field, current, candidate, candidate, winner,
                    reason, severity="warning",
                ))
                record[field] = candidate
                record[f"APP_QSOMGR_{field}_SOURCE"] = target_source
                self._sanitization[metric] += 1

    def _collapse_lotw_only_near_duplicates(
        self,
        merged: List[Dict[str, Any]],
        lotw_only_records: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        if not lotw_only_records:
            return lotw_only_records, 0

        candidate_indexes = [
            i for i, record in enumerate(merged)
            if self._text(record.get("APP_QSOMGR_SOURCES")).upper() == "QRZ,LOTW"
        ]
        edges: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        reverse: Dict[int, List[Tuple[int, int]]] = defaultdict(list)

        for li, lotw in enumerate(lotw_only_records):
            for mi in candidate_indexes:
                target = merged[mi]
                if self._group_key(lotw) != self._group_key(target):
                    continue
                delta = self._time_delta(lotw, target)
                if delta is None or delta > self.MATCH_WINDOW_SECONDS:
                    continue
                if not self._frequency_compatible(lotw, target):
                    continue
                edges[li].append((mi, delta))
                reverse[mi].append((li, delta))

        collapsed: set[int] = set()
        for li, options in edges.items():
            if len(options) != 1:
                continue
            mi, delta = options[0]
            if len(reverse.get(mi, [])) != 1:
                continue

            lotw = lotw_only_records[li]
            target = merged[mi]

            # Preserve the already reconciled QSO as the canonical identity.
            # The duplicate LoTW row may enrich only fields that are empty.
            for field, value in lotw.items():
                if field in IDENTITY_FIELDS or field.startswith("APP_QSOMGR_"):
                    continue
                if self._empty(target.get(field)) and not self._empty(value):
                    target[field] = value

            self._normalize_lotw_confirmation(target, lotw)
            target["APP_QSOMGR_LOTW_DUP_COLLAPSED"] = "Y"
            target["APP_QSOMGR_LOTW_DUP_DELTA_SEC"] = str(delta)

            conflicts.append({
                "call": self._text(target.get("CALL")),
                "date": self._text(target.get("QSO_DATE")),
                "band": self._text(target.get("BAND")),
                "mode": self._canonical_mode(target),
                "field": "QSO_DUPLICATE",
                "qrz": self._text(target.get("TIME_ON")),
                "lotw": self._text(lotw.get("TIME_ON")),
                "resolution": "COLLAPSED_INTO_RECONCILED_QSO",
                "winner": "existing_qrz_lotw",
                "severity": "warning",
                "reason": (
                    "Registro somente-LoTW colapsado no QSO QRZ+LoTW já reconciliado: "
                    "mesmo indicativo/data/banda/modo, frequência compatível e pareamento "
                    "único e recíproco dentro de 120 segundos."
                ),
            })
            collapsed.add(li)
            self._sanitization["lotw_only_near_duplicate_collapsed"] += 1

        retained = [
            record for i, record in enumerate(lotw_only_records)
            if i not in collapsed
        ]
        return retained, len(collapsed)

    @staticmethod
    def _lotw_confirmed(record: Dict[str, Any]) -> bool:
        return (
            str(record.get("QSL_RCVD") or "").strip().upper() == "Y"
            or str(record.get("APP_LOTW_2XQSL") or "").strip().upper() == "Y"
            or str(record.get("LOTW_QSL_RCVD") or "").strip().upper() == "Y"
        )

    @staticmethod
    def _same_grid_value(a: str, b: str) -> bool:
        left, right = str(a or "").strip().upper(), str(b or "").strip().upper()
        if not left or not right:
            return False
        return left == right or (len(left) >= 4 and len(right) >= 4 and left[:4] == right[:4])

    def _coverage_regressions(
        self, source_metrics: Dict[str, Dict[str, int]], master: Dict[str, int]
    ) -> List[Dict[str, Any]]:
        watched = [
            "callsigns", "dxcc", "grids4", "iota", "us_states_all",
            "ft8_10m_states", "ft8_12m_states", "ft8_15m_states",
            "ft4_10m_states", "ft4_12m_states", "ft4_15m_states",
        ]
        regressions = []
        for metric in watched:
            qrz = int(source_metrics["QRZ"].get(metric, 0))
            lotw = int(source_metrics["LOTW"].get(metric, 0))
            actual = int(master.get(metric, 0))
            expected = max(qrz, lotw)
            if actual < expected:
                severity = "warning" if metric == "grids4" else "critical"
                regressions.append({
                    "metric": metric,
                    "qrz": qrz,
                    "lotw": lotw,
                    "master": actual,
                    "expected_minimum": expected,
                    "severity": severity,
                    "reason": (
                        "Há grids conflitantes entre as fontes. O Master adotou a localização conservadora "
                        "sem duplicar o QSO; a diferença fica auditada, mas não bloqueia o arquivo."
                        if metric == "grids4"
                        else
                        "O Master ficou abaixo da melhor fonte nesta dimensão protegida; "
                        "a exportação certificada foi bloqueada."
                    ),
                })
        return regressions

    def _metrics(self, records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        calls, dxcc, grids4, iotas, states = set(), set(), set(), set(), set()
        per_band_mode = defaultdict(set)
        count = 0
        for record in records:
            count += 1
            call = self._text(record.get("CALL")).upper()
            if call:
                calls.add(call)
            entity = self._text(record.get("DXCC"))
            if entity:
                dxcc.add(entity)
            grid = self._text(record.get("GRIDSQUARE")).upper()
            if len(grid) >= 4:
                grids4.add(grid[:4])
            iota = self._text(record.get("IOTA")).upper()
            if iota:
                iotas.add(iota)
            state = self._text(record.get("STATE")).upper()
            if state in US_STATES:
                states.add(state)
                per_band_mode[(self._canonical_mode(record), self._text(record.get("BAND")).upper())].add(state)
        return {
            "records": count,
            "callsigns": len(calls),
            "dxcc": len(dxcc),
            "grids4": len(grids4),
            "iota": len(iotas),
            "us_states_all": len(states),
            "ft8_10m_states": len(per_band_mode[("FT8", "10M")]),
            "ft8_12m_states": len(per_band_mode[("FT8", "12M")]),
            "ft8_15m_states": len(per_band_mode[("FT8", "15M")]),
            "ft4_10m_states": len(per_band_mode[("FT4", "10M")]),
            "ft4_12m_states": len(per_band_mode[("FT4", "12M")]),
            "ft4_15m_states": len(per_band_mode[("FT4", "15M")]),
        }

    def _write_adif(self, records: Sequence[Dict[str, Any]]) -> str:
        header = (
            "<ADIF_VER:5>3.1.4\n"
            "<PROGRAMID:11>QSO-MANAGER\n"
            f"<PROGRAMVERSION:{len(__version__)}>{__version__}\n"
            "<COMMENT:65>Award-safe QRZ+LoTW master; read-only merge with audit guardrails\n"
            "<EOH>\n"
        )
        preferred = [
            "CALL", "QSO_DATE", "TIME_ON", "BAND", "FREQ", "MODE", "SUBMODE",
            "STATE", "CNTY", "COUNTRY", "DXCC", "GRIDSQUARE", "IOTA", "CQZ", "ITUZ",
            "PFX", "CONT", "QSL_RCVD", "QSLRDATE", "LOTW_QSL_RCVD", "LOTW_QSLRDATE",
            "EQSL_QSL_RCVD", "EQSL_QSLRDATE", "APP_QSOMGR_SOURCES", "APP_QSOMGR_MATCH",
        ]
        rows = [header]
        for record in records:
            keys = []
            seen = set()
            for key in preferred:
                if key in record and not self._empty(record[key]):
                    keys.append(key)
                    seen.add(key)
            for key in sorted(record):
                if key not in seen and not self._empty(record[key]):
                    keys.append(key)
            fields = []
            for key in keys:
                value = self._output_value(key, record[key])
                if value == "":
                    continue
                fields.append(f"<{key}:{len(value)}>{value}")
            rows.append("\n".join(fields) + "\n<EOR>\n")
        return "".join(rows)

    @staticmethod
    def _output_value(field: str, value: Any) -> str:
        text = str(value)
        if field == "QSO_DATE":
            return text.replace("-", "")
        if field in {"TIME_ON", "TIME_OFF"}:
            return text.replace(":", "")
        return text

    def _conflict(
        self, qrz: Dict[str, Any], lotw: Dict[str, Any], field: str, qv: Any, lv: Any,
        resolution: Any, winner: str, reason: str, severity: str = "warning"
    ) -> Dict[str, Any]:
        return {
            "call": self._text(qrz.get("CALL") or lotw.get("CALL")),
            "date": self._text(qrz.get("QSO_DATE") or lotw.get("QSO_DATE")),
            "band": self._text(qrz.get("BAND") or lotw.get("BAND")),
            "mode": self._canonical_mode(qrz or lotw),
            "field": field,
            "qrz": self._text(qv),
            "lotw": self._text(lv),
            "resolution": self._text(resolution),
            "winner": winner,
            "severity": severity,
            "reason": reason,
        }

    def _exact_key(self, record: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        return (*self._group_key(record), self._time_key(record))

    def _group_key(self, record: Dict[str, Any]) -> Tuple[str, str, str, str]:
        return (
            self._text(record.get("CALL")).upper(),
            self._text(record.get("QSO_DATE")),
            self._text(record.get("BAND")).upper(),
            self._canonical_mode(record),
        )

    def _time_key(self, record: Dict[str, Any]) -> str:
        return self._text(record.get("TIME_ON"))[:8]

    def _time_delta(self, a: Dict[str, Any], b: Dict[str, Any]) -> Optional[int]:
        ta, tb = self._seconds(a.get("TIME_ON")), self._seconds(b.get("TIME_ON"))
        if ta is None or tb is None:
            return None
        return abs(ta - tb)

    @staticmethod
    def _seconds(value: Any) -> Optional[int]:
        text = str(value or "").replace(":", "")
        if len(text) < 4 or not text[:4].isdigit():
            return None
        text = (text + "00")[:6]
        try:
            return int(text[:2]) * 3600 + int(text[2:4]) * 60 + int(text[4:6])
        except ValueError:
            return None

    @staticmethod
    def _frequency_compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        av, bv = a.get("FREQ"), b.get("FREQ")
        if av in (None, "") or bv in (None, ""):
            return True
        try:
            return abs(float(av) - float(bv)) <= 0.020
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _canonical_mode(record: Dict[str, Any]) -> str:
        sub = str(record.get("SUBMODE") or "").upper().strip()
        mode = str(record.get("MODE") or "").upper().strip()
        if sub:
            return sub
        return mode

    @classmethod
    def _equivalent(cls, field: str, a: Any, b: Any) -> bool:
        if field == "FREQ":
            try:
                return abs(float(a) - float(b)) <= 0.0005
            except (TypeError, ValueError):
                pass
        if field in ZONE_FIELDS:
            return cls._zone_value(a) == cls._zone_value(b)
        return str(a).strip().upper() == str(b).strip().upper()

    @staticmethod
    def _zone_value(value: Any) -> str:
        text = "" if value is None else str(value).strip().upper()
        if text.isdigit():
            return str(int(text))
        return text

    @staticmethod
    def _empty(value: Any) -> bool:
        return value is None or str(value).strip() == ""

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    def _sort_key(self, record: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        return (
            self._text(record.get("QSO_DATE")), self._time_key(record),
            self._text(record.get("CALL")).upper(), self._text(record.get("BAND")).upper(),
            self._canonical_mode(record),
        )
