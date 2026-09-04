"""Connected QSO hub: snapshots, QRZ-first analysis and safe remote actions."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adapters.cloud_logs import PROVIDERS, CloudProviderError, adapter_for, records_to_adif
from .adif_comparison_service import ADIFComparisonService
from .cloud_snapshot_store import CloudSnapshotStore
from .credential_store import CredentialStore


class CloudHubService:
    PROVIDER_ORDER = ("QRZ", "WRL", "CLUBLOG", "EQSL")
    PROVIDER_LABELS = {"QRZ": "QRZ", "WRL": "World Radio League", "CLUBLOG": "Club Log", "EQSL": "eQSL"}
    PROVIDER_NOTES = {
        "QRZ": "Base preferencial. Leitura completa e inclusão segura; edição/exclusão remota ficam bloqueadas para proteger confirmações.",
        "WRL": "API oficial de leitura e escrita. Contatos possuem ID estável e podem ser incluídos, corrigidos e excluídos.",
        "CLUBLOG": "Download do log, inclusão em tempo real e exclusão por identidade exata. O export é minimalista e pode descartar campos do log original.",
        "EQSL": "OutBox em ADIF e inclusão por interface de logger. O download é uma representação normalizada; edição/exclusão remota não é exposta.",
    }

    def __init__(self, credentials: Optional[CredentialStore] = None, snapshots: Optional[CloudSnapshotStore] = None) -> None:
        self.credentials = credentials or CredentialStore()
        self.snapshots = snapshots or CloudSnapshotStore()
        self.comparator = ADIFComparisonService()

    def status(self) -> Dict[str, Any]:
        providers = []
        for provider in self.PROVIDER_ORDER:
            cred = self.credentials.get(provider)
            adapter_cls = PROVIDERS[provider]
            providers.append({
                "provider": provider,
                "label": self.PROVIDER_LABELS[provider],
                "configured": bool(cred),
                "credentials": self.credentials.masked(cred),
                "capabilities": dict(adapter_cls.capabilities),
                "snapshot": self.snapshots.summary(provider),
                "note": self.PROVIDER_NOTES[provider],
                "truth_priority": 1 if provider == "QRZ" else 2,
            })
        return {
            "truth_source": "QRZ",
            "truth_policy": "QRZ é a fonte preferencial, mas ausência no QRZ não é tratada como prova automática: fontes independentes e snapshots recentes podem indicar que o QRZ está desatualizado.",
            "providers": providers,
        }

    def configure(self, provider: str, values: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._provider(provider)
        clean = {k: v.strip() if isinstance(v, str) else v for k, v in values.items() if v not in (None, "")}
        existing = self.credentials.get(provider)
        secret_fields = {"api_key", "password", "app_password", "key"}
        for field in secret_fields:
            if field not in clean and field in existing:
                clean[field] = existing[field]
            elif isinstance(clean.get(field), str) and clean[field].startswith("••••") and field in existing:
                clean[field] = existing[field]
        merged = {**existing, **clean}
        self.credentials.set(provider, merged)
        return next(p for p in self.status()["providers"] if p["provider"] == provider)

    def disconnect(self, provider: str) -> Dict[str, Any]:
        provider = self._provider(provider)
        self.credentials.delete(provider)
        return {"ok": True, "provider": provider}

    def test(self, provider: str) -> Dict[str, Any]:
        provider = self._provider(provider)
        with adapter_for(provider, self._credentials(provider)) as adapter:
            result = adapter.test_connection()
        return {"provider": provider, **result}

    def sync(self, provider: str) -> Dict[str, Any]:
        provider = self._provider(provider)
        with adapter_for(provider, self._credentials(provider)) as adapter:
            result = adapter.fetch_all()
        records = result.get("records") or []
        metadata = result.get("metadata") or {}
        metadata.update({"source": "remote_api", "coverage": metadata.get("coverage") or "API_FULL_SYNC"})
        summary = self.snapshots.save(provider, records, metadata)
        return {"ok": True, **summary}

    def sync_all(self) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        for provider in self.PROVIDER_ORDER:
            if not self.credentials.configured(provider):
                results.append({"provider": provider, "ok": False, "skipped": True, "error": "not configured"})
                continue
            try:
                results.append(self.sync(provider))
            except Exception as exc:
                results.append({"provider": provider, "ok": False, "error": str(exc)})
        return {"results": results, "analysis": self.analysis() if self.snapshots.summary("QRZ")["records"] else None}

    def analysis(self) -> Dict[str, Any]:
        qrz = self.snapshots.load("QRZ")
        qrz_records = qrz.get("records") or []
        if not qrz_records:
            return {
                "ready": False,
                "reason": "Sincronize o QRZ primeiro. Ele é a base preferencial da análise.",
                "summary": {"qrz_records": 0, "qrz_stale_candidates": 0, "missing_elsewhere": 0, "field_differences": 0, "probable_duplicates": 0},
                "pairwise": {}, "qrz_stale_candidates": [], "missing_elsewhere": [], "field_differences": [], "probable_duplicates": [],
            }

        qrz_adif = records_to_adif(qrz_records)
        pairwise: Dict[str, Any] = {}
        stale_groups: Dict[tuple, Dict[str, Any]] = {}
        missing_elsewhere: List[Dict[str, Any]] = []
        fields: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []

        for provider in self.PROVIDER_ORDER:
            if provider == "QRZ":
                continue
            snapshot = self.snapshots.load(provider)
            rows = snapshot.get("records") or []
            if not rows:
                continue
            comparison = self.comparator.compare(
                qrz_adif, records_to_adif(rows), "QRZ", provider,
                "API_FULL_SYNC", "API_FULL_SYNC", "qrz snapshot", f"{provider.lower()} snapshot",
            )
            pairwise[provider] = comparison

            for item in comparison.get("missing_in_a", []):
                key = self._evidence_key(item)
                group = stale_groups.setdefault(key, {
                    **item, "sources": [], "source_indexes": {}, "evidence_count": 0, "assessment": "QRZ_MAY_BE_STALE",
                })
                if provider not in group["sources"]:
                    group["sources"].append(provider)
                    group["source_indexes"][provider] = item.get("index")
                    group["evidence_count"] = len(group["sources"])

            for item in comparison.get("missing_in_b", []):
                missing_elsewhere.append({**item, "target": provider, "qrz_index": item.get("index"), "assessment": "TARGET_MAY_BE_STALE"})

            for item in comparison.get("field_differences", []):
                fields.append({**item, "provider": provider, "preferred_source": "QRZ"})

            for item in comparison.get("probable_duplicates", []):
                if item.get("source") == provider:
                    duplicates.append(item)

        stale_candidates = []
        for group in stale_groups.values():
            count = group.get("evidence_count", 0)
            group["assessment"] = "QRZ_LIKELY_STALE" if count >= 2 else "QRZ_MAY_BE_STALE"
            group["confidence"] = "HIGH" if count >= 2 else "REVIEW"
            group["reason"] = (
                f"Ausente no QRZ e corroborado por {count} fontes independentes: {', '.join(group['sources'])}."
                if count >= 2 else
                f"Ausente no QRZ, mas presente em {group['sources'][0]}. Revisar antes de adicionar à base preferencial."
            )
            stale_candidates.append(group)

        stale_candidates.sort(key=lambda x: (x.get("date") or "", x.get("time") or ""), reverse=True)
        missing_elsewhere.sort(key=lambda x: (x.get("date") or "", x.get("time") or ""), reverse=True)
        fields.sort(key=lambda x: (x.get("date") or "", x.get("time") or ""), reverse=True)

        return {
            "ready": True,
            "truth_source": "QRZ",
            "truth_note": "QRZ orienta o valor canônico, mas o sistema destaca evidências de desatualização em vez de apagar divergências automaticamente.",
            "snapshot_freshness": {p: self.snapshots.summary(p) for p in self.PROVIDER_ORDER},
            "summary": {
                "qrz_records": len(qrz_records),
                "qrz_stale_candidates": len(stale_candidates),
                "qrz_likely_stale": sum(1 for x in stale_candidates if x["assessment"] == "QRZ_LIKELY_STALE"),
                "missing_elsewhere": len(missing_elsewhere),
                "field_differences": len(fields),
                "probable_duplicates": len(duplicates),
            },
            "qrz_stale_candidates": stale_candidates,
            "missing_elsewhere": missing_elsewhere,
            "field_differences": fields,
            "probable_duplicates": duplicates,
            "pairwise": pairwise,
        }

    def search(self, call: str = "", limit: int = 200) -> Dict[str, Any]:
        call = call.strip().upper()
        rows: List[Dict[str, Any]] = []
        for provider in self.PROVIDER_ORDER:
            snapshot = self.snapshots.load(provider)
            for index, record in enumerate(snapshot.get("records") or []):
                rec_call = str(record.get("CALL") or "").upper()
                if call and call not in rec_call:
                    continue
                rows.append({"provider": provider, "index": index, "external_id": self._external_id(provider, record), "record": record})
                if len(rows) >= max(1, min(limit, 2000)):
                    return {"items": rows, "truncated": True}
        return {"items": rows, "truncated": False}

    def record(self, provider: str, index: int) -> Dict[str, Any]:
        provider = self._provider(provider)
        rows = self.snapshots.load(provider).get("records") or []
        if index < 0 or index >= len(rows):
            raise LookupError(f"{provider} snapshot record not found")
        row = rows[index]
        return {"provider": provider, "index": index, "external_id": self._external_id(provider, row), "record": row}

    def publish(self, source: str, index: int, target: str, confirm: bool = False) -> Dict[str, Any]:
        source = self._provider(source)
        target = self._provider(target)
        if source == target:
            raise CloudProviderError("Source and target must be different")
        if not confirm:
            return {"dry_run": True, "source": source, "target": target, "qso": self.record(source, index), "capabilities": PROVIDERS[target].capabilities}
        if not PROVIDERS[target].capabilities.get("add"):
            raise CloudProviderError(f"{target} does not support add")
        row = self.record(source, index)["record"]
        backup = self.snapshots.backup(target)
        with adapter_for(target, self._credentials(target)) as adapter:
            result = adapter.add_qso(row)
            verification = None
            if target == "QRZ" and result.get("external_id") and hasattr(adapter, "fetch_logids"):
                verification = adapter.fetch_logids([str(result["external_id"])])
                if not verification.get("verified"):
                    raise CloudProviderError("QRZ insert returned success but exact re-FETCH verification failed")
        return {"ok": True, "source": source, "target": target, "backup": str(backup) if backup else None, "result": result, "verification": verification, "needs_resync": target != "QRZ"}

    def update_remote(self, provider: str, index: int, changes: Dict[str, Any], confirm: bool = False) -> Dict[str, Any]:
        provider = self._provider(provider)
        item = self.record(provider, index)
        if not PROVIDERS[provider].capabilities.get("update"):
            raise CloudProviderError(f"{provider} remote update is intentionally unavailable")
        if not confirm:
            return {"dry_run": True, "provider": provider, "qso": item, "changes": changes}
        external_id = item.get("external_id")
        if not external_id:
            raise CloudProviderError(f"{provider} record has no stable external id")
        backup = self.snapshots.backup(provider)
        with adapter_for(provider, self._credentials(provider)) as adapter:
            result = adapter.update_qso(external_id, changes)
        return {"ok": True, "backup": str(backup) if backup else None, "result": result, "needs_resync": True}

    def delete_remote(self, provider: str, index: int, confirm: bool = False) -> Dict[str, Any]:
        provider = self._provider(provider)
        item = self.record(provider, index)
        if not PROVIDERS[provider].capabilities.get("delete"):
            raise CloudProviderError(f"{provider} remote delete is intentionally unavailable")
        if not confirm:
            return {"dry_run": True, "provider": provider, "qso": item}
        backup = self.snapshots.backup(provider)
        with adapter_for(provider, self._credentials(provider)) as adapter:
            result = adapter.delete_qso(item.get("external_id") or "", record=item["record"])
        return {"ok": True, "backup": str(backup) if backup else None, "result": result, "needs_resync": True}

    @staticmethod
    def _evidence_key(item: Dict[str, Any]) -> tuple:
        time = str(item.get("time") or "")
        return (str(item.get("call") or "").upper(), item.get("date"), time[:5], str(item.get("band") or "").upper(), str(item.get("mode") or "").upper())

    @staticmethod
    def _external_id(provider: str, record: Dict[str, Any]) -> Optional[str]:
        keys = {"QRZ": ("APP_QRZLOG_LOGID", "QSO_ID"), "WRL": ("APP_WRL_ID",), "CLUBLOG": ("APP_CLUBLOG_QSO_ID",), "EQSL": ("APP_EQSL_ID",)}.get(provider, ())
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    def _credentials(self, provider: str) -> Dict[str, Any]:
        value = self.credentials.get(provider)
        if not value:
            raise CloudProviderError(f"{provider} is not configured")
        return value

    @classmethod
    def _provider(cls, provider: str) -> str:
        name = provider.strip().upper()
        if name not in cls.PROVIDER_ORDER:
            raise CloudProviderError(f"Unsupported provider: {provider}")
        return name
