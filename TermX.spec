# PyInstaller build definition for TermX.
#
#   pyinstaller TermX.spec --noconfirm
#
# Produces a single windowed executable in dist/TermX/ (Windows:
# dist/TermX/TermX.exe). Fonts and the version metadata are bundled so the app
# looks identical on machines without Inter or JetBrains Mono installed.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
]

hiddenimports = collect_submodules("termx") + [
    "pydantic",
    "httpx",
    "httpcore",
]

a = Analysis(
    ["termx/__main__.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TermX",
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TermX",
)
