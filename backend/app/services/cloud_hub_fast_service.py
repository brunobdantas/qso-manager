"""Performance wrapper for connected multi-log analysis."""
from __future__ import annotations

from typing import Optional

from .cloud_hub_service import CloudHubService as BaseCloudHubService
from .cloud_snapshot_store import CloudSnapshotStore
from .credential_store import CredentialStore
from .fast_adif_comparison_service import FastADIFComparisonService


class CloudHubService(BaseCloudHubService):
    def __init__(self, credentials: Optional[CredentialStore] = None, snapshots: Optional[CloudSnapshotStore] = None) -> None:
        super().__init__(credentials=credentials, snapshots=snapshots)
        self.comparator = FastADIFComparisonService()
