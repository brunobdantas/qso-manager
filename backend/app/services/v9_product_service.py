"""Unified product facade for PU2BRU QSO Manager.

Every platform exposes the same product journey. Provider-specific limitations
remain explicit, but online logs, confirmation feeds and manual ADIF sources
all participate in the same logical-QSO workspace.
"""
from __future__ import annotations

import logging
import time

from typing import Any, Dict, Optional

from ..adapters.cloud_logs import CloudProviderError, records_to_adif
from ..adif.parser import ADIFParser
from ..core.version import __version__
from .eqsl_qrz_sync_service import EqslQrzSyncService
from .bootstrap_cache_service import BootstrapCache
from .qso_manager_workspace import QSOManagerWorkspace
from .source_scope_store import SourceScopeStore
from .v8_online_service import V8OnlineService


class V9ProductService(V8OnlineService):
    VERSION = __version__
    LOG_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "HRDLOG", "HRD")
    DISPLAY_ORDER = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD")
    LABELS = {
        **V8OnlineService.LABELS,
        "HRD": "Ham Radio Deluxe",
    }
    NOTES = {
        **V8OnlineService.NOTES,
        "HRD": "Log local via ADIF. No Windows e no Android participa da mesma comparação consolidada.",
    }

    def _normalize_provider(self, provider: str) -> str:
        name = str(provider or "").strip().upper()
        if name not in self.DISPLAY_ORDER:
            raise CloudProviderError(f"Unsupported provider: {provider}")
        return name

    def _configured(self, provider: str) -> bool:
        if provider == "HRD":
            return self.snapshots.summary("HRD").get("downloaded_at") is not None
        return super()._configured(provider)

    def _capabilities(self, provider: str) -> Dict[str, Any]:
        if provider == "HRD":
            return {
                "read": True, "add": False, "update": False, "delete": False,
                "update_fields": [], "write_mode": "local_adif_read_only",
            }
        return super()._capabilities(provider)

    def status(self) -> Dict[str, Any]:
        # super().status() is intentionally reused so hardened provider
        # capability/credential logic stays in one place. LABELS/NOTES above
        # make HRD safe while this subclass changes DISPLAY_ORDER.
        base = super().status()
        rows = []
        scopes = SourceScopeStore(root=self.snapshots.root.parent)
        for row in base.get("providers", []):
            if row.get("provider") == "HRD":
                summary = self.snapshots.summary("HRD")
                row = {
                    **row,
                    "label": self.LABELS["HRD"],
                    "configured": summary.get("downloaded_at") is not None,
                    "credentials": {},
                    "snapshot": summary,
                    "capabilities": self._capabilities("HRD"),
                    "note": self.NOTES["HRD"],
                    "source_kind": "local_adif",
                    "comparison_role": "log",
                }
            provider = row.get("provider")
            comparison_role = row.get("comparison_role")
            scope = scopes.get(provider) if comparison_role == "log" else SourceScopeStore.ACTIVE
            configured = bool(row.get("configured"))
            snapshot_ready = bool((row.get("snapshot") or {}).get("downloaded_at"))
            capabilities = row.get("capabilities") or {}
            row = {
                **row,
                "scope": scope,
                "participates": scope == SourceScopeStore.ACTIVE,
                "read_state": (
                    "OUT_OF_SCOPE" if scope != SourceScopeStore.ACTIVE
                    else "READY" if snapshot_ready
                    else "NOT_LOADED"
                ),
                "write_state": (
                    "UNSUPPORTED" if not any(capabilities.get(k) for k in ("add", "update", "delete"))
                    else "AVAILABLE" if configured
                    else "NOT_CONFIGURED"
                ),
            }
            rows.append(row)
        order = {name: i for i, name in enumerate(self.DISPLAY_ORDER)}
        rows.sort(key=lambda row: order.get(row.get("provider"), 999))
        return {
            **base,
            "version": self.VERSION,
            "product_mode": "unified",
            "mobile_policy": "companion_preview",
            "providers": rows,
            "hrd_local_in_mobile": True,
            "navigation": ["overview", "log", "inbox", "qsl", "sources", "tools"],
            "capability_parity": False,
            "windows_production_ready": True,
            "android_stage": "preview",
        }

    def set_source_scope(self, provider: str, scope: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider not in self.LOG_PROVIDERS:
            raise CloudProviderError("Somente fontes de log participam do escopo de comparação")
        saved = SourceScopeStore(root=self.snapshots.root.parent).set(provider, scope)
        QSOManagerWorkspace.invalidate_cache()
        return {
            "ok": True,
            "provider": provider,
            "scope": saved,
            "participates": saved == SourceScopeStore.ACTIVE,
        }

    def configure(self, provider: str, values: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            raise CloudProviderError("HRD local is configured by importing an ADIF file")
        return super().configure(provider, values)

    def disconnect(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            return self.clear_snapshot("HRD")
        return super().disconnect(provider)

    def test(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            summary = self.snapshots.summary("HRD")
            return {
                "provider": "HRD",
                "ok": summary.get("downloaded_at") is not None,
                "records": summary.get("records", 0),
                "message": "ADIF local carregado." if summary.get("downloaded_at") else "Importe um ADIF do Ham Radio Deluxe.",
            }
        return super().test(provider)

    def sync(self, provider: str, progress=None) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            raise CloudProviderError("HRD local is refreshed by importing a new ADIF export")
        return super().sync(provider, progress=progress)

    def import_local_adif(self, provider: str, content: str, filename: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider not in {"HRD", "HRDLOG", "WRL"}:
            raise CloudProviderError("Manual ADIF is supported for HRD, HRDLOG and full WRL exports")
        if provider == "HRDLOG":
            return self.import_hrdlog_adif(content, filename)
        if not str(content or "").strip():
            raise CloudProviderError("O ADIF está vazio")
        records, errors = ADIFParser().parse(content)
        if not records:
            raise CloudProviderError("Nenhum QSO válido foi encontrado no ADIF")
        if provider == "WRL":
            # Never replace the full local copy with a malformed export.
            if errors:
                raise CloudProviderError("ADIF do WRL com erros: " + "; ".join(errors[:3]))
            if any(not all(record.get(k) for k in ("CALL", "QSO_DATE", "TIME_ON")) for record in records):
                raise CloudProviderError("Exportação WRL incompleta: CALL, QSO_DATE ou TIME_ON ausente")
        backup = self.snapshots.backup(provider)
        summary = self.snapshots.save(provider, records, {
            "source": "manual_wrl_adif" if provider == "WRL" else "manual_adif",
            "coverage": "FULL_EXPORT",
            "filename": (filename or "ham-radio-deluxe.adi")[:255],
            "parse_errors": errors[:20],
        })
        QSOManagerWorkspace.invalidate_cache()
        return {
            "ok": True,
            **summary,
            "backup": str(backup) if backup else None,
            "parse_errors": errors[:20],
        }

    def clear_snapshot(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        result = self.snapshots.clear(provider)
        QSOManagerWorkspace.invalidate_cache()
        return {"ok": True, **result}

    def _eqsl_qrz_service(self) -> EqslQrzSyncService:
        return EqslQrzSyncService(credentials=self.credentials, snapshots=self.snapshots)

    def eqsl_qrz_plan(self, refresh: bool = False) -> Dict[str, Any]:
        """Preview only the strict, auditable eQSL Inbox -> QRZ updates."""
        if refresh:
            if not self._configured("QRZ"):
                raise CloudProviderError("Configure o QRZ antes de analisar eQSL → QRZ")
            if not self._configured("EQSL_INBOX"):
                raise CloudProviderError("Configure o eQSL antes de analisar eQSL → QRZ")
            self.sync("QRZ")
            self.sync("EQSL_INBOX")
        return self._eqsl_qrz_service().plan()

    def eqsl_qrz_apply(self, confirm: bool = False, limit: int = 500) -> Dict[str, Any]:
        """Apply the strict eQSL -> QRZ plan; dry-run unless confirm=True."""
        return self._eqsl_qrz_service().apply(confirm=confirm, limit=limit)

    def export_reference_adif(self) -> Dict[str, Any]:
        records = self.snapshots.load("QRZ").get("records") or []
        if not records:
            raise CloudProviderError("Atualize o QRZ antes de gerar o backup de referência")
        return {
            "provider": "QRZ",
            "records": len(records),
            "content": records_to_adif(records),
            "filename": f"PU2BRU-QRZ-REFERENCIA-v{self.VERSION}.adi",
        }

    def bootstrap(self) -> Dict[str, Any]:
        """Use persistent read-only analysis cache when snapshots are unchanged.

        This prevents full QRZ/LoTW reconciliation on every app relaunch.
        Credential status is never loaded from the cache.
        """
        started = time.monotonic()
        status = self.status()
        cache = BootstrapCache(self.snapshots)
        with cache._lock:
            cached = cache.load()
            if cached is not None:
                logging.getLogger(__name__).info(
                    "bootstrap: disk-cache hit in %.2fs", time.monotonic() - started
                )
                return {"version": self.VERSION, "status": status, **cached}

            signature = cache.signature()
            workspace = self._workspace().options()
            after_workspace = time.monotonic()
            qsl = {
                "ready": None,
                "lazy": True,
                "summary": {"confirmed_qsos": workspace.get("summary", {}).get("confirmed", 0)},
                "proposals": [],
            }
            after_qsl = time.monotonic()
            issues = self.issues(limit=50)
            dashboard_issues = {**issues, "items": issues["items"][:20]}
            dashboard = {
                "version": self.VERSION,
                "summary": workspace.get("summary") or {},
                "issues": dashboard_issues,
                "qsl_summary": qsl.get("summary") or {},
                "sources": status["providers"],
            }
            payload = {
                "dashboard": dashboard,
                "workspace": workspace,
                "qsl": qsl,
                "issues": issues,
            }
            cache.save(payload, signature)
            logging.getLogger(__name__).info(
                "bootstrap: workspace %.2fs, lazy-qsl %.2fs, issues %.2fs, total %.2fs",
                after_workspace-started, after_qsl-after_workspace,
                time.monotonic()-after_qsl, time.monotonic()-started,
            )
            return {"version": self.VERSION, "status": status, **payload}

    def diagnostics(self) -> Dict[str, Any]:
        status = self.status()
        return {
            "version": self.VERSION,
            "workspace": self._workspace().options(),
            "sources": [
                {
                    "provider": row["provider"],
                    "configured": row["configured"],
                    "records": (row.get("snapshot") or {}).get("records", 0),
                    "updated_at": (row.get("snapshot") or {}).get("downloaded_at"),
                    "kind": row.get("source_kind"),
                }
                for row in status["providers"]
            ],
            "capability_parity": False,
            "windows_production_ready": True,
            "android_stage": "preview",
            "navigation": status.get("navigation", []),
        }
