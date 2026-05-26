# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the OpenRouter edition of the Prompt Optimizer desktop app.

One-dir build (faster startup, no per-launch temp extraction — important because
the GUI re-spawns this exe in --run-server mode). Bundles the FastAPI app, static
frontend, assets, and the pywebview/pythonnet stack. The optional Hermes framework
(`run_agent`) is intentionally excluded; the app degrades gracefully without it.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

APP_NAME = "Prompt Optimizer OpenRouter"

datas = [
    ("static", "static"),
    ("assets", "assets"),
    ("docs", "docs"),
]
binaries = []
hiddenimports = []

# Our own package (agents are imported indirectly, so collect them all).
hiddenimports += collect_submodules("app")

# uvicorn picks its loop/protocol implementations via dynamic imports.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("anyio")
hiddenimports += ["uvicorn.lifespan.on", "uvicorn.loops.asyncio",
                  "uvicorn.protocols.http.h11_impl",
                  "uvicorn.protocols.websockets.websockets_impl"]

# pydantic v2 has compiled + dynamic bits.
hiddenimports += collect_submodules("pydantic")

# pywebview ships JS resource files and uses the EdgeChromium (WinForms) backend.
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass
hiddenimports += ["clr"]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Hermes agent framework is optional and heavy; exclude it. The app catches
    # the missing `run_agent` import and reports Hermes as "not installed".
    excludes=["run_agent", "tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/skull.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
