# -*- mode: python ; coding: utf-8 -*-
"""
veriscript-server.spec — the desktop app's sidecar: webapp/server.py plus the
built studio, frozen into ONE executable that the Tauri shell starts
(desktop/src-tauri, `externalBin`).

Build it through desktop/scripts/build_sidecar.py, which builds the studio,
runs this spec and copies the result to the name Tauri expects.

Layout inside the bundle (sys._MEIPASS) mirrors the repository, because the
code resolves files relative to its own location:
  vvweb/...                 webapp/vvweb   -> WEBAPP_DIR = _MEIPASS
  frontend/dist/...         webapp/frontend/dist (FRONTEND_DIST)
  veriscript/...            the package    -> paths.ROOT = _MEIPASS
  fonts/, calibration/      repo data the document pipeline reads

Document mode only: the photo upscaler (torch, CC-BY-NC-SA weights) and the
optional bodhan verifier are excluded.

STATUS: written but not yet built on a clean machine — the first build must
be checked with `veriscript-server --help`-style smoke runs (see
desktop/README.md, "Release checklist").
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
WEBAPP = ROOT / "webapp"
DIST = WEBAPP / "frontend" / "dist"
if not (DIST / "index.html").is_file():
    raise SystemExit("webapp/frontend/dist is missing: run `npm run build` in webapp/frontend")

datas = [
    (str(DIST), "frontend/dist"),
    (str(ROOT / "fonts" / "Mukta-Regular.ttf"), "fonts"),
    (str(ROOT / "fonts" / "OFL.txt"), "fonts"),
    (str(ROOT / "calibration" / "rapidocr_devanagari_v1.json"), "calibration"),
]
binaries, hiddenimports = [], []
for pkg in ("rapidocr", "onnxruntime", "reportlab", "pypdfium2", "uvicorn"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("vvweb")
hiddenimports += collect_submodules("veriscript.document")
hiddenimports += collect_submodules("veriscript.core")
hiddenimports += ["multipart", "python_multipart"]

a = Analysis(
    [str(WEBAPP / "server.py")],
    pathex=[str(ROOT), str(WEBAPP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "torch", "torchvision", "matplotlib", "pytest", "tkinter",
        "veriscript.photo", "smart_upscaler",
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
    name="veriscript-server",
    console=False,  # the shell logs stdout/stderr to server.log
    upx=False,
    runtime_tmpdir=None,
)
