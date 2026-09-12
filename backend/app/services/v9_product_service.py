"""Unified product facade for QSO Manager v9.

v9 makes one workspace the product surface on every platform.  Online logbooks,
confirmation feeds and manual ADIF sources all participate in the same logical
QSO model.  The older v5-v8 APIs remain available for compatibility, but the
v9 UI consumes this facade.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adapters.cloud_logs import CloudProviderError
from ..adif.parser import ADIFParser
from .qso_manager_workspace import QSOManagerWorkspace
from .v8_online_service import V8OnlineService


class V9ProductService(V8OnlineService):
    VERSION = "9.0.0"
    LOG_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "EQSL", "HRDLOG", "HRD")
    DISPLAY_ORDER = ("QRZ", "WRL", "CLUBLOG", "EQSL", "EQSL_INBOX", "LOTW", "HRDLOG", "HRD")

    def _normalize_provider(self, provider: str) -> str:
        name = str(provider or "").strip().upper()
        if name not in self.DISPLAY_ORDER:
            raise CloudProviderError(f"Unsupported v9 provider: {provider}")
        return name

    def _configured(self, provider: str) -> bool:
        if provider == "HRD":
            return self.snapshots.summary("HRD").get("downloaded_at") is not None
        return super()._configured(provider)

    def _capabilities(self, provider: str) -> Dict[str, bool]:
        if provider == "HRD":
            return {"read": True, "add": False, "update": False, "delete": False}
        return super()._capabilities(provider)

    def status(self) -> Dict[str, Any]:
        base = super().status()
        rows = [row for row in base.get("providers", []) if row.get("provider") != "HRD"]
        hrd_summary = self.snapshots.summary("HRD")
        rows.append({
            "provider": "HRD",
            "label": "Ham Radio Deluxe",
            "configured": hrd_summary.get("downloaded_at") is not None,
            "credentials": {},
            "snapshot": hrd_summary,
            "capabilities": self._capabilities("HRD"),
            "note": "Log local via ADIF. No Windows pode representar o export do HRD; no Android o mesmo arquivo pode ser importado e comparado.",
            "source_kind": "local_adif",
            "comparison_role": "log",
        })
        order = {name: i for i, name in enumerate(self.DISPLAY_ORDER)}
        rows.sort(key=lambda row: order.get(row.get("provider"), 999))
        return {
            **base,
            "version": self.VERSION,
            "product_mode": "unified",
            "mobile_policy": "feature_parity",
            "providers": rows,
            "hrd_local_in_mobile": True,
            "navigation": ["overview", "log", "inbox", "qsl", "sources", "tools"],
            "capability_parity": True,
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

    def sync(self, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider == "HRD":
            raise CloudProviderError("HRD local is refreshed by importing a new ADIF export")
        return super().sync(provider)

    def import_local_adif(self, provider: str, content: str, filename: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)
        if provider not in {"HRD", "HRDLOG"}:
            raise CloudProviderError("Manual ADIF bootstrap is supported for HRD and HRDLOG")
        if provider == "HRDLOG":
            return self.import_hrdlog_adif(content, filename)
        if not str(content or "").strip():
            raise CloudProviderError("O ADIF está vazio")
        records, errors = ADIFParser().parse(content)
        if not records:
            raise CloudProviderError("Nenhum QSO válido foi encontrado no ADIF")
        backup = self.snapshots.backup(provider)
        summary = self.snapshots.save(provider, records, {
            "source": "manual_adif",
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
        before = self.snapshots.summary(provider)
        self.snapshots.clear(provider)
        QSOManagerWorkspace.invalidate_cache()
        return {"ok": True, "provider": provider, "records_removed": int(before.get("records") or 0)}

    def bootstrap(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "status": self.status(),
            "dashboard": self.dashboard(),
            "workspace": self._workspace().options(),
            "qsl": self.qsl_analysis(),
            "issues": self.issues(limit=50),
        }

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
            "capability_parity": True,
        }
