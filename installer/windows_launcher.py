"""Robust Windows launcher for PU2BRU QSO Manager v9.

Goals:
- no tkinter/Tcl runtime dependency;
- persistent launcher diagnostics;
- real backend smoke-start path used by CI;
- dynamic localhost port fallback when 8000 is occupied;
- open the browser only after the FastAPI health endpoint is ready.
"""
from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

os.environ.setdefault("QSO_MANAGER_PACKAGED", "1")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORT_SCAN_LIMIT = 20


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _log_path() -> Path:
    try:
        from app.core.runtime import ensure_runtime_dirs, user_data_root
        ensure_runtime_dirs()
        path = user_data_root() / "logs" / "launcher.log"
    except Exception:
        base = Path(os.getenv("LOCALAPPDATA") or Path.home())
        path = base / "PU2BRU QSO Manager" / "logs" / "launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("qso_manager_launcher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(_log_path(), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


LOGGER = None


def _logger() -> logging.Logger:
    global LOGGER
    if LOGGER is None:
        LOGGER = _setup_logging()
    return LOGGER


def _message_box(title: str, message: str, error: bool = False) -> None:
    """Show a native Windows message box without depending on Tcl/Tk."""
    try:
        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
    except Exception:
        _logger().exception("Could not show native message box")


def _url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _health_url(host: str, port: int) -> str:
    return f"{_url(host, port)}/api/health"


def _health_payload(host: str, port: int, timeout: float = 0.75) -> Optional[str]:
    try:
        with urllib.request.urlopen(_health_url(host, port), timeout=timeout) as response:
            if response.status != 200:
                return None
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _is_qso_manager(host: str, port: int) -> bool:
    payload = _health_payload(host, port)
    if not payload:
        return False
    text = payload.lower()
    return "qso" in text or "healthy" in text or '"status"' in text


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _find_port(host: str, preferred: int) -> int:
    if not _port_in_use(host, preferred):
        return preferred
    if _is_qso_manager(host, preferred):
        return preferred
    for port in range(preferred + 1, preferred + PORT_SCAN_LIMIT + 1):
        if not _port_in_use(host, port):
            return port
    raise RuntimeError(
        f"Nenhuma porta local disponível entre {preferred} e {preferred + PORT_SCAN_LIMIT}. "
        "Feche outro aplicativo que esteja usando essas portas e tente novamente."
    )


def _make_uvicorn_config(app, host: str, port: int):
    import uvicorn
    return uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )


def _run_self_test() -> int:
    """Static packaged-runtime test. Does not start the HTTP server."""
    try:
        _ensure_stdio()
        from app.core.runtime import ensure_runtime_dirs, frontend_dist_dir, user_data_root

        ensure_runtime_dirs()
        index = frontend_dist_dir() / "index.html"
        if not index.exists():
            _logger().error("Self-test: frontend index missing at %s", index)
            return 11

        from app.db.database import engine
        from app.main import app

        with engine.connect() as conn:
            if conn.exec_driver_sql("SELECT 1").scalar_one() != 1:
                return 12

        paths = {route.path for route in app.routes}
        required = {
            "/api/health",
            "/api/integrations/status",
            "/api/cloud/status",
            "/api/cloud/analysis",
            "/api/v8/status",
        }
        if not required.issubset(paths):
            _logger().error("Self-test: missing routes %s", sorted(required - paths))
            return 13
        if not user_data_root().exists():
            return 14

        from app.services.cloud_hub_fast_service import CloudHubService
        cloud_status = CloudHubService().status()
        provider_names = {item.get("provider") for item in cloud_status.get("providers", [])}
        required_providers = {"QRZ", "WRL", "CLUBLOG", "EQSL", "HRD"}
        if cloud_status.get("truth_source") != "QRZ" or not required_providers.issubset(provider_names):
            return 16

        config = _make_uvicorn_config(app, DEFAULT_HOST, DEFAULT_PORT)
        if config.log_config is not None:
            return 15
        _logger().info("Self-test passed")
        return 0
    except Exception:
        _logger().exception("Self-test crashed")
        return 99


def _wait_for_health(host: str, port: int, attempts: int = 80, interval: float = 0.25) -> bool:
    for _ in range(attempts):
        if _health_payload(host, port):
            return True
        time.sleep(interval)
    return False


def _run_smoke_start() -> int:
    """Start the real ASGI server and prove HTTP health/root, then stop.

    CI runs this against both the raw bundle and the silently installed copy.
    """
    _ensure_stdio()
    try:
        from app.main import app
        import uvicorn

        host = DEFAULT_HOST
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
            port = int(probe.getsockname()[1])

        config = _make_uvicorn_config(app, host, port)
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, name="qso-manager-smoke", daemon=True)
        thread.start()

        if not _wait_for_health(host, port, attempts=60):
            server.should_exit = True
            thread.join(timeout=5)
            _logger().error("Smoke-start: health endpoint never became ready")
            return 21

        with urllib.request.urlopen(_url(host, port) + "/", timeout=2.0) as response:
            body = response.read(512)
            if response.status != 200 or not body:
                server.should_exit = True
                thread.join(timeout=5)
                return 22

        server.should_exit = True
        thread.join(timeout=8)
        if thread.is_alive():
            return 23
        _logger().info("Smoke-start passed on port %s", port)
        return 0
    except Exception:
        _logger().exception("Smoke-start crashed")
        return 29


def _open_browser_when_ready(host: str, port: int, server) -> None:
    if _wait_for_health(host, port):
        url = _url(host, port)
        _logger().info("Backend ready at %s; opening browser", url)
        try:
            opened = webbrowser.open(url, new=2)
            if not opened:
                _message_box(
                    "PU2BRU QSO Manager",
                    f"O sistema está pronto, mas o navegador não abriu automaticamente.\n\nAbra manualmente:\n{url}",
                )
        except Exception:
            _logger().exception("Browser launch failed")
            _message_box(
                "PU2BRU QSO Manager",
                f"O sistema está pronto, mas o navegador não abriu automaticamente.\n\nAbra manualmente:\n{url}",
            )
        return

    _logger().error("Backend did not become healthy")
    server.should_exit = True
    _message_box(
        "PU2BRU QSO Manager",
        "O servidor local não conseguiu iniciar.\n\n"
        f"Consulte o diagnóstico em:\n{_log_path()}",
        error=True,
    )


def _run_app() -> int:
    _ensure_stdio()
    logger = _logger()
    logger.info("Launching QSO Manager; executable=%s", sys.executable)

    from app.core.config import settings
    from app.core.runtime import ensure_runtime_dirs, user_data_root
    ensure_runtime_dirs()

    host = str(getattr(settings, "backend_host", None) or DEFAULT_HOST)
    preferred = int(getattr(settings, "backend_port", None) or DEFAULT_PORT)
    port = _find_port(host, preferred)

    if _is_qso_manager(host, port):
        url = _url(host, port)
        logger.info("Existing QSO Manager instance detected at %s", url)
        webbrowser.open(url, new=2)
        return 0

    # A non-QSO process may occupy the configured port; transparently move to
    # the next free localhost port instead of failing silently.
    if port != preferred:
        logger.warning("Preferred port %s occupied; using %s", preferred, port)

    from app.main import app
    import uvicorn

    config = _make_uvicorn_config(app, host, port)
    server = uvicorn.Server(config)

    threading.Thread(
        target=_open_browser_when_ready,
        args=(host, port, server),
        name="qso-manager-browser",
        daemon=True,
    ).start()

    try:
        # Run Uvicorn in the main thread. This removes the old Tk event-loop
        # dependency and keeps the frozen process alive for as long as the
        # local backend is serving.
        server.run()
    except Exception as exc:
        logger.exception("Backend server crashed")
        _message_box(
            "PU2BRU QSO Manager",
            "Falha ao iniciar o aplicativo.\n\n"
            f"{exc}\n\n"
            f"Diagnóstico:\n{_log_path()}",
            error=True,
        )
        return 1

    logger.info("QSO Manager stopped; data_root=%s", user_data_root())
    return 0


def main() -> int:
    _ensure_stdio()
    try:
        if "--self-test" in sys.argv:
            return _run_self_test()
        if "--smoke-start" in sys.argv:
            return _run_smoke_start()
        return _run_app()
    except Exception as exc:
        _logger().exception("Launcher failed before server start")
        _message_box(
            "PU2BRU QSO Manager",
            "Falha ao iniciar o aplicativo.\n\n"
            f"{exc}\n\n"
            f"Diagnóstico:\n{_log_path()}",
            error=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
