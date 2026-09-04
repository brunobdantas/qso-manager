"""QRZ cloud adapter hotfix for real-world Logbook API validation.

Release 5.0.1 keeps the Release 5 safety model intact while making QRZ
connection failures actionable. The QRZ Logbook API can return a bare
``RESULT=FAIL`` without a REASON (notably for an invalid/unauthorized logbook
access key), which previously surfaced as the unhelpful message
"QRZ returned FAIL".
"""
from __future__ import annotations

from typing import Any, Dict

from .cloud_logs import CloudProviderError, QRZCloudAdapter


class QRZCloudAdapterV501(QRZCloudAdapter):
    """Production QRZ adapter with read-access validation and useful errors."""

    @staticmethod
    def _access_help(action: str, original: str) -> str:
        action = action.upper()
        return (
            f"QRZ recusou a operação {action}. "
            "Use a QRZ Logbook API Access Key do logbook correto (não a chave do "
            "serviço XML/callsign). O acesso à Logbook API exige assinatura QRZ "
            "no nível XML ou superior. Se a chave foi copiada do QRZ, gere/recopie "
            "a chave em Logbook → Settings → API e teste novamente. "
            f"Resposta do QRZ: {original}."
        )

    def _post(self, action: str, **fields: Any) -> Dict[str, str]:
        # A pasted key can occasionally contain line breaks/spaces. The official
        # key itself contains dashes, which must be preserved.
        raw_key = str(self.credentials.get("api_key") or "")
        cleaned_key = "".join(raw_key.split())
        if cleaned_key != raw_key:
            self.credentials = {**self.credentials, "api_key": cleaned_key}
        try:
            return super()._post(action, **fields)
        except CloudProviderError as exc:
            message = str(exc).strip()
            if message in {"QRZ returned FAIL", "QRZ returned AUTH"}:
                raise CloudProviderError(self._access_help(action, message)) from exc
            # Preserve specific server reasons, but add context for the common
            # authentication/subscription class of errors.
            lowered = message.lower()
            if any(token in lowered for token in ("invalid key", "access key", "unauthorized", "subscription", "privilege")):
                raise CloudProviderError(self._access_help(action, message)) from exc
            raise

    def test_connection(self) -> Dict[str, Any]:
        # Validate exactly what the product needs: FETCH permission. QRZ's FETCH
        # documentation explicitly supports MAX:0 to return only COUNT, avoiding
        # a full download just to test credentials.
        data = self._post("FETCH", OPTION="MAX:0,TYPE:LOGIDS,STATUS:ALL")
        try:
            count = int(data.get("COUNT") or 0)
        except (TypeError, ValueError):
            count = 0
        return {
            "ok": data.get("RESULT", "").upper() == "OK",
            "records": count,
            "status": "Acesso de leitura à QRZ Logbook API validado.",
        }
