"""Focused, read-only comparison of two ADIF exports.

This service intentionally does not write to the database.  It models the first
product workflow: give the application two ADIF files and receive a concise,
explainable list of presence differences, probable duplicates and relevant
field differences.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..adif.parser import ADIFParser
from ..models.models import CoverageType


@dataclass
class QSO:
    side: str
    index: int
    raw: Dict[str, Any]
    call: str
    date: str
    time: Optional[str]
    band: Optional[str]
    freq_hz: Optional[int]
    mode: Optional[str]
    submode: Optional[str]
    operating_mode: Optional[str]
    mode_family: Optional[str]
    rst_sent: Optional[str]
    rst_rcvd: Optional[str]
    grid: Optional[str]
    state: Optional[str]
    county: Optional[str]
    country: Optional[str]

    @property
    def seconds(self) -> Optional[int]:
        if not self.time:
            return None
        try:
            hh, mm, ss = self.time.split(":")
            return int(hh) * 3600 + int(mm) * 60 + int(ss)
        except (ValueError, AttributeError):
            return None


class ADIFComparisonService:
    """Compare exactly two ADIF snapshots without mutating application state."""

    AUTO_TIME_SECONDS = 60
    REVIEW_TIME_SECONDS = 300

    def __init__(self) -> None:
        self.parser = ADIFParser()

    def compare(
        self,
        content_a: str,
        content_b: str,
        source_a: str,
        source_b: str,
        coverage_a: str = "PARTIAL_EXPORT",
        coverage_b: str = "PARTIAL_EXPORT",
        filename_a: str = "source-a.adi",
        filename_b: str = "source-b.adi",
    ) -> Dict[str, Any]:
        records_a, errors_a = ADIFParser().parse(content_a)
        records_b, errors_b = ADIFParser().parse(content_b)
        a = self._normalize(records_a, "A")
        b = self._normalize(records_b, "B")

        matched, unmatched_a, unmatched_b, review_candidates = self._match(a, b)
        duplicates_a = self._probable_duplicates(a)
        duplicates_b = self._probable_duplicates(b)
        duplicate_ids_a = {idx for group in duplicates_a for idx in group["indexes"]}
        duplicate_ids_b = {idx for group in duplicates_b for idx in group["indexes"]}
        matched_ids_a = {left.index for left, _, _ in matched}
        matched_ids_b = {right.index for _, right, _ in matched}

        # A duplicate record that lost a one-to-one match to its near-identical
        # sibling is not reported as a missing QSO.
        unmatched_a = [q for q in unmatched_a if not (q.index in duplicate_ids_a and self._duplicate_has_matched_sibling(q, duplicates_a, matched_ids_a))]
        unmatched_b = [q for q in unmatched_b if not (q.index in duplicate_ids_b and self._duplicate_has_matched_sibling(q, duplicates_b, matched_ids_b))]

        missing_in_b = [
            self._missing_item(q, source_a, source_b, coverage_b, matched, review_candidates)
            for q in unmatched_a
        ]
        missing_in_a = [
            self._missing_item(q, source_b, source_a, coverage_a, [(r, l, m) for l, r, m in matched], self._swap_reviews(review_candidates))
            for q in unmatched_b
        ]

        field_differences: List[Dict[str, Any]] = []
        tolerated: List[Dict[str, Any]] = []
        for left, right, evidence in matched:
            important, soft = self._field_differences(left, right, source_a, source_b, evidence)
            field_differences.extend(important)
            tolerated.extend(soft)

        probable_duplicates = [
            self._duplicate_item(group, a, source_a) for group in duplicates_a
        ] + [
            self._duplicate_item(group, b, source_b) for group in duplicates_b
        ]

        return {
            "source_a": {"name": source_a, "filename": filename_a, "coverage": coverage_a, "records": len(a), "parse_errors": errors_a[:20]},
            "source_b": {"name": source_b, "filename": filename_b, "coverage": coverage_b, "records": len(b), "parse_errors": errors_b[:20]},
            "summary": {
                "records_a": len(a),
                "records_b": len(b),
                "matched": len(matched),
                "missing_in_a": len(missing_in_a),
                "missing_in_b": len(missing_in_b),
                "probable_duplicates": len(probable_duplicates),
                "field_differences": len(field_differences),
                "tolerated_differences": len(tolerated),
            },
            "missing_in_a": missing_in_a,
            "missing_in_b": missing_in_b,
            "probable_duplicates": probable_duplicates,
            "field_differences": field_differences,
            "tolerated_differences": tolerated,
        }

    def _normalize(self, records: Iterable[Dict[str, Any]], side: str) -> List[QSO]:
        out: List[QSO] = []
        for idx, record in enumerate(records):
            call = str(record.get("CALL") or "").strip().upper()
            date = str(record.get("QSO_DATE") or "").strip()
            if not call or not date:
                continue
            mode = str(record.get("MODE") or "").strip().upper() or None
            submode = str(record.get("SUBMODE") or "").strip().upper() or None
            operating_mode, mode_family = self.parser.classify_mode(mode or "", submode)
            freq = record.get("FREQ")
            try:
                freq_hz = round(float(freq) * 1_000_000) if freq is not None else None
            except (TypeError, ValueError):
                freq_hz = None
            out.append(QSO(
                side=side,
                index=idx,
                raw=record,
                call=call,
                date=date,
                time=record.get("TIME_ON"),
                band=(str(record.get("BAND")).upper() if record.get("BAND") else None),
                freq_hz=freq_hz,
                mode=mode,
                submode=submode,
                operating_mode=(operating_mode or None),
                mode_family=(mode_family or None),
                rst_sent=self._text(record.get("RST_SENT")),
                rst_rcvd=self._text(record.get("RST_RCVD")),
                grid=self._text(record.get("GRIDSQUARE") or record.get("GRID")),
                state=self._text(record.get("STATE")),
                county=self._text(record.get("CNTY") or record.get("COUNTY")),
                country=self._text(record.get("COUNTRY")),
            ))
        return out

    @staticmethod
    def _text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _mode_compatible(self, a: QSO, b: QSO) -> bool:
        if not a.operating_mode or not b.operating_mode:
            return True
        if a.operating_mode == b.operating_mode:
            return True
        return a.mode_family == b.mode_family == "SSB"

    def _freq_tolerance(self, a: QSO, b: QSO) -> int:
        family = a.mode_family if a.mode_family == b.mode_family else (a.mode_family or b.mode_family)
        if family == "CW":
            return 500
        if family in {"SSB", "FM"}:
            return 3000
        return 1000

    def _candidate(self, a: QSO, b: QSO) -> Optional[Dict[str, Any]]:
        if a.call != b.call or a.date != b.date:
            return None
        if a.band and b.band and a.band != b.band:
            return None

        time_diff = None
        if a.seconds is not None and b.seconds is not None:
            time_diff = abs(a.seconds - b.seconds)
            if time_diff > self.REVIEW_TIME_SECONDS:
                return None

        freq_diff = None
        if a.freq_hz is not None and b.freq_hz is not None:
            freq_diff = abs(a.freq_hz - b.freq_hz)

        mode_ok = self._mode_compatible(a, b)
        tolerance = self._freq_tolerance(a, b)
        freq_ok = freq_diff is None or freq_diff <= tolerance

        # A very tight call/date/time/frequency match can still be the same QSO
        # when one source labels the mode differently; keep it as a field conflict.
        tight_mode_exception = (
            time_diff is not None and time_diff <= 10 and
            (freq_diff is None or freq_diff <= tolerance)
        )
        if not mode_ok and not tight_mode_exception:
            return None

        if time_diff is not None and time_diff > self.AUTO_TIME_SECONDS:
            return {
                "kind": "review",
                "time_diff_seconds": time_diff,
                "freq_diff_hz": freq_diff,
                "mode_compatible": mode_ok,
            }
        if not freq_ok:
            return None

        score = 100.0
        if time_diff is None:
            score -= 18
        else:
            score -= min(time_diff, 60) * 0.25
        if freq_diff is None:
            score -= 3
        else:
            score -= min(15.0, (freq_diff / max(tolerance, 1)) * 15.0)
        if not mode_ok:
            score -= 20
        return {
            "kind": "auto",
            "time_diff_seconds": time_diff,
            "freq_diff_hz": freq_diff,
            "mode_compatible": mode_ok,
            "score": round(score, 1),
        }

    def _match(self, a: List[QSO], b: List[QSO]) -> Tuple[List[Tuple[QSO, QSO, Dict[str, Any]]], List[QSO], List[QSO], List[Tuple[QSO, QSO, Dict[str, Any]]]]:
        auto: List[Tuple[Tuple[Any, ...], QSO, QSO, Dict[str, Any]]] = []
        review: List[Tuple[QSO, QSO, Dict[str, Any]]] = []
        missing_time_counts: Dict[Tuple[str, int], int] = defaultdict(int)

        by_key_b: Dict[Tuple[str, str], List[QSO]] = defaultdict(list)
        for q in b:
            by_key_b[(q.call, q.date)].append(q)

        for left in a:
            for right in by_key_b.get((left.call, left.date), []):
                evidence = self._candidate(left, right)
                if not evidence:
                    continue
                if evidence["kind"] == "review":
                    review.append((left, right, evidence))
                    continue
                if left.seconds is None:
                    missing_time_counts[("A", left.index)] += 1
                if right.seconds is None:
                    missing_time_counts[("B", right.index)] += 1
                time_rank = evidence["time_diff_seconds"] if evidence["time_diff_seconds"] is not None else 10_000
                freq_rank = evidence["freq_diff_hz"] if evidence["freq_diff_hz"] is not None else 10_000_000
                mode_rank = 0 if evidence["mode_compatible"] else 1
                auto.append(((time_rank, mode_rank, freq_rank, -evidence["score"]), left, right, evidence))

        used_a, used_b = set(), set()
        matched: List[Tuple[QSO, QSO, Dict[str, Any]]] = []
        for _, left, right, evidence in sorted(auto, key=lambda row: row[0]):
            if left.index in used_a or right.index in used_b:
                continue
            if left.seconds is None and missing_time_counts[("A", left.index)] > 1:
                continue
            if right.seconds is None and missing_time_counts[("B", right.index)] > 1:
                continue
            used_a.add(left.index)
            used_b.add(right.index)
            matched.append((left, right, evidence))

        return (
            matched,
            [q for q in a if q.index not in used_a],
            [q for q in b if q.index not in used_b],
            review,
        )

    def _probable_duplicates(self, rows: List[QSO]) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        used = set()
        for i, q in enumerate(rows):
            if q.index in used:
                continue
            members = [q]
            for other in rows[i + 1:]:
                if other.index in used:
                    continue
                if q.call != other.call or q.date != other.date or q.band != other.band:
                    continue
                if not self._mode_compatible(q, other):
                    continue
                if q.seconds is None or other.seconds is None or abs(q.seconds - other.seconds) > 2:
                    continue
                if q.freq_hz is not None and other.freq_hz is not None and abs(q.freq_hz - other.freq_hz) > self._freq_tolerance(q, other):
                    continue
                if q.rst_sent != other.rst_sent or q.rst_rcvd != other.rst_rcvd:
                    continue
                if (q.grid or "").upper() != (other.grid or "").upper():
                    continue
                members.append(other)
            if len(members) > 1:
                for m in members:
                    used.add(m.index)
                groups.append({"indexes": [m.index for m in members], "records": members})
        return groups

    @staticmethod
    def _duplicate_has_matched_sibling(q: QSO, groups: List[Dict[str, Any]], matched_ids: set) -> bool:
        for group in groups:
            if q.index in group["indexes"]:
                return any(idx in matched_ids for idx in group["indexes"] if idx != q.index)
        return False

    def _missing_item(
        self,
        q: QSO,
        present_source: str,
        absent_source: str,
        absent_coverage: str,
        matched: List[Tuple[QSO, QSO, Dict[str, Any]]],
        review_candidates: List[Tuple[QSO, QSO, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        nearby = []
        for left, right, evidence in matched:
            if left.call == q.call and left.date == q.date and right.call == q.call:
                diff = abs(q.seconds - right.seconds) if q.seconds is not None and right.seconds is not None else None
                if diff is None or diff <= self.REVIEW_TIME_SECONDS:
                    nearby.append({"time": right.time, "time_diff_seconds": diff, "note": "outro registro já recebeu uma correspondência melhor"})
        for left, right, evidence in review_candidates:
            if left.index == q.index:
                nearby.append({"time": right.time, "time_diff_seconds": evidence.get("time_diff_seconds"), "note": "candidato próximo, fora da janela de pareamento automático"})

        full = absent_coverage in {CoverageType.FULL_EXPORT.value, CoverageType.API_FULL_SYNC.value}
        confidence = "HIGH" if full else "INSUFFICIENT_COVERAGE"
        reason = (
            f"Presente em {present_source} e sem correspondência 1:1 em {absent_source}."
            if full else
            f"Sem correspondência em {absent_source}, mas a cobertura informada não permite afirmar ausência."
        )
        if nearby:
            reason += " Há registro próximo da mesma estação; ele foi preservado como evidência e não usado para ocultar este QSO."
        return {
            **self._qso_view(q),
            "present_in": present_source,
            "missing_in": absent_source,
            "confidence": confidence,
            "reason": reason,
            "nearby": nearby[:5],
        }

    @staticmethod
    def _swap_reviews(rows: List[Tuple[QSO, QSO, Dict[str, Any]]]) -> List[Tuple[QSO, QSO, Dict[str, Any]]]:
        return [(right, left, evidence) for left, right, evidence in rows]

    def _duplicate_item(self, group: Dict[str, Any], rows: List[QSO], source: str) -> Dict[str, Any]:
        members: List[QSO] = group["records"]
        base = members[0]
        return {
            "source": source,
            "call": base.call,
            "date": base.date,
            "band": base.band,
            "mode": base.operating_mode or base.mode,
            "records": [self._qso_view(q) for q in members],
            "reason": f"{len(members)} registros praticamente idênticos na mesma fonte, separados por no máximo 2 segundos.",
        }

    def _field_differences(self, a: QSO, b: QSO, source_a: str, source_b: str, evidence: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        important: List[Dict[str, Any]] = []
        soft: List[Dict[str, Any]] = []
        base = {"call": a.call, "date": a.date, "time": a.time, "band": a.band, "source_a": source_a, "source_b": source_b}

        def add(field: str, av: Any, bv: Any, severity: str, reason: str) -> None:
            if av is None or bv is None or str(av).strip().upper() == str(bv).strip().upper():
                return
            item = {**base, "field": field, "value_a": av, "value_b": bv, "severity": severity, "reason": reason}
            (important if severity == "IMPORTANT" else soft).append(item)

        add("RST_SENT", a.rst_sent, b.rst_sent, "IMPORTANT", "Reports transmitidos diferentes")
        add("RST_RCVD", a.rst_rcvd, b.rst_rcvd, "IMPORTANT", "Reports recebidos diferentes")
        add("STATE", a.state, b.state, "IMPORTANT", "Estado diferente entre as fontes")
        add("COUNTY", a.county, b.county, "IMPORTANT", "County diferente entre as fontes")
        add("COUNTRY", a.country, b.country, "IMPORTANT", "País diferente entre as fontes")

        if a.grid and b.grid and a.grid.upper() != b.grid.upper():
            ga, gb = a.grid.upper(), b.grid.upper()
            if ga.startswith(gb) or gb.startswith(ga):
                add("GRID", a.grid, b.grid, "PRECISION", "Mesmo grid-base, com precisão diferente")
            else:
                add("GRID", a.grid, b.grid, "IMPORTANT", "Grid conflitante")

        if a.operating_mode and b.operating_mode and a.operating_mode != b.operating_mode:
            if not self._mode_compatible(a, b):
                add("MODE", a.operating_mode, b.operating_mode, "IMPORTANT", "Modo diferente no mesmo QSO pareado")

        freq_diff = evidence.get("freq_diff_hz")
        if freq_diff and freq_diff > 100:
            soft.append({**base, "field": "FREQ", "value_a": a.freq_hz / 1_000_000 if a.freq_hz else None, "value_b": b.freq_hz / 1_000_000 if b.freq_hz else None, "severity": "TOLERATED", "reason": f"Diferença de {freq_diff} Hz dentro da tolerância de pareamento"})
        time_diff = evidence.get("time_diff_seconds")
        if time_diff and time_diff > 2:
            soft.append({**base, "field": "TIME_ON", "value_a": a.time, "value_b": b.time, "severity": "TOLERATED", "reason": f"Diferença de {time_diff} s dentro da tolerância de 60 s"})
        return important, soft

    @staticmethod
    def _qso_view(q: QSO) -> Dict[str, Any]:
        return {
            "index": q.index,
            "call": q.call,
            "date": q.date,
            "time": q.time,
            "band": q.band,
            "freq_mhz": (round(q.freq_hz / 1_000_000, 6) if q.freq_hz is not None else None),
            "mode": q.operating_mode or q.mode,
            "raw_mode": q.mode,
            "submode": q.submode,
            "rst_sent": q.rst_sent,
            "rst_rcvd": q.rst_rcvd,
            "grid": q.grid,
        }
