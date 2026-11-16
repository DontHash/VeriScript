"""Fetch the pinned UVDoc model and export it to ONNX for the app
(docs/TECH_UPGRADE_PLAN.md F1; docs/EXTERNAL_ASSETS.md).

Like prepare_rapidocr.py: every file is checked against its pinned SHA-256
before use, and nothing is downloaded at app runtime. The checkpoint is a
pickle; it is only ever loaded with torch.load(weights_only=True).
Needs PyTorch (CPU), onnx and onnxruntime on the build machine.

python mobile/tool/prepare_uvdoc.py
"""
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "external" / "uvdoc"
COMMIT = "4c9b82b537057aff2526e6dd118a847cdd072e82"
BASE = f"https://raw.githubusercontent.com/tanguymagne/UVDoc/{COMMIT}/"
FILES = {
    # path: sha256 (text files hashed with LF line endings)
    "model/best_model.pkl": "7e90861b8a516eb4bc51f84bd889cb77275743d2d1d3ca8091951ec9f2b7da23",
    "model.py": "320f460edc54cf830dfdd9788dfbc1b96a836429b64ed6078a30582be6f59e42",
    "LICENSE": None,  # kept beside the model for the licence notice
}


def digest(data: bytes, text: bool) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()


def main() -> None:
    for name, sha in FILES.items():
        out = TARGET / name
        text = not name.endswith(".pkl")
        if out.exists() and (sha is None or digest(out.read_bytes(), text) == sha):
            continue
        with urllib.request.urlopen(BASE + name, timeout=300) as response:
            data = response.read()
        if sha is not None and digest(data, text) != sha:
            raise SystemExit(f"UVDoc checksum mismatch: {name}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(name, len(data))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_uvdoc_onnx.py")], check=True)


if __name__ == "__main__":
    main()
