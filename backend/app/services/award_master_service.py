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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..adif.parser import ADIFParser
from ..core.version import __version__


US_STATES = {
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD",
    "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH",
    "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}

IDENTITY_FIELDS = ("CALL", "QSO_DATE", "TIME_ON", "BAND", "MODE", "SUBMODE", "FREQ")
LOTW_AUTHORITY_FIELDS = ("STATE", "CNTY", "DXCC", "COUNTRY", "CQZ", "ITUZ", "PFX", "CONT")


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
        qrz_records, qrz_errors = self._parse(qrz_content, "QRZ")
        lotw_records, lotw_errors = self._parse(lotw_content, "LoTW")
        pairs, qrz_unmatched, lotw_unmatched, ambiguous = self._match(qrz_records, lotw_records)

        merged: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
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
            merged.append(record)
            field_sources["QRZ"] += len(record)

        for index in sorted(lotw_unmatched):
            record = self._normalize_lotw_confirmation(dict(lotw_records[index]))
            record["APP_QSOMGR_SOURCES"] = "LOTW"
            merged.append(record)
            field_sources["LOTW"] += len(record)

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
                "lotw_only": len(lotw_unmatched),
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
        }

        content = self._write_adif(merged)
        report["master_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return {"content": content, "report": report}

    def certified_export(self, qrz_content: str, lotw_content: str) -> Dict[str, Any]:
        result = self.build(qrz_content, lotw_content)
        if not result["report"]["safe_to_export"]:
            raise AwardMasterError(
                "O Master ADIF exige revisão: há regressão crítica de cobertura, conflito crítico "
                "ou pareamento ambíguo. Nenhum arquivo certificado foi gerado."
            )
        return result

    def audit_csv(self, report: Dict[str, Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "call", "date", "band", "mode", "field", "qrz", "lotw", "resolution", "severity", "reason"])
        for item in report.get("conflicts", {}).get("items", []):
            writer.writerow([
                "conflict", item.get("call", ""), item.get("date", ""), item.get("band", ""),
                item.get("mode", ""), item.get("field", ""), item.get("qrz", ""),
                item.get("lotw", ""), item.get("resolution", ""), item.get("severity", ""),
                item.get("reason", ""),
            ])
        for item in report.get("ambiguous", []):
            writer.writerow([
                "ambiguous", item.get("call", ""), item.get("date", ""), item.get("band", ""),
                item.get("mode", ""), "", "", "", "", "review", item.get("reason", ""),
            ])
        for item in report.get("coverage", {}).get("regressions", []):
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
        records = [self._clean_record(record) for record in records if record and record.get("CALL")]
        if not records:
            raise AwardMasterError(f"Nenhum QSO válido foi encontrado no arquivo {label}")
        return records, errors

    @staticmethod
    def _clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                continue
            name = str(key).strip().upper()
            if not name:
                continue
            cleaned[name] = value.strip() if isinstance(value, str) else value
        return cleaned

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
                conflicts.append(self._conflict(qrz, lotw, field, qv, lv, lv, "lotw", "LoTW prevalece para identidade geográfica de award."))
            result[field] = lv
            source_counts["LOTW"] += 1

        q_grid, l_grid = self._text(qrz.get("GRIDSQUARE")).upper(), self._text(lotw.get("GRIDSQUARE")).upper()
        chosen_grid, grid_reason = self._choose_grid(q_grid, l_grid, lotw)
        if chosen_grid:
            result["GRIDSQUARE"] = chosen_grid
            source_counts["LOTW" if chosen_grid == l_grid and l_grid else "QRZ"] += 1
        if q_grid and l_grid and q_grid != l_grid and q_grid[:4] != l_grid[:4]:
            conflicts.append(self._conflict(qrz, lotw, "GRIDSQUARE", q_grid, l_grid, chosen_grid, "review", grid_reason, severity="warning"))

        if not self._empty(qrz.get("IOTA")):
            result["IOTA"] = qrz["IOTA"]
        elif not self._empty(lotw.get("IOTA")):
            result["IOTA"] = lotw["IOTA"]

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

    def _choose_grid(self, qrz: str, lotw: str, lotw_record: Dict[str, Any]) -> Tuple[str, str]:
        if not qrz:
            return lotw, "QRZ sem grid; usado LoTW."
        if not lotw:
            return qrz, "LoTW sem grid; preservado QRZ."
        if qrz[:4] == lotw[:4]:
            return (qrz if len(qrz) >= len(lotw) else lotw), "Mesmo grid-base; preservada a maior precisão."
        if self._text(lotw_record.get("STATE")).upper() in US_STATES:
            return lotw, "Conflito de grid em QSO dos EUA; LoTW prevalece para reduzir Grid-State mismatch."
        return lotw, "Conflito geográfico entre fontes; LoTW prevalece e o caso permanece auditado."

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

    @staticmethod
    def _equivalent(field: str, a: Any, b: Any) -> bool:
        if field == "FREQ":
            try:
                return abs(float(a) - float(b)) <= 0.0005
            except (TypeError, ValueError):
                pass
        return str(a).strip().upper() == str(b).strip().upper()

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
