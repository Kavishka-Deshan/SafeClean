# PyInstaller build spec for SafeClean.
#
#   python -m PyInstaller SafeClean.spec --noconfirm
#
# Produces a single dist/SafeClean.exe that opens the main window.

from pathlib import Path

project = Path(SPECPATH)
assets = project / "safeclean" / "assets"

a = Analysis(
    ["main.py"],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(assets / "icon.ico"), "safeclean/assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nothing here is imported; excluding them keeps the binary smaller.
        "numpy", "pandas", "matplotlib", "scipy", "pytest",
        "setuptools", "pip", "PIL", "pystray", "PyQt5", "PySide2",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SafeClean",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,              # no console window
    disable_windowed_traceback=False,
    icon=str(assets / "icon.ico"),
    version=None,
)
