"""Advanced, read-only ADIF and QSL analysis workflows for QSO Manager v7.

The service deliberately does not mutate remote logbooks.  It builds explainable
comparison evidence and QSL correction proposals that can be reviewed/exported
before any manual change is made in a source system.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..adif.parser import ADIFParser
from .fast_adif_comparison_service import FastADIFComparisonService


class AdvancedAnalysisService:
    """Multi-source comparison plus QSL evidence consolidation."""

    QSL_FIELDS = {
        "EQSL": {
            "received": ["EQSL_QSL_RCVD", "EQSL_RCVD"],
            "dates": ["EQSL_QSLRDATE", "EQSL_QSL_DATE", "QSLRDATE"],
            "target_received": "EQSL_QSL_RCVD",
            "target_date": "EQSL_QSLRDATE",
        },
        "LOTW": {
            "received": ["LOTW_QSL_RCVD", "LOTW_RCVD"],
            "dates": ["LOTW_QSLRDATE", "LOTW_QSL_DATE", "QSLRDATE"],
            "target_received": "LOTW_QSL_RCVD",
            "target_date": "LOTW_QSLRDATE",
        },
        "PAPER": {
            "received": ["QSL_RCVD"],
            "dates": ["QSLRDATE"],
            "target_received": "QSL_RCVD",
            "target_date": "QSLRDATE",
        },
        "GENERIC": {
            "received": ["QSL_RCVD", "EQSL_QSL_RCVD", "LOTW_QSL_RCVD"],
            "dates": ["QSLRDATE", "EQSL_QSLRDATE", "LOTW_QSLRDATE"],
            "target_received": "QSL_RCVD",
            "target_date": "QSLRDATE",
        },
    }

    def __init__(self) -> None:
        self.matcher = FastADIFComparisonService()

    @staticmethod
    def _name(source: Dict[str, Any]) -> str:
        return str(source.get("source") or "ADIF").strip().upper()

    @staticmethod
    def _coverage(source: Dict[str, Any]) -> str:
        return str(source.get("coverage") or "PARTIAL_EXPORT").strip().upper()

    def _parse(self, source: Dict[str, Any], side: str) -> Tuple[List[Dict[str, Any]], List[Any], List[str]]:
        records, errors = ADIFParser().parse(str(source.get("content") or ""))
        normalized = self.matcher._normalize(records, side)
        return records, normalized, errors

    @staticmethod
    def _dedupe(items: Iterable[Dict[str, Any]], key_fn) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for item in items:
            key = key_fn(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def compare_sources(self, sources: List[Dict[str, Any]], reference_index: int = 0) -> Dict[str, Any]:
        if len(sources) < 2:
            raise ValueError("Informe ao menos duas fontes ADIF.")
        if reference_index < 0 or reference_index >= len(sources):
            raise ValueError("reference_index fora do intervalo de fontes.")

        names = [self._name(source) for source in sources]
        if len(set(names)) != len(names):
            raise ValueError("Cada fonte precisa ter um nome exclusivo nesta comparação.")

        reference = sources[reference_index]
        reference_name = names[reference_index]
        reference_records, reference_qsos, reference_errors = self._parse(reference, "R")

        source_meta = [{
            "name": reference_name,
            "filename": reference.get("filename") or "reference.adi",
            "coverage": self._coverage(reference),
            "records": len(reference_qsos),
            "parse_errors": reference_errors[:20],
            "reference": True,
        }]
        pair_summaries: List[Dict[str, Any]] = []
        presence: List[Dict[str, Any]] = []
        fields: List[Dict[str, Any]] = []
        tolerated: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        matches: List[Dict[str, Any]] = []
        reviews: List[Dict[str, Any]] = []

        for idx, other in enumerate(sources):
            if idx == reference_index:
                continue
            other_name = names[idx]
            pair_label = f"{reference_name} ↔ {other_name}"
            pair = self.matcher.compare(
                content_a=str(reference.get("content") or ""),
                content_b=str(other.get("content") or ""),
                source_a=reference_name,
                source_b=other_name,
                coverage_a=self._coverage(reference),
                coverage_b=self._coverage(other),
                filename_a=str(reference.get("filename") or "reference.adi"),
                filename_b=str(other.get("filename") or f"{other_name}.adi"),
            )
            pair_summaries.append({"pair": pair_label, "source": other_name, **pair["summary"]})
            source_meta.append({**pair["source_b"], "reference": False})

            for item in pair.get("missing_in_a", []):
                presence.append({**item, "pair": pair_label, "category": "MISSING_IN_REFERENCE"})
            for item in pair.get("missing_in_b", []):
                presence.append({**item, "pair": pair_label, "category": "MISSING_IN_SOURCE"})
            for item in pair.get("field_differences", []):
                fields.append({**item, "pair": pair_label, "compared_source": other_name})
            for item in pair.get("tolerated_differences", []):
                tolerated.append({**item, "pair": pair_label, "compared_source": other_name})
            for item in pair.get("probable_duplicates", []):
                duplicates.append({**item, "pair": pair_label})

            _, other_qsos, other_errors = self._parse(other, f"S{idx}")
            matched, _, _, review_candidates = self.matcher._match(reference_qsos, other_qsos)
            for left, right, evidence in matched:
                matches.append({
                    "pair": pair_label,
                    "reference_source": reference_name,
                    "compared_source": other_name,
                    "reference": self.matcher._qso_view(left),
                    "compared": self.matcher._qso_view(right),
                    "evidence": evidence,
                    "classification": "MATCHED",
                    "reason": self._match_reason(evidence),
                })
            for left, right, evidence in review_candidates:
                reviews.append({
                    "pair": pair_label,
                    "reference_source": reference_name,
                    "compared_source": other_name,
                    "reference": self.matcher._qso_view(left),
                    "compared": self.matcher._qso_view(right),
                    "evidence": evidence,
                    "classification": "REVIEW",
                    "reason": "Mesmo indicativo/data, porém fora da janela de pareamento automático; revisar manualmente.",
                })
            if other_errors:
                source_meta[-1]["parse_errors"] = other_errors[:20]

        duplicates = self._dedupe(
            duplicates,
            lambda d: (
                d.get("source"), d.get("call"), d.get("date"), d.get("band"), d.get("mode"),
                tuple(record.get("index") for record in d.get("records", [])),
            ),
        )

        return {
            "reference_source": reference_name,
            "sources": source_meta,
            "pair_summaries": pair_summaries,
            "summary": {
                "source_count": len(sources),
                "reference_records": len(reference_qsos),
                "matched_pairs": len(matches),
                "presence_differences": len(presence),
                "missing_in_reference": sum(1 for x in presence if x["category"] == "MISSING_IN_REFERENCE"),
                "missing_in_sources": sum(1 for x in presence if x["category"] == "MISSING_IN_SOURCE"),
                "field_differences": len(fields),
                "tolerated_differences": len(tolerated),
                "probable_duplicates": len(duplicates),
                "review_candidates": len(reviews),
            },
            "presence_differences": presence,
            "field_differences": fields,
            "tolerated_differences": tolerated,
            "probable_duplicates": duplicates,
            "matches": matches,
            "review_candidates": reviews,
            "reference_parse_errors": reference_errors[:20],
        }

    @staticmethod
    def _match_reason(evidence: Dict[str, Any]) -> str:
        bits = []
        if evidence.get("time_diff_seconds") is not None:
            bits.append(f"Δtempo {evidence['time_diff_seconds']} s")
        if evidence.get("freq_diff_hz") is not None:
            bits.append(f"Δfreq {evidence['freq_diff_hz']} Hz")
        if evidence.get("score") is not None:
            bits.append(f"score {evidence['score']}")
        if evidence.get("mode_compatible") is False:
            bits.append("modo divergente em match apertado")
        return ", ".join(bits) if bits else "Pareamento por indicativo, data e campos disponíveis."

    @staticmethod
    def _is_yes(value: Any) -> bool:
        return str(value or "").strip().upper() in {"Y", "YES", "TRUE", "1", "C"}

    @staticmethod
    def _normalize_date(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        compact = text.replace("-", "").replace("/", "")
        if len(compact) == 8 and compact.isdigit():
            return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        return text

    def _qsl_config(self, kind: str) -> Dict[str, Any]:
        return self.QSL_FIELDS.get(kind, self.QSL_FIELDS["GENERIC"])

    def _current_confirmation(self, raw: Dict[str, Any], kind: str) -> Tuple[bool, Optional[str]]:
        config = self._qsl_config(kind)
        received = any(self._is_yes(raw.get(field)) for field in config["received"])
        date = None
        for field in config["dates"]:
            date = self._normalize_date(raw.get(field))
            if date:
                break
        return received, date

    def _evidence_date(self, raw: Dict[str, Any], kind: str) -> Optional[str]:
        config = self._qsl_config(kind)
        for field in config["dates"]:
            value = self._normalize_date(raw.get(field))
            if value:
                return value
        # Deliberately never substitute QSO_DATE: contact date is not proof of QSL receipt date.
        return None

    def analyze_qsl(self, reference: Dict[str, Any], evidence_sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not evidence_sources:
            raise ValueError("Informe ao menos uma fonte de evidência QSL.")

        reference_name = self._name(reference)
        reference_records, reference_qsos, reference_errors = self._parse(reference, "QRZ")
        if not reference_qsos:
            raise ValueError("A referência não contém QSOs válidos para análise.")

        groups: Dict[Tuple[int, str], Dict[str, Any]] = {}
        unmatched: List[Dict[str, Any]] = []
        reviews: List[Dict[str, Any]] = []
        source_meta: List[Dict[str, Any]] = []

        for idx, source in enumerate(evidence_sources):
            source_name = self._name(source)
            kind = str(source.get("kind") or source_name or "GENERIC").strip().upper()
            if kind not in self.QSL_FIELDS:
                kind = "GENERIC"
            assume_received = bool(source.get("assume_received", True))
            records, qsos, errors = self._parse(source, f"E{idx}")
            source_meta.append({
                "name": source_name,
                "kind": kind,
                "filename": source.get("filename") or f"{source_name}.adi",
                "records": len(qsos),
                "parse_errors": errors[:20],
                "assume_received": assume_received,
            })

            matched, _, unmatched_evidence, review_candidates = self.matcher._match(reference_qsos, qsos)
            config = self._qsl_config(kind)
            for left, right, evidence in matched:
                evidence_raw = right.raw
                if not assume_received and not any(self._is_yes(evidence_raw.get(field)) for field in config["received"]):
                    continue
                key = (left.index, kind)
                entry = groups.setdefault(key, {
                    "reference_index": left.index,
                    "kind": kind,
                    "qso": self.matcher._qso_view(left),
                    "reference_raw": left.raw,
                    "evidence_sources": set(),
                    "evidence_indexes": [],
                    "evidence_dates": set(),
                    "matches": [],
                })
                entry["evidence_sources"].add(source_name)
                entry["evidence_indexes"].append(right.index)
                date = self._evidence_date(evidence_raw, kind)
                if date:
                    entry["evidence_dates"].add(date)
                entry["matches"].append({
                    "source": source_name,
                    "index": right.index,
                    "date": date,
                    "evidence": evidence,
                    "reason": self._match_reason(evidence),
                })

            for qso in unmatched_evidence:
                unmatched.append({
                    **self.matcher._qso_view(qso),
                    "source": source_name,
                    "kind": kind,
                    "reason": f"Evidência presente em {source_name}, mas sem correspondência segura na referência {reference_name}.",
                })
            for left, right, evidence in review_candidates:
                reviews.append({
                    "source": source_name,
                    "kind": kind,
                    "reference": self.matcher._qso_view(left),
                    "evidence_qso": self.matcher._qso_view(right),
                    "evidence": evidence,
                    "reason": "Candidato próximo de confirmação, mas o intervalo de horário exige revisão manual.",
                })

        proposals: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        matrix: List[Dict[str, Any]] = []
        missing_explicit_date = 0

        by_reference: Dict[int, Dict[str, Any]] = defaultdict(dict)
        for (_, kind), entry in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            raw = entry["reference_raw"]
            config = self._qsl_config(kind)
            current_received, current_date = self._current_confirmation(raw, kind)
            dates = sorted(entry["evidence_dates"])
            evidence_date = dates[0] if len(dates) == 1 else None
            changes: Dict[str, Any] = {}

            if not current_received:
                changes[config["target_received"]] = "Y"
            if evidence_date and not current_date:
                changes[config["target_date"]] = evidence_date
            elif evidence_date and current_date and evidence_date != current_date:
                conflicts.append({
                    "qso": entry["qso"],
                    "service": kind,
                    "field": config["target_date"],
                    "current_value": current_date,
                    "evidence_value": evidence_date,
                    "sources": sorted(entry["evidence_sources"]),
                    "reason": "A referência já possui uma data diferente; não sobrescrever automaticamente.",
                })
            elif len(dates) > 1:
                conflicts.append({
                    "qso": entry["qso"],
                    "service": kind,
                    "field": config["target_date"],
                    "current_value": current_date,
                    "evidence_value": dates,
                    "sources": sorted(entry["evidence_sources"]),
                    "reason": "As evidências trazem datas de confirmação diferentes; revisar antes de preencher.",
                })
            elif not dates and not current_date:
                missing_explicit_date += 1

            reason = (
                f"Confirmação {kind} comprovada por presença em {', '.join(sorted(entry['evidence_sources']))}."
                + (f" Data explícita: {evidence_date}." if evidence_date else " A fonte não trouxe data explícita de recebimento; QSO_DATE não será usado como substituto.")
            )
            proposal = {
                "qso": entry["qso"],
                "service": kind,
                "sources": sorted(entry["evidence_sources"]),
                "current_received": current_received,
                "current_date": current_date,
                "evidence_date": evidence_date,
                "evidence_dates": dates,
                "changes": changes,
                "received_field": config["target_received"],
                "date_field": config["target_date"],
                "reason": reason,
                "matches": entry["matches"],
                "actionable": bool(changes),
            }
            if changes:
                proposals.append(proposal)
            by_reference[entry["reference_index"]][kind] = proposal

        for ref_index, services in sorted(by_reference.items()):
            ref_qso = reference_qsos[ref_index]
            native = {}
            for kind in ("PAPER", "EQSL", "LOTW"):
                received, date = self._current_confirmation(ref_qso.raw, kind)
                native[kind] = {"received": received, "date": date}
            matrix.append({
                "qso": self.matcher._qso_view(ref_qso),
                "reference_confirmations": native,
                "evidence": services,
            })

        return {
            "reference": {
                "name": reference_name,
                "filename": reference.get("filename") or "reference.adi",
                "records": len(reference_qsos),
                "parse_errors": reference_errors[:20],
            },
            "evidence_sources": source_meta,
            "summary": {
                "reference_records": len(reference_qsos),
                "evidence_sources": len(evidence_sources),
                "matched_confirmation_groups": len(groups),
                "actionable_proposals": len(proposals),
                "unmatched_evidence": len(unmatched),
                "review_candidates": len(reviews),
                "date_conflicts": len(conflicts),
                "missing_explicit_confirmation_date": missing_explicit_date,
            },
            "proposals": proposals,
            "confirmation_matrix": matrix,
            "unmatched_evidence": unmatched,
            "review_candidates": reviews,
            "conflicts": conflicts,
            "policy": {
                "reference_is_mutated": False,
                "qso_date_used_as_qsl_date": False,
                "existing_dates_overwritten": False,
                "note": "O resultado é uma proposta auditável. Datas existentes conflitantes são preservadas para revisão manual.",
            },
        }
