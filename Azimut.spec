# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = [
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.simpledialog",
    "customtkinter",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageTk",
    "pystray",
    "pystray._win32",
    "cryptography",
    "azimut.secrets",
    "azimut.bypass_update",
    "azimut.apps",
    "azimut.diagnose",
]

for package in ("customtkinter", "darkdetect", "PIL", "pystray", "cryptography"):
    collected_datas, collected_binaries, collected_hidden = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden

datas += [(str(ROOT / "azimut" / "warp_i1.hex"), "azimut")]

a = Analysis(
    [str(ROOT / "boot.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Azimut",
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
    icon=str(ROOT / "assets" / "azimut-app.ico"),
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Azimut",
)
