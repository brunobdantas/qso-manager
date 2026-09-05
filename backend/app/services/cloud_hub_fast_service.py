"""Performance wrapper for connected multi-log analysis."""
from __future__ import annotations

from typing import Dict, Any, Optional

from ..adapters.cloud_logs import CloudProviderError, PROVIDERS
from ..adapters.eqsl_cloud_v510 import EQSLCloudAdapterV510
from ..adapters.qrz_cloud_v501 import QRZCloudAdapterV501
from .cloud_hub_service import CloudHubService as BaseCloudHubService
from .cloud_snapshot_store import CloudSnapshotStore
from .credential_store import CredentialStore
from .fast_adif_comparison_service import FastADIFComparisonService

# Keep the shared provider registry used by the base service, replacing only
# adapters that need hardened production behavior observed against real logs.
PROVIDERS["QRZ"] = QRZCloudAdapterV501
PROVIDERS["EQSL"] = EQSLCloudAdapterV510


class CloudHubService(BaseCloudHubService):
    def __init__(self, credentials: Optional[CredentialStore] = None, snapshots: Optional[CloudSnapshotStore] = None) -> None:
        super().__init__(credentials=credentials, snapshots=snapshots)
        self.comparator = FastADIFComparisonService()

    def _legacy_eqsl_snapshot(self) -> bool:
        summary = self.snapshots.summary("EQSL")
        metadata = summary.get("metadata") or {}
        return bool(summary.get("records")) and bool(metadata.get("normalized_export")) and not metadata.get("download_strategy")

    @staticmethod
    def _reassess_stale_group(group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sources = list(group.get("sources") or [])
        if not sources:
            return None
        count = len(sources)
        group["evidence_count"] = count
        group["assessment"] = "QRZ_LIKELY_STALE" if count >= 2 else "QRZ_MAY_BE_STALE"
        group["confidence"] = "HIGH" if count >= 2 else "REVIEW"
        group["reason"] = (
            f"Ausente no QRZ e corroborado por {count} fontes independentes: {', '.join(sources)}."
            if count >= 2 else
            f"Ausente no QRZ, mas presente em {sources[0]}. Revisar antes de adicionar à base preferencial."
        )
        return group

    def analysis(self):
        result = super().analysis()
        if not result.get("ready"):
            return result

        if self._legacy_eqsl_snapshot():
            result.get("pairwise", {}).pop("EQSL", None)

            cleaned_stale = []
            for original in result.get("qrz_stale_candidates") or []:
                group = dict(original)
                group["sources"] = [s for s in (group.get("sources") or []) if s != "EQSL"]
                indexes = dict(group.get("source_indexes") or {})
                indexes.pop("EQSL", None)
                group["source_indexes"] = indexes
                reassessed = self._reassess_stale_group(group)
                if reassessed:
                    cleaned_stale.append(reassessed)

            result["qrz_stale_candidates"] = cleaned_stale
            result["missing_elsewhere"] = [x for x in (result.get("missing_elsewhere") or []) if x.get("target") != "EQSL"]
            result["field_differences"] = [x for x in (result.get("field_differences") or []) if x.get("provider") != "EQSL"]
            result["probable_duplicates"] = [x for x in (result.get("probable_duplicates") or []) if x.get("source") != "EQSL"]
            result["ignored_sources"] = sorted(set((result.get("ignored_sources") or []) + ["EQSL"]))
            result["source_warnings"] = {
                **(result.get("source_warnings") or {}),
                "EQSL": "Snapshot legado do eQSL ignorado até uma nova sincronização validada do arquivo ADIF do OutBox.",
            }

            summary = result.get("summary") or {}
            summary["qrz_stale_candidates"] = len(result["qrz_stale_candidates"])
            summary["qrz_likely_stale"] = sum(1 for x in result["qrz_stale_candidates"] if x.get("assessment") == "QRZ_LIKELY_STALE")
            summary["missing_elsewhere"] = len(result["missing_elsewhere"])
            summary["field_differences"] = len(result["field_differences"])
            summary["probable_duplicates"] = len(result["probable_duplicates"])
            result["summary"] = summary

        existing = result.get("probable_duplicates") or []
        seen = {
            (d.get("source"), d.get("call"), d.get("date"), d.get("band"), tuple(r.get("time") for r in d.get("records") or []))
            for d in existing
        }
        for comparison in (result.get("pairwise") or {}).values():
            for duplicate in comparison.get("probable_duplicates", []):
                if duplicate.get("source") != "QRZ":
                    continue
                key = (
                    duplicate.get("source"), duplicate.get("call"), duplicate.get("date"), duplicate.get("band"),
                    tuple(r.get("time") for r in duplicate.get("records") or []),
                )
                if key not in seen:
                    existing.append(duplicate)
                    seen.add(key)
        result["probable_duplicates"] = existing
        result["summary"]["probable_duplicates"] = len(existing)
        return result

    def clear_snapshot(self, provider: str) -> Dict[str, Any]:
        provider = self._provider(provider)
        return {"ok": True, **self.snapshots.clear(provider)}

    def update_remote(self, provider: str, index: int, changes: Dict[str, Any], confirm: bool = False):
        normalized = dict(changes)
        if provider.strip().upper() == "WRL" and "FREQ" in normalized:
            try:
                normalized["FREQ"] = float(normalized["FREQ"])
            except (TypeError, ValueError) as exc:
                raise CloudProviderError("WRL frequency must be a number in MHz") from exc
        return super().update_remote(provider, index, normalized, confirm)
