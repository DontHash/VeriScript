#!/usr/bin/env python3
"""import_label_review.py — apply owner verdicts to a staged beta batch.

Reads `<staging>/review.tsv` (columns: file, page, original, corrected,
flags, verdict, notes) produced by `scripts/build_label_review_sheet.py`:

* verdict `ok`   -> label kept as staged
* verdict `fix`  -> the corrected reading replaces the label; the reading is
  taken from `notes` after a `Correct reading:` marker when present, else the
  whole `notes` field is used (documented convention: for `fix` rows, notes
  should carry the corrected reading, optionally after that marker)

Rewrites `<staging>/labels.tsv` and updates `import_manifest.json`
(reviewed_by, audit counts, new labels sha256).

Usage:
    python scripts/import_label_review.py \
        --staging data/doc_eval/target_domain_digit_staging_v2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _corrected_from_notes(notes: str) -> str:
    m = re.search(r"Correct reading:\s*(.+)$", notes or "", re.S)
    return (m.group(1) if m else (notes or "")).strip()


def run(staging: str) -> Dict:
    review_path = os.path.join(staging, "review.tsv")
    with open(review_path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = [dict(zip(header, line.rstrip("\n").split("\t")))
                for line in fh if line.strip()]
    verdicts = [r for r in rows if (r.get("verdict") or "").strip()]
    if len(verdicts) != len(rows):
        raise SystemExit(f"{review_path}: {len(rows) - len(verdicts)} rows "
                         f"have no verdict")

    manifest_path = os.path.join(staging, "import_manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    by_file = {e["file"]: e for e in manifest["entries"]}

    ok = fixed = 0
    changes: List[Dict] = []
    for r in rows:
        verdict = r["verdict"].strip()
        entry = by_file.get(r["file"])
        if entry is None:
            raise SystemExit(f"unknown file in review: {r['file']}")
        if verdict == "ok":
            ok += 1
        elif verdict == "fix":
            corrected = _corrected_from_notes(r.get("notes", ""))
            if not corrected:
                raise SystemExit(f"{r['file']}: verdict fix but no corrected "
                                 f"reading in notes")
            changes.append({"file": r["file"], "before": entry["text"],
                            "after": corrected})
            entry["text"] = corrected
            fixed += 1
        else:
            raise SystemExit(f"{r['file']}: unknown verdict {verdict!r}")

    labels_path = os.path.join(staging, "labels.tsv")
    with open(labels_path, "w", encoding="utf-8", newline="\n") as fh:
        for e in manifest["entries"]:
            fh.write(f"{e['file']}\t{e['text']}\n")

    manifest["reviewed_by"] = ("dataset owner audit applied; "
                               f"{ok} ok / {fixed} fix")
    manifest["audit"] = {"reviewed": len(rows), "ok": ok, "fixed": fixed,
                         "applied_at": __import__("time").strftime(
                             "%Y-%m-%dT%H:%M:%S"),
                         "changes": changes}
    manifest["labels_sha256"] = _sha256(labels_path)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)

    out = {"staging": staging, "reviewed": len(rows), "ok": ok,
           "fixed": fixed, "labels_sha256": manifest["labels_sha256"]}
    print(json.dumps(out, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    args = ap.parse_args()
    run(args.staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
