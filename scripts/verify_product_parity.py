"""Static release gate for PU2BRU QSO Manager production contracts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "shared" / "product_contract.json").read_text(encoding="utf-8"))
VERSION = CONTRACT["version"]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"PRODUCT PARITY FAILURE: {message}")


def main() -> int:
    desktop_main = read("frontend/src/main.jsx")
    desktop = read("frontend/src/App900.jsx")
    mobile_main = read("mobile/src/main.jsx")
    mobile = read("mobile/src/App900.jsx")
    backend = read("backend/app/main.py")
    backend_version = read("backend/app/core/version.py")
    frontend_package = json.loads(read("frontend/package.json"))
    product_api = read("backend/app/api/product.py")
    launcher = read("installer/windows_launcher.py")
    installer = read("installer/qso-manager.iss")
    mobile_package = json.loads(read("mobile/package.json"))

    require("App900.jsx" in desktop_main, "desktop must boot the current unified app")
    require("unified900.css" in desktop_main, "desktop must use the unified design system")
    require("App900.jsx" in mobile_main, "mobile must boot the current companion app")
    require("unified900.css" in mobile_main, "mobile must use the unified design system")
    require(f'__version__ = "{VERSION}"' in backend_version, "canonical backend version must match product contract")
    require("version=__version__" in backend, "FastAPI must use the canonical backend version")
    require(frontend_package.get("version") == VERSION, "desktop package version must match product contract")
    require(f'#define MyAppVersion "{VERSION}"' in installer, "Windows installer version must match product contract")
    require(mobile_package.get("version") == VERSION, "Android package version must match product contract")
    require("--gui-smoke-test" in launcher, "Windows launcher must expose an end-to-end GUI smoke test")
    require('prefix="/api/product"' in product_api and '@router.get("/bootstrap")' in product_api, "unified bootstrap endpoint missing")

    for item in CONTRACT["navigation"]:
        nav_id = item["id"]
        require(nav_id in desktop, f"desktop missing navigation capability {nav_id}")
        require(nav_id in mobile, f"mobile missing navigation capability {nav_id}")

    for provider in CONTRACT["providers"]:
        require(provider in desktop, f"desktop missing provider {provider}")
        require(provider in mobile, f"mobile missing provider {provider}")

    windows = CONTRACT["platforms"]["windows"]
    android = CONTRACT["platforms"]["android"]
    require(windows.get("stage") == "production", "Windows must be declared production")
    require(windows.get("eqsl_qrz_safe_sync") is True, "Windows must expose safe eQSL -> QRZ sync")
    require(android.get("stage") == "preview", "Android must remain explicitly preview")
    require(android.get("eqsl_qrz_safe_sync") is False, "Android must not claim QRZ mutation parity")
    require("/api/product/qsl/eqsl-qrz/plan" in desktop, "desktop missing eQSL -> QRZ analysis")
    require("/api/product/qsl/eqsl-qrz/apply" in desktop, "desktop missing eQSL -> QRZ apply")
    require("award_master_safe_adif" in CONTRACT["capabilities"], "product contract missing Award Master capability")
    require("/api/product/award-master/preview" in desktop, "desktop missing Award Master preview")
    require("/api/product/award-master/export" in desktop, "desktop missing Award Master export")
    require('@router.post("/award-master/preview")' in product_api, "backend missing Award Master preview endpoint")
    require('@router.post("/award-master/export")' in product_api, "backend missing Award Master export endpoint")
    require("parallel_source_sync" in CONTRACT["capabilities"], "product contract missing parallel source sync capability")
    require("/api/product/sync-jobs-all" in desktop, "desktop missing parallel sync-all action")
    require("u-source-progress" in desktop, "desktop missing per-source progress UI")
    require('@router.post("/sync-jobs-all")' in product_api, "backend missing parallel sync-all endpoint")
    require('@router.get("/sync-jobs/{job_id}")' in product_api, "backend missing sync progress endpoint")

    markers = {
        "advanced_multi_adif_compare": ("/api/advanced/compare", "matchRecords"),
        "local_hrd_adif_source": ("HRD", "HRD"),
        "hrdlog_adif_bootstrap": ("HRDLOG", "HRDLOG"),
        "hrdlog_online_insert": ("/api/product/hrdlog/push", "pushHRDLog"),
        "adif_export": ("/api/qso-manager/export", "recordToAdif"),
        "activity_history": ("/api/qso-manager/activity", "loadActivity"),
        "credential_security": ("CONEXÃO SEGURA", "SecureStoragePlugin"),
    }
    storage = read("mobile/src/storage.js")
    for capability, (desktop_marker, mobile_marker) in markers.items():
        require(desktop_marker in desktop, f"desktop missing {capability}")
        require(mobile_marker in mobile + storage, f"mobile missing {capability}")

    print(f"QSO Manager {VERSION}: production capability contract passed")
    print(f"Navigation: {', '.join(x['id'] for x in CONTRACT['navigation'])}")
    print(f"Providers: {', '.join(CONTRACT['providers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
