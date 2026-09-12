"""Runtime diagnostics for installed QSO Manager clients."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from fastapi import APIRouter

from ..core.runtime import frontend_dist_dir, is_frozen, is_packaged, user_data_root
from ..db.database import engine

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _check_write(path: Path) -> bool:
    marker = path / ".qso-manager-write-test"
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
        marker.unlink(missing_ok=True)
        return True
    except Exception:
        try:
            marker.unlink(missing_ok=True)
        except Exception:
            pass
        return False


@router.get("")
def diagnostics():
    root = user_data_root()
    frontend = frontend_dist_dir()
    checks = {}

    try:
        with engine.connect() as conn:
            checks["database"] = conn.exec_driver_sql("SELECT 1").scalar_one() == 1
    except Exception:
        checks["database"] = False

    checks["frontend"] = (frontend / "index.html").exists()
    checks["data_dir_writable"] = _check_write(root / "data")
    checks["logs_dir_writable"] = _check_write(root / "logs")

    try:
        from ..services.cloud_hub_fast_service import CloudHubService
        status = CloudHubService().status()
        providers = [x.get("provider") for x in status.get("providers", [])]
        checks["provider_registry"] = all(x in providers for x in ("QRZ", "WRL", "CLUBLOG", "EQSL", "HRD"))
    except Exception:
        providers = []
        checks["provider_registry"] = False

    healthy = all(checks.values())
    return {
        "ok": healthy,
        "version": "9.0.0",
        "runtime": {
            "packaged": is_packaged(),
            "frozen": is_frozen(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": sys.executable,
            "pid": os.getpid(),
        },
        "paths": {
            "data_root": str(root),
            "frontend": str(frontend),
            "launcher_log": str(root / "logs" / "launcher.log"),
        },
        "checks": checks,
        "providers": providers,
    }


@router.get("/launcher-log")
def launcher_log():
    path = user_data_root() / "logs" / "launcher.log"
    if not path.exists():
        return {"exists": False, "path": str(path), "lines": []}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": str(exc), "lines": []}
    return {"exists": True, "path": str(path), "lines": lines}
