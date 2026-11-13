"""Build the desktop sidecar (the local VeriScript server) for Tauri.

    python desktop/scripts/build_sidecar.py

1. builds the studio (webapp/frontend: npm ci && npm run build);
2. freezes webapp/server.py with packaging/veriscript-server.spec;
3. copies the executable to desktop/src-tauri/binaries/
   veriscript-server-<rust target triple>[.exe], the name Tauri's
   `externalBin` expects.

Then build the installer:

    cd desktop && npm ci && npm run build -- --config src-tauri/tauri.release.conf.json

Run it in a virtual environment that has requirements.txt,
webapp/requirements-web.txt and pyinstaller installed. Needs ~3 GB free.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "webapp" / "frontend"
SPEC = ROOT / "packaging" / "veriscript-server.spec"
BINARIES = ROOT / "desktop" / "src-tauri" / "binaries"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def run(cmd: list[str], cwd: Path) -> str:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


def target_triple() -> str:
    for line in run(["rustc", "-vV"], ROOT).splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("could not read the Rust host triple from `rustc -vV`")


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("pyinstaller is not installed in this environment")

    run([NPM, "ci"], FRONTEND)
    run([NPM, "run", "build"], FRONTEND)
    work = ROOT / "build" / "sidecar"
    run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
         "--distpath", str(work / "dist"), "--workpath", str(work / "work")], ROOT)

    exe = ".exe" if sys.platform == "win32" else ""
    built = work / "dist" / f"veriscript-server{exe}"
    if not built.is_file():
        raise SystemExit(f"PyInstaller did not produce {built}")
    BINARIES.mkdir(parents=True, exist_ok=True)
    out = BINARIES / f"veriscript-server-{target_triple()}{exe}"
    shutil.copy2(built, out)
    print(f"sidecar ready: {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
