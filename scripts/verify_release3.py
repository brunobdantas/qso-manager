"""Final Release 3 integration verification.

This verifier requires no external credentials and never performs external
network I/O. QRZ must remain fail-closed; WRL is exercised in dry-run mode.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[PASS] {message}")


def main() -> int:
    print("=" * 72)
    print("PU2BRU QSO MANAGER — RELEASE 3 FINAL VERIFICATION")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "release3.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["ENVIRONMENT"] = "test"
        os.environ["QRZ_WRITE_ENABLED"] = "false"
        os.environ["QRZ_DRY_RUN"] = "true"
        os.environ["WRL_UDP_ENABLED"] = "false"
        os.environ["WRL_UDP_HOST"] = "127.0.0.1"
        os.environ["WRL_UDP_PORT"] = "2237"
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))

        from fastapi.testclient import TestClient
        from app.core.config import settings
        from app.db.database import SessionLocal
        from app.main import app
        from app.models.models import LogicalQSO, QSOIdentity, SyncJob

        if settings.qrz_write_enabled:
            fail("QRZ write default is not fail-closed")
        if settings.wrl_udp_enabled:
            fail("WRL UDP default should require explicit enablement")
        ok("safe integration defaults")

        db = SessionLocal()
        identity = QSOIdentity(
            uuid="release3-identity",
            callsign="K1ABC",
            qso_date="2026-09-04",
            time_on="12:39:00",
        )
        db.add(identity); db.flush()
        qso = LogicalQSO(
            uuid="release3-qso",
            qso_identity_id=identity.id,
            callsign="K1ABC",
            qso_date="2026-09-04",
            time_on="12:39:00",
            band="15M",
            freq_hz=21076900,
            mode="MFSK",
            submode="FT4",
            operating_mode="FT4",
            status="reconciled",
            divergence_count=0,
        )
        db.add(qso); db.commit(); db.close()

        client = TestClient(app)
        status = client.get("/api/integrations/status")
        if status.status_code != 200:
            fail(f"integration status: {status.status_code} {status.text}")
        body = status.json()
        if body["qrz"]["write_enabled"] is not False or body["qrz"]["live_transport"] != "locked":
            fail("QRZ status does not clearly report locked live transport")
        if not body["wrl"]["loopback_safe"]:
            fail("WRL default is not loopback-safe")
        ok("integration status API")

        qrz = client.post("/api/integrations/qrz/preview/release3-qso", json={"operation": "replace"})
        if qrz.status_code != 200:
            fail(f"QRZ preview: {qrz.status_code} {qrz.text}")
        qrz_body = qrz.json()
        if not qrz_body.get("dry_run") or qrz_body.get("real_write_allowed") is not False:
            fail("QRZ preview is not a strict dry-run")
        if qrz_body.get("locator", {}).get("TIME_ON") != "123900":
            fail("QRZ exact locator not preserved")
        ok("QRZ exact dry-run preview")

        live = client.post("/api/integrations/qrz/apply/release3-qso", json={"operation": "replace"})
        if live.status_code != 423:
            fail(f"QRZ live endpoint was not locked: {live.status_code}")
        ok("QRZ real write hard lock")

        preview = client.post("/api/integrations/wrl/preview/release3-qso")
        if preview.status_code != 200 or preview.json().get("host") != "127.0.0.1":
            fail(f"WRL preview failed: {preview.status_code} {preview.text}")
        ok("WRL local UDP preview")

        dry = client.post("/api/integrations/wrl/send/release3-qso", json={"dry_run": True})
        if dry.status_code != 200 or dry.json().get("sent") is not False:
            fail(f"WRL dry-run failed: {dry.status_code} {dry.text}")
        db = SessionLocal()
        if db.query(SyncJob).count() != 1:
            fail("WRL dry-run was not auditable through SyncJob")
        db.close()
        ok("WRL dry-run audit trail")

        blocked = client.post("/api/integrations/wrl/send/release3-qso", json={"dry_run": False})
        if blocked.status_code != 409:
            fail(f"WRL real send should be disabled by default: {blocked.status_code}")
        ok("WRL real send explicit enable gate")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
