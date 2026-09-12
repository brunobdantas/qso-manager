"""QSO Manager v8 online cockpit service.

This layer keeps the v7 desktop intact while exposing the online-only model used
by the new mobile experience.  HRD local is intentionally excluded here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adapters.cloud_logs import PROVIDERS, CloudProviderError, records_to_adif
from ..adapters.online_v8 import EQSLInboxAdapter, HRDLogCloudAdapter, LoTWConfirmationAdapter
from ..adif.parser import ADIFParser
from .advanced_analysis_service import AdvancedAnalysisService
from .cloud_hub_fast_service import CloudHubService
from .cloud_snapshot_store import CloudSnapshotStore
from .credential_store import CredentialStore
from .fast_adif_comparison_service import FastADIFComparisonService
from .qso_manager_workspace import QSOManagerWorkspace

# Shared registry: this lets the existing workspace understand HRDLog presence
# without pretending that HRDLog exposes a full-log read API.
PROVIDERS["HRDLOG"] = HRDLogCloudAdapter


class V8OnlineService:
    LOG_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "HRDLOG", "HRD")
    SYNC_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW")
    DISPLAY_ORDER = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD")

    LABELS = {
        "QRZ": "QRZ",
        "WRL": "World Radio League",
        "CLUBLOG": "Club Log",
        "EQSL": "eQSL OutBox",
        "EQSL_INBOX": "eQSL Inbox",
        "LOTW": "LoTW",
        "HRDLOG": "HRDLog.net",
        "HRD": "Ham Radio Deluxe",
    }

    NOTES = {
        "QRZ": "Logbook online completo; referência preferencial de consolidação.",
        "WRL": "Logbook online completo via Developer API.",
        "CLUBLOG": "Log online completo; download e publicação pelos endpoints do Club Log.",
        "EQSL": "OutBox online: QSOs enviados ao eQSL.",
        "EQSL_INBOX": "Inbox online: evidências de eQSLs recebidos.",
        "LOTW": "Confirmações recebidas consultadas online no relatório oficial LoTW.",
        "HRDLOG": "Bootstrap por ADIF + inserções online. Alterações feitas diretamente no site exigem nova reconciliação ADIF.",
        "HRD": "Fonte local por ADIF. Pode ser importada e comparada igualmente no Windows e no Android.",
    }

    def __init__(
        self,
        credentials: Optional[CredentialStore] = None,
        snapshots: Optional[CloudSnapshotStore] = None,
    ) -> None:
        self.credentials = credentials or CredentialStore()
        self.snapshots = snapshots or CloudSnapshotStore()
        self.hub = CloudHubService(credentials=self.credentials, snapshots=self.snapshots)
        self.matcher = FastADIFComparisonService()
        self.advanced = AdvancedAnalysisService()

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        name = str(provider or "").strip().upper()
        if name not in V8OnlineService.DISPLAY_ORDER:
            raise CloudProviderError(f"Unsupported v8 provider: {provider}")
        return name

    def _credentials_for(self, provider: str) -> Dict[str, Any]:
        if provider == "EQSL_INBOX":
            return self.credentials.get("EQSL")
        if provider == "HRD":
            return {}
        return self.credentials.get(provider)

    def _configured(self, provider: str) -> bool:
        if provider == "EQSL_INBOX":
            return self.credentials.configured("EQSL")
        if provider == "HRD":
            return bool(self.snapshots.summary("HRD").get("records"))
        return self.credentials.configured(provider)

    def _capabilities(self, provider: str) -> Dict[str, bool]:
        if provider == "LOTW":
            return dict(LoTWConfirmationAdapter.capabilities)
        if provider == "EQSL_INBOX":
            return dict(EQSLInboxAdapter.capabilities)
        if provider == "HRDLOG":
            return dict(HRDLogCloudAdapter.capabilities)
        if provider == "HRD":
            return {"read": True, "add": False, "update": False, "delete": False}
        adapter = PROVIDERS.get(provider)
        return dict(adapter.capabilities) if adapter else {"read": False, "add": False, "update": False, "delete": False}

    def status(self) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for provider in self.DISPLAY_ORDER:
            credential_provider = "EQSL" if provider == "EQSL_INBOX" else provider
            creds = self.credentials.get(credential_provider)
            snapshot = self.snapshots.summary(provider)
            configured = self._configured(provider)
            rows.append({
                "provider": provider,
                "label": self.LABELS[provider],
                "configured": configured,
                "credentials": self.credentials.masked(creds),
                "snapshot": snapshot,
                "capabilities": self._capabilities(provider),
                "note": self.NOTES[provider],
                "source_kind": (
                    "hybrid_bootstrap_upload" if provider == "HRDLOG"
                    else "local_adif" if provider == "HRD"
                    else "confirmation_api" if provider in {"EQSL_INBOX", "LOTW"}
                    else "remote_api"
                ),
                "comparison_role": "qsl_evidence" if provider in {"EQSL_INBOX", "LOTW"} else "log",
            })
        return {
            "version": "8.0.0",
            "mobile_policy": "online_only",
            "truth_source": "QRZ",
            "providers": rows,
            "hrd_local_in_mobile": False,
            "hrdlog_policy": {
                "full_read_api": False,
                "bootstrap": "ADIF",
                "online_update": "realtime insert",
                "direct_site_changes_detected": False,
            },
        }

    def configure(self, provider: str, values: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            raise CloudProviderError("HRD é uma fonte ADIF local e não usa credenciais")
        if provider == "EQSL_INBOX":
            provider = "EQSL"
        clean = {k: v.strip() if isinstance(v, str) else v for k, v in values.items() if v not in (None, "")}
        existing = self.credentials.get(provider)
        secret_fields = {"api_key", "password", "app_password", "key", "upload_code", "code"}
        for field in secret_fields:
            if field not in clean and field in existing:
                clean[field] = existing[field]
            elif isinstance(clean.get(field), str) and clean[field].startswith("••••") and field in existing:
                clean[field] = existing[field]
        self.credentials.set(provider, {**existing, **clean})
        return next(row for row in self.status()["providers"] if row["provider"] == provider)

    def disconnect(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            self.snapshots.clear("HRD")
            QSOManagerWorkspace.invalidate_cache()
            return {"ok": True, "provider": "HRD"}
        target = "EQSL" if provider == "EQSL_INBOX" else provider
        self.credentials.delete(target)
        return {"ok": True, "provider": target}

    def _adapter(self, provider: str):
        if provider == "HRD":
            raise CloudProviderError("HRD é uma fonte ADIF local; importe um arquivo em vez de sincronizar")
        creds = self._credentials_for(provider)
        if not creds:
            raise CloudProviderError(f"{self.LABELS[provider]} is not configured")
        if provider == "LOTW":
            return LoTWConfirmationAdapter(creds)
        if provider == "EQSL_INBOX":
            return EQSLInboxAdapter(creds)
        if provider == "HRDLOG":
            return HRDLogCloudAdapter(creds)
        from ..adapters.cloud_logs import adapter_for
        return adapter_for(provider, creds)

    def test(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        with self._adapter(provider) as adapter:
            result = adapter.test_connection()
        return {"provider": provider, **result}

    def sync(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            raise CloudProviderError("HRD é uma fonte ADIF local; importe um arquivo em vez de sincronizar")
        if provider == "HRDLOG":
            raise CloudProviderError("HRDLog uses ADIF bootstrap + realtime inserts; it has no supported full-log read sync")
        with self._adapter(provider) as adapter:
            result = adapter.fetch_all()
        metadata = dict(result.get("metadata") or {})
        metadata.setdefault("coverage", "API_FULL_SYNC")
        metadata.setdefault("source", "remote_api")
        summary = self.snapshots.save(provider, result.get("records") or [], metadata)
        QSOManagerWorkspace.invalidate_cache()
        return {"ok": True, **summary}

    def sync_all(self) -> Dict[str, Any]:
        results = []
        for provider in self.SYNC_PROVIDERS:
            if not self._configured(provider):
                results.append({"provider": provider, "ok": False, "skipped": True, "error": "not configured"})
                continue
            try:
                results.append(self.sync(provider))
            except Exception as exc:
                results.append({"provider": provider, "ok": False, "error": str(exc)})
        return {"results": results, "dashboard": self.dashboard()}

    def import_source_adif(self, provider: str, content: str, filename: str = "source.adi") -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider not in {"HRD", "HRDLOG"}:
            raise CloudProviderError(f"{provider} deve ser atualizado por sua conexão online")
        if not str(content or "").strip():
            raise CloudProviderError("O ADIF está vazio")
        records, errors = ADIFParser().parse(content)
        if not records:
            raise CloudProviderError("Nenhum QSO válido foi encontrado no ADIF")
        backup = self.snapshots.backup(provider)
        metadata = {
            "source": "hrdlog_bootstrap_adif" if provider == "HRDLOG" else "local_adif",
            "coverage": "FULL_EXPORT",
            "filename": (filename or "source.adi")[:255],
            "parse_errors": errors[:20],
            "managed_after_bootstrap": provider == "HRDLOG",
        }
        summary = self.snapshots.save(provider, records, metadata)
        QSOManagerWorkspace.invalidate_cache()
        return {
            "ok": True,
            **summary,
            "backup": str(backup) if backup else None,
            "parse_errors": errors[:20],
        }

    def import_hrdlog_adif(self, content: str, filename: str = "hrdlog.adi") -> Dict[str, Any]:
        return self.import_source_adif("HRDLOG", content, filename)

    def hrdlog_plan(self, limit: int = 5000) -> Dict[str, Any]:
        qrz_records = self.snapshots.load("QRZ").get("records") or []
        hrd_records = self.snapshots.load("HRDLOG").get("records") or []
        if not qrz_records:
            raise CloudProviderError("Sincronize o QRZ antes de calcular atualizações do HRDLog")
        if self.snapshots.summary("HRDLOG").get("downloaded_at") is None:
            raise CloudProviderError("Importe primeiro um ADIF completo do HRDLog para criar a base de comparação")

        qrz_norm = self.matcher._normalize(qrz_records, "QRZ")
        hrd_norm = self.matcher._normalize(hrd_records, "HRDLOG")
        matched, unmatched_qrz, _unmatched_hrd, review = self.matcher._match(qrz_norm, hrd_norm)
        review_indexes = {left.index for left, _right, _evidence in review}
        duplicate_indexes = {
            index
            for group in self.matcher._probable_duplicates(qrz_norm)
            for index in (group.get("indexes") or [])
        }
        safe = [
            q for q in unmatched_qrz
            if q.index not in review_indexes and q.index not in duplicate_indexes
        ]
        blocked = [q for q in unmatched_qrz if q.index in review_indexes or q.index in duplicate_indexes]
        limit = max(1, min(int(limit), 5000))
        return {
            "qrz_records": len(qrz_records),
            "known_hrdlog_records": len(hrd_records),
            "matched": len(matched),
            "safe_missing": len(safe),
            "blocked_for_review": len(blocked),
            "candidates": [
                {**self.matcher._qso_view(q), "qrz_index": q.index}
                for q in safe[:limit]
            ],
            "truncated": len(safe) > limit,
            "policy": "Somente ausências de alta confiança; candidatos próximos e duplicidades não são enviados automaticamente.",
        }

    def push_hrdlog_missing(self, confirm: bool = False, limit: int = 500) -> Dict[str, Any]:
        plan = self.hrdlog_plan(limit=limit)
        if not confirm:
            return {"dry_run": True, **plan}
        if not self.credentials.configured("HRDLOG"):
            raise CloudProviderError("Configure Callsign + Upload Code do HRDLog antes do envio")

        qrz_records = self.snapshots.load("QRZ").get("records") or []
        known = list(self.snapshots.load("HRDLOG").get("records") or [])
        sent = []
        errors = []
        with HRDLogCloudAdapter(self.credentials.get("HRDLOG")) as adapter:
            for candidate in plan["candidates"]:
                index = int(candidate["qrz_index"])
                if index < 0 or index >= len(qrz_records):
                    continue
                record = dict(qrz_records[index])
                try:
                    result = adapter.add_qso(record)
                    record["APP_QSOMANAGER_HRDLOG_STATUS"] = result.get("status")
                    known.append(record)
                    sent.append({
                        "qrz_index": index,
                        "call": record.get("CALL"),
                        "status": result.get("status"),
                    })
                except Exception as exc:
                    errors.append({"qrz_index": index, "call": record.get("CALL"), "error": str(exc)})

        if sent:
            old = self.snapshots.load("HRDLOG").get("metadata") or {}
            metadata = {
                **old,
                "source": "hrdlog_bootstrap_plus_online",
                "coverage": "FULL_EXPORT",
                "managed_after_bootstrap": True,
                "online_managed_records": int(old.get("online_managed_records") or 0) + len(sent),
            }
            self.snapshots.save("HRDLOG", known, metadata)
            QSOManagerWorkspace.invalidate_cache()

        return {
            "ok": not errors,
            "attempted": len(plan["candidates"]),
            "sent_or_already_remote": len(sent),
            "errors": errors,
            "items": sent,
            "remaining_hint": max(0, int(plan["safe_missing"]) - len(sent)),
        }

    def _workspace(self) -> QSOManagerWorkspace:
        # The workspace shares our snapshot root/credentials.
        return QSOManagerWorkspace(hub=self.hub)

    def qsl_analysis(self) -> Dict[str, Any]:
        qrz = self.snapshots.load("QRZ").get("records") or []
        if not qrz:
            return {
                "ready": False,
                "summary": {"actionable_proposals": 0, "matched_confirmation_groups": 0, "unmatched_evidence": 0},
                "proposals": [],
                "confirmation_matrix": [],
                "conflicts": [],
                "unmatched_evidence": [],
            }
        evidence = []
        eqsl = self.snapshots.load("EQSL_INBOX").get("records") or []
        lotw = self.snapshots.load("LOTW").get("records") or []
        if eqsl:
            evidence.append({
                "source": "EQSL_INBOX",
                "content": records_to_adif(eqsl),
                "coverage": "API_FULL_SYNC",
                "kind": "EQSL",
                "assume_received": True,
            })
        if lotw:
            evidence.append({
                "source": "LOTW",
                "content": records_to_adif(lotw),
                "coverage": "API_FULL_SYNC",
                "kind": "LOTW",
                "assume_received": True,
            })
        if not evidence:
            return {
                "ready": False,
                "summary": {"actionable_proposals": 0, "matched_confirmation_groups": 0, "unmatched_evidence": 0},
                "proposals": [],
                "confirmation_matrix": [],
                "conflicts": [],
                "unmatched_evidence": [],
            }
        result = self.advanced.analyze_qsl({
            "source": "QRZ",
            "content": records_to_adif(qrz),
            "coverage": "API_FULL_SYNC",
        }, evidence)
        result["ready"] = True
        return result

    def issues(self, limit: int = 100) -> Dict[str, Any]:
        rows, _ = self._workspace()._cached()
        configured_logs = {
            p for p in self.LOG_PROVIDERS
            if self.snapshots.summary(p).get("downloaded_at") is not None
        }
        issues = []
        for row in rows:
            missing = [p for p in row.get("missing_in", []) if p in configured_logs]
            if missing:
                issues.append({
                    "type": "MISSING",
                    "severity": "warning",
                    "logical_id": row["logical_id"],
                    "call": row["call"],
                    "date": row["date"],
                    "time": row["time"],
                    "band": row["band"],
                    "mode": row["mode"],
                    "message": "Ausente em " + ", ".join(missing),
                    "sources": row.get("providers", []),
                    "missing_in": missing,
                })
            if row.get("difference_count"):
                issues.append({
                    "type": "DIFFERENCE",
                    "severity": "review",
                    "logical_id": row["logical_id"],
                    "call": row["call"],
                    "date": row["date"],
                    "time": row["time"],
                    "band": row["band"],
                    "mode": row["mode"],
                    "message": "Campos divergentes: " + ", ".join(row.get("difference_fields") or []),
                    "sources": row.get("providers", []),
                })
            if row.get("duplicate"):
                issues.append({
                    "type": "DUPLICATE",
                    "severity": "review",
                    "logical_id": row["logical_id"],
                    "call": row["call"],
                    "date": row["date"],
                    "time": row["time"],
                    "band": row["band"],
                    "mode": row["mode"],
                    "message": "Duplicidade provável",
                    "sources": row.get("providers", []),
                })
        qsl = self.qsl_analysis()
        for proposal in qsl.get("proposals") or []:
            q = proposal.get("qso") or {}
            issues.append({
                "type": "QSL",
                "severity": "info",
                "call": q.get("call"),
                "date": q.get("date"),
                "time": q.get("time"),
                "band": q.get("band"),
                "mode": q.get("mode"),
                "message": f"Confirmação {proposal.get('service')} encontrada",
                "sources": proposal.get("sources") or [],
            })
        limit = max(1, min(int(limit), 1000))
        return {
            "total": len(issues),
            "counts": {
                "missing": sum(1 for x in issues if x["type"] == "MISSING"),
                "differences": sum(1 for x in issues if x["type"] == "DIFFERENCE"),
                "duplicates": sum(1 for x in issues if x["type"] == "DUPLICATE"),
                "qsl": sum(1 for x in issues if x["type"] == "QSL"),
            },
            "items": issues[:limit],
            "truncated": len(issues) > limit,
        }

    def dashboard(self) -> Dict[str, Any]:
        workspace = self._workspace().options()
        issues = self.issues(limit=20)
        qsl = self.qsl_analysis()
        return {
            "version": "8.0.0",
            "summary": workspace.get("summary") or {},
            "issues": issues,
            "qsl_summary": qsl.get("summary") or {},
            "sources": self.status()["providers"],
        }

    def log(self, **filters: Any) -> Dict[str, Any]:
        return self._workspace().query(**filters)
