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

    def analysis(self):
        result = super().analysis()
        if not result.get("ready"):
            return result
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

    def update_remote(self, provider: str, index: int, changes: Dict[str, Any], confirm: bool = False):
        normalized = dict(changes)
        if provider.strip().upper() == "WRL" and "FREQ" in normalized:
            try:
                normalized["FREQ"] = float(normalized["FREQ"])
            except (TypeError, ValueError) as exc:
                raise CloudProviderError("WRL frequency must be a number in MHz") from exc
        return super().update_remote(provider, index, normalized, confirm)
