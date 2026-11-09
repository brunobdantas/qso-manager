"""QRZ-led logbook integrity, decisions, QSL opportunities and safe monitoring.

The engine reads local snapshots only; it never mutates a remote logbook.
All writes go through the existing, previewed bulk action coordinator.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.runtime import user_data_root
from .qso_manager_workspace import QSOManagerWorkspace

PROVIDERS = ("WRL", "CLUBLOG", "EQSL", "HRDLOG")
FULL_COVERAGE = {"API_FULL_SYNC", "FULL_EXPORT"}
COMPARE_FIELDS = ("RST_SENT", "RST_RCVD", "GRIDSQUARE", "STATE", "CNTY", "COUNTRY", "NAME", "QTH", "COMMENT")
DECISIONS = {"KEEP_SEPARATE", "CONFIRMED_DUPLICATE", "ACCEPT_EXCEPTION", "NEEDS_REVIEW", "RESOLVED"}
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(*items: Any) -> str:
    payload = json.dumps(items, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _fingerprint(row: dict) -> str:
    # Independent of snapshot array indexes; durable across reimports.
    raw = row.get("canonical_record") or {}
    return _hash(row.get("call"), row.get("date"),
                 str(row.get("time") or "").replace(":", "")[:6],
                 row.get("band"), row.get("mode"), raw.get("STATION_CALLSIGN"))


def _normalize(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def _failure_type(error: str) -> str:
    lower = str(error).lower()
    if "429" in lower or "rate limit" in lower or "too many" in lower:
        return "RATE_LIMIT"
    if any(x in lower for x in ("401", "403", "unauthorized", "credential", "login", "password", "authentication")):
        return "AUTH"
    if any(x in lower for x in ("unsupported", "not support", "404", "method not allowed")):
        return "UNSUPPORTED"
    if any(x in lower for x in ("409", "duplicate", "already exists", "conflict")):
        return "CONFLICT"
    if any(x in lower for x in ("timeout", "503", "502", "504", "connection", "network")):
        return "TRANSIENT"
    return "OTHER"


class IntegrityStore:
    """Durable local decision log and provider error ledger (SQLite/WAL)."""

    def __init__(self, root: Optional[Path] = None):
        folder = Path(root or user_data_root()) / "integrity"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "integrity.db"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS decisions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_key TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_case ON decisions(case_key,provider,id);
                CREATE TABLE IF NOT EXISTS provider_errors(
                    provider TEXT PRIMARY KEY, classification TEXT NOT NULL,
                    message TEXT NOT NULL, failures INTEGER NOT NULL,
                    active INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scans(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature TEXT NOT NULL, summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def decisions(self) -> Dict[tuple, dict]:
        with _LOCK, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM decisions ORDER BY id ASC"
            ).fetchall()
        return {(r["case_key"], r["provider"]): dict(r) for r in rows}

    def decide(self, case_key: str, provider: str, decision: str, reason: str, evidence: Optional[dict] = None) -> dict:
        provider, decision = provider.upper(), decision.upper()
        if decision not in DECISIONS:
            raise ValueError("Decisão inválida")
        if len(reason.strip()) < 5:
            raise ValueError("Informe uma justificativa com ao menos 5 caracteres")
        if not 8 <= len(case_key) <= 128 or provider not in (*PROVIDERS, "QRZ", "LOTW", "EQSL_INBOX", "HRD"):
            raise ValueError("Caso ou provedor inválido")
        with _LOCK, self._connect() as db:
            cur = db.execute(
                "INSERT INTO decisions(case_key,provider,decision,reason,evidence,created_at) VALUES(?,?,?,?,?,?)",
                (case_key, provider, decision, reason.strip()[:4000],
                 json.dumps(evidence or {}, ensure_ascii=False, default=str)[:10000], _now()),
            )
            db.commit()
        return {"id": cur.lastrowid, "case_key": case_key, "provider": provider, "decision": decision}

    def history(self, limit: int = 100) -> list[dict]:
        with _LOCK, self._connect() as db:
            rows = db.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (min(max(1, limit), 1000),)).fetchall()
        return [dict(row) for row in rows]

    def revision(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COALESCE(MAX(id),0) FROM decisions").fetchone()[0])

    def provider_result(self, provider: str, error: Optional[str]) -> None:
        provider = provider.upper()
        if provider not in (*PROVIDERS, "QRZ", "LOTW", "EQSL_INBOX"):
            return
        with _LOCK, self._connect() as db:
            if error:
                previous = db.execute(
                    "SELECT failures FROM provider_errors WHERE provider=?", (provider,)
                ).fetchone()
                db.execute(
                    "INSERT INTO provider_errors VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(provider) DO UPDATE SET classification=excluded.classification,"
                    "message=excluded.message,failures=excluded.failures,active=1,updated_at=excluded.updated_at",
                    (provider, _failure_type(error), str(error)[:2000],
                     (int(previous[0]) if previous else 0) + 1, 1, _now()),
                )
            else:
                db.execute("UPDATE provider_errors SET active=0,updated_at=? WHERE provider=?", (_now(), provider))
            db.commit()

    def errors(self) -> Dict[str, dict]:
        with self._connect() as db:
            return {r["provider"]: dict(r) for r in db.execute("SELECT * FROM provider_errors")}

    def scan(self, signature: str, summary: dict) -> None:
        with _LOCK, self._connect() as db:
            previous = db.execute("SELECT signature FROM scans ORDER BY id DESC LIMIT 1").fetchone()
            if previous and previous[0] == signature:
                return
            db.execute("INSERT INTO scans(signature,summary,created_at) VALUES(?,?,?)",
                       (signature, json.dumps(summary, ensure_ascii=False), _now()))
            db.execute("DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY id DESC LIMIT 100)")
            db.commit()

    def scans(self, limit: int = 15) -> list[dict]:
        with self._connect() as db:
            return [
                {"created_at": r["created_at"], "summary": json.loads(r["summary"]), "signature": r["signature"]}
                for r in db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (min(limit, 100),))
            ]

    def setting(self, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with _LOCK, self._connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))
            db.commit()


class IntegrityService:
    """Explainable per-provider comparisons. No remote writes."""

    _cache_guard = threading.RLock()
    _analysis_cache: Dict[str, tuple[str, dict]] = {}

    def __init__(self, workspace: Optional[QSOManagerWorkspace] = None, store: Optional[IntegrityStore] = None):
        self.workspace = workspace or QSOManagerWorkspace()
        self.store = store or IntegrityStore()

    def signature(self) -> str:
        # File signatures change after a snapshot update, even for identical counts.
        parts = []
        for provider in ("QRZ", *PROVIDERS, "HRD", "LOTW", "EQSL_INBOX"):
            path = self.workspace.hub.snapshots._path(provider)
            try:
                stat = path.stat()
                parts.append((provider, stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                parts.append((provider, None, None))
        return _hash(parts)

    def _case(self, kind: str, provider: str, row: dict, *, reason: str, confidence: str = "REVIEW",
              field: str = "", before: Any = None, after: Any = None, actionable: bool = False) -> dict:
        identity = _fingerprint(row)
        key = _hash(kind, provider, identity, field, row.get("source_records", {}).get(provider, {}).get("external_id"))
        return {
            "case_key": key, "kind": kind, "provider": provider,
            "logical_id": row.get("logical_id"), "fingerprint": identity,
            "call": row.get("call"), "date": row.get("date"), "time": row.get("time"),
            "band": row.get("band"), "mode": row.get("mode"), "country": row.get("country"),
            "dxcc": (row.get("canonical_record") or {}).get("DXCC"),
            "reason": reason, "confidence": confidence, "field": field,
            "reference_value": before, "provider_value": after,
            "actionable": bool(actionable),
        }

    def _analyze(self) -> dict:
        rows, _ = self.workspace._cached()
        summaries = {p: self.workspace.hub.snapshots.summary(p) for p in ("QRZ", *PROVIDERS)}
        full = {p for p in PROVIDERS if
                summaries[p].get("downloaded_at") is not None and
                (summaries[p].get("metadata") or {}).get("coverage") in FULL_COVERAGE}
        caps = {p: self.workspace._capabilities(p) for p in PROVIDERS}
        errors = self.store.errors()
        decisions = self.store.decisions()
        counters = {p: {"records": summaries[p].get("records") or 0,
                        "matched": 0, "missing": 0, "extra": 0,
                        "different": 0, "duplicates": 0, "blocked": 0,
                        "loaded": p in full, "coverage": (summaries[p].get("metadata") or {}).get("coverage"),
                        "last_update": summaries[p].get("downloaded_at")} for p in PROVIDERS}
        cases = []
        for row in rows:
            refs = row["refs"]
            has_qrz = "QRZ" in refs
            if has_qrz:
                qrz = row["source_records"]["QRZ"]["record"]
                for provider in full:
                    if provider not in refs:
                        counters[provider]["missing"] += 1
                        can_add = bool(caps[provider].get("add"))
                        can_add = can_add and not row["duplicate"] and not (errors.get(provider, {}).get("active") and errors[provider]["classification"] in {"AUTH", "UNSUPPORTED"})
                        case = self._case("MISSING", provider, row, reason="QSO do QRZ ausente neste snapshot completo",
                                          confidence="HIGH" if can_add else "REVIEW", actionable=can_add)
                        cases.append(case)
                    else:
                        counters[provider]["matched"] += 1
                        target = row["source_records"][provider]["record"]
                        differences = []
                        for field in COMPARE_FIELDS:
                            qv, pv = _normalize(qrz.get(field)), _normalize(target.get(field))
                            if qv and pv and qv != pv:
                                differences.append((field, qv, pv))
                        if differences:
                            counters[provider]["different"] += 1
                            for field, original, current in differences:
                                cases.append(self._case(
                                    "DIFFERENCE", provider, row, reason="Divergência verificada entre QRZ e a fonte",
                                    field=field, before=original, after=current))
            else:
                for provider in refs:
                    if provider in full:
                        counters[provider]["extra"] += 1
                        cases.append(self._case(
                            "EXTRA", provider, row,
                            reason="Registro presente no provedor sem pareamento seguro no QRZ; conferir antes de alterar"))
        # Identify duplicate pairs within each provider. Different bands, modes and
        # distinct nearby QSOs are not merged by the established comparator.
        for provider in full:
            snapshot = self.workspace.hub.snapshots.load(provider)
            norm = self.workspace.comparator._normalize(snapshot.get("records") or [], provider)
            groups = self.workspace.comparator._probable_duplicates(norm)
            for group in groups:
                members = group.get("records") or []
                if len(members) < 2:
                    continue
                counters[provider]["duplicates"] += len(members) - 1
                first = members[0]
                raw = first.raw
                other_ids = [
                    str(self.workspace.hub._external_id(provider, q.raw) or q.index)
                    for q in members
                ]
                sample = {
                    "call": first.call, "date": first.date, "time": first.time,
                    "band": first.band, "mode": first.operating_mode,
                    "country": raw.get("COUNTRY"), "canonical_record": raw,
                    "logical_id": None, "source_records": {provider: {"external_id": "|".join(other_ids)}},
                }
                case = self._case(
                    "DUPLICATE", provider, sample,
                    reason="Possível repetição: mesmo indicativo, banda, modo e instante (até 2 s),"
                           " com frequência/RST/grid compatíveis. Revisão manual obrigatória.")
                case["member_ids"] = other_ids
                case["confidence"] = "REVIEW"
                cases.append(case)

        by_kind = defaultdict(int)
        for case in cases:
            choice = decisions.get((case["case_key"], case["provider"]))
            if choice:
                case["decision"] = choice["decision"]
                case["decision_reason"] = choice["reason"]
                if choice["decision"] in ("ACCEPT_EXCEPTION", "KEEP_SEPARATE", "RESOLVED"):
                    case["actionable"] = False
                    counters[case["provider"]]["blocked"] += 1
            by_kind[case["kind"]] += 1

        for provider, metrics in counters.items():
            err = errors.get(provider, {})
            metrics["exception"] = err if err.get("active") else None
            if not metrics["loaded"]:
                metrics["state"] = "NO_COMPLETE_SNAPSHOT"
            elif err.get("active"):
                metrics["state"] = "PROVIDER_ERROR"
            elif all(metrics[x] == 0 for x in ("missing", "extra", "different", "duplicates")):
                metrics["state"] = "ALIGNED_WITH_QRZ"
            else:
                metrics["state"] = "DIVERGENT"

        summary = {"reference": "QRZ",
                   "reference_records": summaries["QRZ"].get("records") or 0,
                   "cases": len(cases), "by_kind": dict(by_kind),
                   "providers": counters,
                   "note": "Ausências/excedentes baseados em snapshots completos, não em contagens líquidas. Candidatos ambíguos exigem revisão."}
        return {"signature": self.signature(), "summary": summary, "cases": cases}

    def _cached_analysis(self) -> dict:
        signature = self.signature()
        key = str(self.store.path.resolve())
        with self._cache_guard:
            cached = self._analysis_cache.get(key)
            if cached is not None and cached[0] == (signature, self.store.revision()):
                return cached[1]
            analysis = self._analyze()
            self.store.scan(signature, analysis["summary"])
            self._analysis_cache[key] = ((signature, self.store.revision()), analysis)
            return analysis

    def report(self, page: int = 1, page_size: int = 50, provider: str = "",
               kind: str = "", q: str = "") -> dict:
        analysis = self._cached_analysis()
        provider, kind, q = provider.upper(), kind.upper(), q.upper().strip()
        cases = [x for x in analysis["cases"]
                 if (not provider or x["provider"] == provider)
                 and (not kind or x["kind"] == kind)
                 and (not q or q in str(x.get("call") or "").upper())]
        offset = (max(1, page) - 1) * max(1, page_size)
        return {"signature": analysis["signature"], "summary": analysis["summary"],
                "total": len(cases), "page": page, "page_size": page_size,
                "items": cases[offset:offset+page_size]}

    def reconcile_plan(self, provider: str, limit: int = 100) -> dict:
        provider = provider.upper()
        if provider not in PROVIDERS:
            raise ValueError("Provedor inválido")
        report = self._cached_analysis()
        state = report["summary"]["providers"][provider]
        candidates = [
            x for x in report["cases"] if x["provider"] == provider and
            x["kind"] == "MISSING" and x["actionable"]
        ]
        # No silent delete/overwrite. All proposals are QRZ -> provider inserts.
        selected = candidates[:min(max(limit, 1), 1000)]
        ids = list(dict.fromkeys(c["logical_id"] for c in selected))
        return {
            "source": "QRZ", "target": provider, "action": "PUBLISH",
            "signature": report["signature"], "coverage": state["coverage"],
            "total_candidates": len(candidates), "selected": len(ids),
            "logical_ids": ids, "sample": selected[:20],
            "blocked": state["blocked"],
            "ready": bool(state["loaded"] and self.workspace._capabilities(provider).get("add")),
            "policy": "Prévia obrigatória; somente inclusões de alta confiança, sem exclusões ou mudanças automáticas",
        }

    def qsl_opportunities(self, limit: int = 100) -> dict:
        snapshots = self.workspace.hub.snapshots
        qr = snapshots.load("QRZ").get("records") or []
        if not qr:
            return {"ready": False, "summary": {}, "items": []}
        comparator = self.workspace.comparator
        normalized = comparator._normalize(qr, "QRZ")
        matched_by = defaultdict(set)
        for provider in ("LOTW", "EQSL_INBOX"):
            evidence = snapshots.load(provider).get("records") or []
            if not evidence:
                continue
            external = comparator._normalize(evidence, provider)
            matches, _, _, _ = comparator._match(normalized, external)
            for ref, candidate, _ in matches:
                record = candidate.raw
                if provider == "EQSL_INBOX" or any(
                    _normalize(record.get(key)) in ("Y", "V", "YES", "CONFIRMED")
                    for key in ("LOTW_QSL_RCVD", "QSL_RCVD")
                ):
                    matched_by[ref.index].add(provider)
        confirmed_entities = set()
        confirmed_combos = set()
        rows = []
        for q in normalized:
            record = qr[q.index]
            dxcc = str(record.get("DXCC") or "").strip()
            is_confirmed = any(_normalize(record.get(key)) in ("Y", "V", "YES")
                               for key in ("QSL_RCVD", "LOTW_QSL_RCVD", "EQSL_QSL_RCVD"))
            is_confirmed = is_confirmed or bool(matched_by.get(q.index))
            if is_confirmed and dxcc.isdigit() and int(dxcc) > 0:
                confirmed_entities.add(dxcc)
                confirmed_combos.add((dxcc, q.band, q.operating_mode))
            rows.append((q, record, dxcc, is_confirmed))
        candidates = []
        for q, record, dxcc, confirmed in rows:
            if confirmed or not dxcc.isdigit() or int(dxcc) <= 0:
                continue
            new_dxcc = dxcc not in confirmed_entities
            new_combo = (dxcc, q.band, q.operating_mode) not in confirmed_combos
            priority = (100 if new_dxcc else 0) + (30 if new_combo else 0)
            if not priority:
                continue
            candidates.append({
                "call": q.call, "date": q.date, "time": q.time,
                "band": q.band, "mode": q.operating_mode, "dxcc": dxcc,
                "country": record.get("COUNTRY"), "priority": priority,
                "new_dxcc": new_dxcc, "new_band_mode": new_combo,
                "confirmation": "PENDING",
                "reason": "DXCC ainda não confirmado" if new_dxcc else "Combinação DXCC/banda/modo ainda não confirmada",
            })
        candidates.sort(key=lambda x: (-x["priority"], x["dxcc"], x["call"], x["date"]))
        return {"ready": True,
                "summary": {"confirmed_dxcc": len(confirmed_entities),
                            "pending_dxcc": len({x["dxcc"] for x in candidates if x["new_dxcc"]}),
                            "priority_qsos": len(candidates),
                            "note": "Prioridade por cobertura potencial; não garante QSL ou crédito de award."},
                "items": candidates[:min(max(limit, 1), 1000)]}
