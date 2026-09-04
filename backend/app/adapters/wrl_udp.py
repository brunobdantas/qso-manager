"""WRL local UDP bridge with strict loopback enforcement."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Dict


class WRLSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class WRLPlan:
    host: str
    port: int
    payload: str
    dry_run: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "destination": "WRL",
            "transport": "UDP",
            "host": self.host,
            "port": self.port,
            "payload": self.payload,
            "dry_run": self.dry_run,
        }


class WRLUDPAdapter:
    def __init__(self, host: str = "127.0.0.1", port: int = 2237):
        self.host = host
        self.port = int(port)
        self._validate_destination()

    def _validate_destination(self) -> None:
        if not (1 <= self.port <= 65535):
            raise WRLSafetyError("WRL UDP port must be between 1 and 65535")
        host = self.host.strip().lower()
        if host == "localhost":
            return
        try:
            addr = ipaddress.ip_address(host)
        except ValueError as exc:
            raise WRLSafetyError("WRL UDP destination must be localhost or a loopback IP") from exc
        if not addr.is_loopback:
            raise WRLSafetyError("WRL UDP destination must be loopback-only")

    @staticmethod
    def _field(name: str, value: Any) -> str:
        if value is None or value == "":
            return ""
        text = str(value)
        return f"<{name}:{len(text)}>{text}"

    def build_payload(self, qso) -> str:
        date = qso.qso_date.replace("-", "") if qso.qso_date else None
        time = qso.time_on.replace(":", "") if qso.time_on else None
        freq = f"{qso.freq_hz / 1_000_000:.6f}" if qso.freq_hz else None
        fields = (
            ("CALL", qso.callsign), ("QSO_DATE", date), ("TIME_ON", time),
            ("BAND", qso.band), ("FREQ", freq), ("MODE", qso.mode),
            ("SUBMODE", qso.submode), ("RST_SENT", qso.rst_sent),
            ("RST_RCVD", qso.rst_rcvd), ("GRIDSQUARE", qso.grid),
            ("COMMENT", qso.comment),
        )
        return "".join(self._field(name, value) for name, value in fields) + "<EOR>"

    def plan(self, qso) -> WRLPlan:
        if not qso.callsign or not qso.qso_date:
            raise WRLSafetyError("WRL payload requires CALL and QSO_DATE")
        return WRLPlan(host=self.host, port=self.port, payload=self.build_payload(qso), dry_run=True)

    def send(self, plan: WRLPlan) -> int:
        """Send only to the already validated local loopback endpoint."""
        self._validate_destination()
        data = plan.payload.encode("utf-8")
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        host = "127.0.0.1" if self.host.lower() == "localhost" else self.host
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            return sock.sendto(data, (host, self.port))
