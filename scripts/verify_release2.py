"""Release 2 verification: built frontend + local FastAPI integration."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[PASS] {message}")


def main() -> int:
    print("=" * 72)
    print("PU2BRU QSO MANAGER — RELEASE 2 LOCAL APP VERIFICATION")
    print("=" * 72)

    required = [
        DIST / "index.html",
        ROOT / "setup.ps1",
        ROOT / "start.bat",
        ROOT / "test.bat",
        ROOT / "frontend" / "package.json",
    ]
    for path in required:
        if not path.exists():
            fail(f"missing required file: {path.relative_to(ROOT)}")
    ok("release files present")

    index_text = (DIST / "index.html").read_text(encoding="utf-8")
    if 'id="root"' not in index_text:
        fail("frontend build index does not contain React root")
    ok("frontend build exists")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "release2.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["ENVIRONMENT"] = "test"
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))

        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        health = client.get("/api/health")
        if health.status_code != 200 or health.json().get("status") != "healthy":
            fail(f"health endpoint failed: {health.status_code} {health.text}")
        ok("API health")

        for endpoint in ("/api/qsos", "/api/qsos/normalized", "/api/qsos/divergences", "/api/imports", "/api/audit", "/api/backups"):
            response = client.get(endpoint)
            if response.status_code != 200:
                fail(f"{endpoint} returned {response.status_code}: {response.text}")
        ok("core UI APIs")

        root = client.get("/")
        if root.status_code != 200 or "text/html" not in root.headers.get("content-type", ""):
            fail(f"FastAPI did not serve built frontend: {root.status_code}")
        ok("FastAPI serves React build")

        spa = client.get("/qsos")
        if spa.status_code != 200 or "text/html" not in spa.headers.get("content-type", ""):
            fail("SPA fallback failed")
        ok("SPA fallback")

        docs = client.get("/docs")
        if docs.status_code != 200:
            fail("OpenAPI docs unavailable")
        ok("API docs")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
