# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

project_dir = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(project_dir, 'frontend', 'dist'), 'frontend_dist'),
    (os.path.join(project_dir, 'backend'), 'backend'),
]

# Include Pay.xlsx if it exists in the workspace or backend/data
if os.path.exists(os.path.join(project_dir, 'Pay.xlsx')):
    datas.append((os.path.join(project_dir, 'Pay.xlsx'), '.'))
elif os.path.exists(os.path.join(project_dir, 'backend', 'data', 'Pay.xlsx')):
    datas.append((os.path.join(project_dir, 'backend', 'data', 'Pay.xlsx'), '.'))

hidden_imports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans',
    'uvicorn.lifespans.auto',
    'uvicorn.lifespans.on',
    'uvicorn.lifespans.off',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.sqlite.pysqlite',
    'pandas',
    'openpyxl',
    'multipart',
    'multipart.multipart',
    'tkinter',
    'tkinter.messagebox',
    'main',
    'models',
    'services',
    'services.db_service',
    'services.excel_service',
    'services.status_engine',
]

a = Analysis(
    ['launcher.py'],
    pathex=[project_dir, os.path.join(project_dir, 'backend')],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'unittest', 'IPython', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Payble',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
