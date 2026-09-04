"""Windows launcher for the standalone PU2BRU QSO Manager executable."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

os.environ.setdefault("QSO_MANAGER_PACKAGED", "1")

APP_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{APP_URL}/api/health"


def _health_ok(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _port_in_use(host: str = "127.0.0.1", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _run_self_test() -> int:
    try:
        from app.core.runtime import ensure_runtime_dirs, frontend_dist_dir, user_data_root

        ensure_runtime_dirs()
        index = frontend_dist_dir() / "index.html"
        if not index.exists():
            return 11

        from app.db.database import engine
        from app.main import app

        with engine.connect() as conn:
            value = conn.exec_driver_sql("SELECT 1").scalar_one()
            if value != 1:
                return 12

        paths = {route.path for route in app.routes}
        if "/api/health" not in paths or "/api/integrations/status" not in paths:
            return 13
        if not user_data_root().exists():
            return 14
        return 0
    except Exception:
        return 99


def _open_when_ready(root, status_var) -> None:
    for _ in range(60):
        if _health_ok():
            root.after(0, lambda: status_var.set("Sistema pronto. O navegador foi aberto."))
            webbrowser.open(APP_URL)
            return
        time.sleep(0.25)
    root.after(0, lambda: status_var.set("O servidor não respondeu. Feche e abra o aplicativo novamente."))


def _run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox

    if _health_ok():
        webbrowser.open(APP_URL)
        return 0

    if _port_in_use():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "PU2BRU QSO Manager",
            "A porta local 8000 já está em uso por outro programa.\n\nFeche o programa que usa essa porta e tente novamente.",
        )
        root.destroy()
        return 2

    from app.core.runtime import ensure_runtime_dirs, user_data_root
    ensure_runtime_dirs()

    from app.core.config import settings
    from app.main import app
    import uvicorn

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=settings.backend_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    server_thread = threading.Thread(target=server.run, name="qso-manager-server", daemon=True)
    server_thread.start()

    root = tk.Tk()
    root.title("PU2BRU QSO Manager")
    root.geometry("470x230")
    root.resizable(False, False)

    status_var = tk.StringVar(value="Iniciando o QSO Manager…")

    frame = tk.Frame(root, padx=24, pady=22)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="PU2BRU QSO Manager", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    tk.Label(
        frame,
        text="Aplicação local de reconciliação e auditoria de QSOs",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(4, 14))
    tk.Label(frame, textvariable=status_var, font=("Segoe UI", 10), wraplength=420, justify="left").pack(anchor="w")
    tk.Label(
        frame,
        text=f"Dados locais: {user_data_root()}",
        font=("Segoe UI", 8),
        fg="#555555",
        wraplength=420,
        justify="left",
    ).pack(anchor="w", pady=(10, 16))

    buttons = tk.Frame(frame)
    buttons.pack(fill="x")

    tk.Button(buttons, text="Abrir QSO Manager", width=18, command=lambda: webbrowser.open(APP_URL)).pack(side="left")

    def shutdown() -> None:
        server.should_exit = True
        status_var.set("Encerrando…")
        root.after(250, root.destroy)

    tk.Button(buttons, text="Encerrar", width=12, command=shutdown).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", shutdown)

    threading.Thread(target=_open_when_ready, args=(root, status_var), daemon=True).start()
    root.mainloop()

    server.should_exit = True
    server_thread.join(timeout=4)
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _run_self_test()
    try:
        return _run_gui()
    except Exception as exc:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("PU2BRU QSO Manager", f"Falha ao iniciar o aplicativo:\n\n{exc}")
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
