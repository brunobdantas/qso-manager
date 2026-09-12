"""Single production provider registry.

Keeping adapter selection in one module prevents behavior from changing based on
Python import order. Both desktop services and v9 APIs resolve providers here.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type

import httpx

from .cloud_logs import (
    CloudLogAdapter,
    CloudProviderError,
    QRZCloudAdapter,
    WRLCloudAdapter,
    ClubLogCloudAdapter,
    EQSLCloudAdapter,
)
from .qrz_cloud_v501 import QRZCloudAdapterV501
from .eqsl_cloud_v510 import EQSLCloudAdapterV510
from .online_v8 import HRDLogCloudAdapter, LoTWConfirmationAdapter, EQSLInboxAdapter


PROVIDER_ADAPTERS: Dict[str, Type[CloudLogAdapter]] = {
    "QRZ": QRZCloudAdapterV501,
    "WRL": WRLCloudAdapter,
    "CLUBLOG": ClubLogCloudAdapter,
    "EQSL": EQSLCloudAdapterV510,
    "HRDLOG": HRDLogCloudAdapter,
    "LOTW": LoTWConfirmationAdapter,
    "EQSL_INBOX": EQSLInboxAdapter,
}


def capabilities_for(provider: str) -> Dict[str, bool]:
    name = str(provider or "").strip().upper()
    cls = PROVIDER_ADAPTERS.get(name)
    if cls is None:
        if name == "HRD":
            return {"read": True, "add": False, "update": False, "delete": False}
        raise CloudProviderError(f"Unsupported provider: {provider}")
    return dict(cls.capabilities)


def adapter_for_provider(
    provider: str,
    credentials: Dict[str, Any],
    client: Optional[httpx.Client] = None,
) -> CloudLogAdapter:
    name = str(provider or "").strip().upper()
    cls = PROVIDER_ADAPTERS.get(name)
    if cls is None:
        raise CloudProviderError(f"Unsupported provider: {provider}")
    return cls(credentials, client=client)
