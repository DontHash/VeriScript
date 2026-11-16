"""Validate searchable PDFs against PDF/A-2b with veraPDF (docs/TECH_UPGRADE_PLAN.md E4).

python scripts/check_pdfa.py [file.pdf ...]

Without arguments, writes archive-preset sample PDFs (grey page, colour
page, two-page Devanagari) and validates them. veraPDF is a local tool
(docs/EXTERNAL_ASSETS.md): VERAPDF names its launcher, default
data/external/verapdf/app/verapdf(.bat). Exit status 0 only if every file
is compliant.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def verapdf() -> str:
    name = "verapdf.bat" if os.name == "nt" else "verapdf"
    return os.environ.get("VERAPDF") or os.path.join(ROOT, "data", "external", "verapdf", "app", name)


def validate(path: str) -> tuple[bool, str]:
    tool = verapdf()
    if not os.path.isfile(tool):
        raise FileNotFoundError(f"veraPDF not found at {tool} (see docs/EXTERNAL_ASSETS.md)")
    cmd = [tool, "--format", "text", "-f", "2b", os.path.abspath(path)]
    if os.name == "nt":
        cmd = ["cmd", "/c"] + cmd
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    lines = [l for l in out.stdout.splitlines() if l.startswith(("PASS", "FAIL"))]
    if not lines:
        return False, (out.stdout + out.stderr).strip()[-500:]
    return lines[0].startswith("PASS"), lines[0]


def samples(folder: str) -> list[str]:
    import cv2
    import numpy as np

    from veriscript.document.export import write_searchable_pdf, write_searchable_pdf_pages
    from veriscript.document.ocr import Token

    tokens = [Token("Total 12345", 95, (80, 150, 500, 210)),
              Token("नेपाल सरकार १२,५००.७५", 95, (80, 300, 700, 350))]
    paths = []
    for colour in (False, True):
        img = np.full((1400, 1000, 3), 250, np.uint8)
        cv2.putText(img, "Total 12345", (80, 200), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        if colour:
            cv2.rectangle(img, (600, 50), (900, 300), (30, 30, 200), -1)
        p = os.path.join(folder, f"archive_{'colour' if colour else 'grey'}.pdf")
        write_searchable_pdf(p, img, tokens, size="archive", title="Ward 7 record")
        paths.append(p)
    p = os.path.join(folder, "archive_two_pages.pdf")
    page = np.full((1400, 1000, 3), 245, np.uint8)
    write_searchable_pdf_pages(p, [(page, tokens, 150), (page, tokens[1:], 150)],
                               title="कुल रकम", size="archive")
    paths.append(p)
    return paths


def main(argv: list[str]) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        files = argv or samples(tmp)
        ok = True
        for f in files:
            passed, line = validate(f)
            ok &= passed
            print(("PASS " if passed else "FAIL ") + os.path.basename(f) + ("" if passed else f"  {line}"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
