"""Production release gate for PU2BRU QSO Manager.

This gate is intentionally static and credential-free. It verifies that the
repository, runtime metadata, packaging and safety declarations agree before a
production artifact is built.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"PRODUCTION GATE FAILURE: {message}")


def main() -> int:
    version = read("VERSION").strip()
    contract = json.loads(read("shared/product_contract.json"))
    frontend_pkg = json.loads(read("frontend/package.json"))
    mobile_pkg = json.loads(read("mobile/package.json"))

    require(re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, "VERSION must use semantic versioning")
    require(contract["version"] == version, "product contract version mismatch")
    require(frontend_pkg["version"] == version, "frontend package version mismatch")
    require(mobile_pkg["version"] == version, "mobile package version mismatch")
    require(f'__version__ = "{version}"' in read("backend/app/core/version.py"), "backend version mismatch")
    require(f'#define MyAppVersion "{version}"' in read("installer/qso-manager.iss"), "installer version mismatch")
    require(f"const VERSION = '{version}'" in read("frontend/src/App900.jsx"), "desktop UI version mismatch")
    require(f"const VERSION='{version}'" in read("mobile/src/App900.jsx"), "mobile UI version mismatch")

    main_py = read("backend/app/main.py")
    require("version=__version__" in main_py, "FastAPI must use canonical version")
    launcher = read("installer/windows_launcher.py")
    require('os.environ.setdefault("ENVIRONMENT", "production")' in launcher, "packaged runtime must force production environment")
    require("windows_production_ready" in launcher, "packaged self-test must verify production readiness")

    sync = read("backend/app/services/eqsl_qrz_sync_service.py")
    for marker in (
        "strict_one_to_one",
        "CONTEST_ID",
        "LOTW_QSL_RCVD",
        "fetch_exact",
        "backup",
    ):
        require(marker.lower() in sync.lower(), f"safe eQSL -> QRZ marker missing: {marker}")
    require('"remote_delete": False' in sync, "eQSL -> QRZ must declare no remote delete")

    award_master = read("backend/app/services/award_master_service.py")
    for marker in (
        "safe_to_export",
        "coverage_regressions",
        "ambiguous_pairs_are_never_merged",
        "remote_writes",
        "certified_export",
    ):
        require(marker in award_master, f"Award Master safety marker missing: {marker}")
    product_api = read("backend/app/api/product.py")
    require('@router.post("/award-master/preview")' in product_api, "Award Master preview endpoint missing")
    require('@router.post("/award-master/export")' in product_api, "Award Master export endpoint missing")

    source_sync = read("backend/app/services/sync_job_service.py")
    for marker in (
        "threading.Thread",
        "progress",
        "remote_write",
        "snapshot anterior foi preservado",
        "start_all",
    ):
        require(marker in source_sync, f"parallel source sync safety marker missing: {marker}")
    require('@router.post("/sync-jobs-all")' in product_api, "parallel sync-all endpoint missing")
    require('@router.get("/sync-jobs/{job_id}")' in product_api, "sync progress endpoint missing")

    qrz = read("backend/app/adapters/qrz_cloud_v501.py")
    require('OPTION="REPLACE"' in qrz, "audited QRZ replacement path missing")
    require("protected_fields" in qrz and "expected_fields" in qrz, "QRZ replace must enforce protected fields and live preconditions")

    required_docs = (
        "README.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/ARCHITECTURE.md",
        "docs/PRODUCTION_READINESS.md",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
    )
    for path in required_docs:
        require((ROOT / path).is_file(), f"missing production repository file: {path}")

    readme = read("README.md")
    require(f"v{version}" in readme, "README must identify current production version")
    require("Windows 11" in readme, "README must identify Windows production target")
    require("Android" in readme and "preview" in readme.lower(), "README must describe Android preview status")

    gitignore = read(".gitignore")
    for marker in ("dist-installer/", "mobile/android/", ".coverage", ".ruff_cache/"):
        require(marker in gitignore, f".gitignore missing {marker}")

    print(f"PU2BRU QSO Manager v{version}: production gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
