"""Runtime path helpers for source and packaged Windows builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PU2BRU QSO Manager"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_packaged() -> bool:
    return is_frozen() or os.getenv("QSO_MANAGER_PACKAGED", "").strip() == "1"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def bundle_root() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return repository_root()


def user_data_root() -> Path:
    override = os.getenv("QSO_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / APP_DIR_NAME

    base = Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "pu2bru-qso-manager"


def ensure_runtime_dirs() -> None:
    if not is_packaged() and not os.getenv("QSO_MANAGER_DATA_DIR"):
        return
    root = user_data_root()
    for name in ("data", "backups", "imports", "exports", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)


def default_database_url() -> str:
    if is_packaged() or os.getenv("QSO_MANAGER_DATA_DIR"):
        ensure_runtime_dirs()
        db_path = (user_data_root() / "data" / "qso_manager.db").resolve()
        return f"sqlite:///{db_path.as_posix()}"
    return "sqlite:///./data/qso_manager.db"


def backup_dir() -> Path:
    if is_packaged() or os.getenv("QSO_MANAGER_DATA_DIR"):
        ensure_runtime_dirs()
        return user_data_root() / "backups"
    return Path("backups")


def env_file_path() -> str:
    if is_packaged() or os.getenv("QSO_MANAGER_DATA_DIR"):
        ensure_runtime_dirs()
        return str(user_data_root() / ".env")
    return ".env"


def frontend_dist_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "frontend" / "dist"
    return repository_root() / "frontend" / "dist"
