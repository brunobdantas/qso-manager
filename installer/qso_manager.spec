# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPEC).resolve().parent
ROOT_DIR = SPEC_DIR.parent
BACKEND_DIR = ROOT_DIR / 'backend'
FRONTEND_DIST = ROOT_DIR / 'frontend' / 'dist'

sys.path.insert(0, str(BACKEND_DIR))

hiddenimports = collect_submodules('app') + collect_submodules('uvicorn') + [
    'sqlalchemy.dialects.sqlite.pysqlite',
]

a = Analysis(
    [str(SPEC_DIR / 'windows_launcher.py')],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=[(str(FRONTEND_DIST), 'frontend/dist')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PU2BRU-QSO-Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
