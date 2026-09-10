# -*- mode: python ; coding: utf-8 -*-
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

# Use onedir rather than onefile. Besides faster startup, this avoids extracting
# python312.dll to a temporary _MEI directory, which is more likely to be
# blocked/quarantined by endpoint security on user machines.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PU2BRU-QSO-Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PU2BRU-QSO-Manager',
)
