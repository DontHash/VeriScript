#!/usr/bin/env python3
"""import_audit_verdicts.py — owner verdicts -> audited residual set.

Reads the owner-filled `out/audit_v2/labels.tsv` (from
`scripts/build_audit_sheet.py`) and writes
`data/doc_eval/v2_digit_audit_v1/`:

  labels.tsv     the real content-error rows (crops copied in) and the real
                 OCR drops, with owner notes - the audited residual list
  manifest.json  counts + labels sha256

Verdicts kept: `real` (content errors that are genuine product errors) and
`real-drop` (GT numbers the OCR genuinely never produced). `noise`,
`gt-scriptmix` and `ambiguous` rows stay out. Internal set; not frozen; the
audit notes carry the truth for most crops - exact per-crop corrections are
a dedicated pass before any training use.

Usage:
    python scripts/import_audit_verdicts.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_DIR = os.path.join(BASE_DIR, "out", "audit_v2")
OUT_DIR = os.path.join(BASE_DIR, "data", "doc_eval", "v2_digit_audit_v1")
KEEP = {"real": "content_error", "real-drop": "missing_drop"}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _crop_src(rel: str) -> str:
    return os.path.join(AUDIT_DIR, rel.replace("\\", "/"))


def run() -> dict:
    src = os.path.join(AUDIT_DIR, "labels.tsv")
    rows = list(csv.DictReader(open(src, encoding="utf-8"), delimiter="\t"))
    keep = [r for r in rows if (r.get("verdict") or "") in KEEP]
    os.makedirs(os.path.join(OUT_DIR, "crops"), exist_ok=True)

    entries = []
    for r in keep:
        kind = KEEP[(r["verdict"] or "").strip()]
        entry = {
            "page": r["page"], "kind": kind,
            "ocr_text": r["text"], "atoms": r["atoms"],
            "flags": r["flags"], "gt_context": r["gt_context"],
            "owner_notes": r.get("notes", ""),
            "crop": "",
        }
        if kind == "content_error" and r.get("crop"):
            base = os.path.basename(r["crop"].replace("\\", "/"))
            dst = os.path.join(OUT_DIR, "crops", base)
            if os.path.isfile(_crop_src(r["crop"])):
                shutil.copyfile(_crop_src(r["crop"]), dst)
                entry["crop"] = f"crops/{base}"
        entries.append(entry)

    labels_path = os.path.join(OUT_DIR, "labels.tsv")
    with open(labels_path, "w", encoding="utf-8") as fh:
        fh.write("page\tkind\tocr_text\tatoms\tflags\tgt_context\tcrop\t"
                 "owner_notes\n")
        for e in entries:
            fh.write("\t".join(
                str(e[k]).replace("\t", " ").replace("\n", " ")
                for k in ("page", "kind", "ocr_text", "atoms", "flags",
                          "gt_context", "crop", "owner_notes")) + "\n")

    manifest = {
        "name": "v2_digit_audit_v1",
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "owner audit of out/audit_v2 (docs/PLAN.md Appendix AQ)",
        "reviewed_by": "dataset owner (all 147 verdicts reviewed 2026-10-10)",
        "internal_only": True,
        "not_a_frozen_eval_set": True,
        "n_entries": len(entries),
        "n_content_errors": sum(1 for e in entries
                                if e["kind"] == "content_error"),
        "n_real_drops": sum(1 for e in entries
                            if e["kind"] == "missing_drop"),
        "labels_sha256": _sha256(labels_path),
        "entries": entries,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)

    print(json.dumps({k: manifest[k] for k in
                      ("name", "n_entries", "n_content_errors",
                       "n_real_drops", "labels_sha256")}, indent=2))
    return manifest


if __name__ == "__main__":
    run()
