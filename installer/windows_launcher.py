"""Robust Windows launcher for the standalone PU2BRU QSO Manager executable."""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

os.environ.setdefault("QSO_MANAGER_PACKAGED", "1")
APP_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _early_data_root() -> Path:
    override = os.getenv("QSO_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "PU2BRU QSO Manager"


def _setup_logging() -> Path:
    root = _early_data_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "startup.log"
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
        force=True,
    )
    logging.info("=== QSO Manager launcher starting ===")
    logging.info("frozen=%s executable=%s cwd=%s", getattr(sys, "frozen", False), sys.executable, os.getcwd())
    return path


LOG_PATH = _setup_logging()


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _url(port: int, path: str = "") -> str:
    return f"http://{APP_HOST}:{port}{path}"


def _health_ok(port: int, timeout: float = 0.7) -> bool:
    try:
        with urllib.request.urlopen(_url(port, "/api/health"), timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _root_ok(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(_url(port, "/"), timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", errors="ignore").lower()
            return response.status == 200 and ("<html" in body or "<!doctype" in body)
    except Exception:
        return False


def _port_in_use(port: int) -> bool:
    try:
        with socket.create_connection((APP_HOST, port), timeout=0.35):
            return True
    except OSError:
        return False


def _free_port(preferred: int = DEFAULT_PORT) -> int:
    if not _port_in_use(preferred):
        return preferred
    if _health_ok(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((APP_HOST, 0))
        return int(sock.getsockname()[1])


def _make_uvicorn_config(app, port: int):
    import uvicorn
    return uvicorn.Config(
        app=app,
        host=APP_HOST,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )


def _load_app():
    logging.info("Loading runtime and FastAPI application")
    from app.core.runtime import ensure_runtime_dirs, frontend_dist_dir, user_data_root
    ensure_runtime_dirs()
    index = frontend_dist_dir() / "index.html"
    if not index.exists():
        raise RuntimeError(f"Frontend não encontrado no pacote: {index}")
    from app.main import app
    return app, user_data_root(), index


def _run_self_test() -> int:
    try:
        _ensure_stdio()
        app, data_root, _index = _load_app()
        from app.db.database import engine
        with engine.connect() as conn:
            if conn.exec_driver_sql("SELECT 1").scalar_one() != 1:
                return 12
        paths = {route.path for route in app.routes}
        required = {
            "/api/health",
            "/api/cloud/status",
            "/api/qso-manager/options",
            "/api/advanced/compare",
            "/api/product/bootstrap",
            "/api/product/diagnostics",
        }
        if not required.issubset(paths):
            logging.error("Missing routes: %s", sorted(required - paths))
            return 13
        if not data_root.exists():
            return 14
        from app.services.v9_product_service import V9ProductService
        diagnostic = V9ProductService().diagnostics()
        if diagnostic.get("version") != "9.0.0" or not diagnostic.get("capability_parity"):
            return 16
        config = _make_uvicorn_config(app, DEFAULT_PORT)
        if config.log_config is not None:
            return 15
        logging.info("Self-test succeeded")
        return 0
    except Exception:
        logging.exception("Self-test failed")
        return 99


def _run_gui_smoke_test() -> int:
    """CI-only smoke test that exercises Tk, Uvicorn, health and the packaged SPA."""
    server = None
    thread = None
    root = None
    try:
        _ensure_stdio()
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        app, _data_root, _index = _load_app()
        import uvicorn
        port = _free_port(18765)
        server = uvicorn.Server(_make_uvicorn_config(app, port))
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if _health_ok(port) and _root_ok(port):
                logging.info("GUI smoke test succeeded on port %s", port)
                return 0
            time.sleep(0.1)
        logging.error("GUI smoke test timed out")
        return 21
    except Exception:
        logging.exception("GUI smoke test failed")
        return 22
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=4)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def _run_gui() -> int:
    _ensure_stdio()
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("PU2BRU QSO Manager")
    root.geometry("520x270")
    root.resizable(False, False)

    status_var = tk.StringVar(value="Preparando o QSO Manager…")
    detail_var = tk.StringVar(value="Validando componentes locais…")

    frame = tk.Frame(root, padx=26, pady=22)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="PU2BRU QSO Manager", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(frame, text="v9 · log unificado para desktop e mobile", font=("Segoe UI", 10), fg="#35627d").pack(anchor="w", pady=(2, 14))
    tk.Label(frame, textvariable=status_var, font=("Segoe UI", 11, "bold"), wraplength=460, justify="left").pack(anchor="w")
    tk.Label(frame, textvariable=detail_var, font=("Segoe UI", 9), fg="#555555", wraplength=460, justify="left").pack(anchor="w", pady=(5, 15))
    buttons = tk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    open_button = tk.Button(buttons, text="Abrir QSO Manager", width=20, state="disabled")
    open_button.pack(side="left")
    tk.Button(buttons, text="Abrir pasta de logs", width=18, command=lambda: os.startfile(str(LOG_PATH.parent))).pack(side="left", padx=(8, 0))

    server_holder = {"server": None, "thread": None, "port": None}

    def shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True
        status_var.set("Encerrando…")
        root.after(200, root.destroy)

    tk.Button(buttons, text="Encerrar", width=11, command=shutdown).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", shutdown)

    def fail(exc: Exception) -> None:
        logging.error("GUI startup failed: %s\n%s", exc, traceback.format_exc())
        status_var.set("Não foi possível iniciar o QSO Manager.")
        detail_var.set(f"Detalhes gravados em: {LOG_PATH}")
        try:
            messagebox.showerror(
                "PU2BRU QSO Manager",
                f"Falha ao iniciar o aplicativo.\n\n{exc}\n\nLog: {LOG_PATH}",
                parent=root,
            )
        except Exception:
            pass

    def bootstrap() -> None:
        try:
            app, data_root, _index = _load_app()
            from app.core.config import settings
            import uvicorn
            preferred = int(getattr(settings, "backend_port", DEFAULT_PORT) or DEFAULT_PORT)
            if _health_ok(preferred):
                port = preferred
                logging.info("Existing healthy QSO Manager instance detected on %s", port)
                root.after(0, lambda: ready(port, data_root, None, None))
                return
            port = _free_port(preferred)
            config = _make_uvicorn_config(app, port)
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None
            thread = threading.Thread(target=server.run, name="qso-manager-server", daemon=True)
            server_holder.update({"server": server, "thread": thread, "port": port})
            thread.start()
            root.after(0, lambda: status_var.set("Iniciando serviços locais…"))
            for _ in range(120):
                if _health_ok(port) and _root_ok(port):
                    root.after(0, lambda: ready(port, data_root, server, thread))
                    return
                if not thread.is_alive():
                    raise RuntimeError("O servidor local encerrou durante a inicialização")
                time.sleep(0.1)
            raise RuntimeError("O servidor local não ficou pronto no tempo esperado")
        except Exception as exc:
            root.after(0, lambda e=exc: fail(e))

    def ready(port: int, data_root: Path, server, thread) -> None:
        url = _url(port)
        server_holder.update({"server": server, "thread": thread, "port": port})
        status_var.set("Sistema pronto")
        detail_var.set(f"Dados: {data_root} · Endereço local: {url}")
        open_button.configure(state="normal", command=lambda: webbrowser.open(url))
        logging.info("Application ready at %s", url)
        webbrowser.open(url)

    threading.Thread(target=bootstrap, name="qso-manager-bootstrap", daemon=True).start()
    root.mainloop()

    server = server_holder.get("server")
    thread = server_holder.get("thread")
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout=4)
    return 0


def main() -> int:
    _ensure_stdio()
    if "--self-test" in sys.argv:
        return _run_self_test()
    if "--gui-smoke-test" in sys.argv:
        return _run_gui_smoke_test()
    try:
        return _run_gui()
    except Exception as exc:
        logging.exception("Fatal launcher failure")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "PU2BRU QSO Manager",
                f"Falha ao iniciar o aplicativo:\n\n{exc}\n\nLog: {LOG_PATH}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
