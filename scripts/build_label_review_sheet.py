#!/usr/bin/env python3
"""build_label_review_sheet.py — owner review sheet for a staged beta batch.

Reads a staging dir (`import_manifest.json` + `lines/`) produced by
`scripts/corrections_beta.py import` and writes:

  review.html   viewer: crop + page + original -> corrected + flags
  review.tsv    one row per label; fill `verdict` (`ok` | `fix`) + `notes`

Usage:
    python scripts/build_label_review_sheet.py \
        --staging data/doc_eval/target_domain_digit_staging_v2
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


def _san(s: str) -> str:
    return (s or "").replace("\t", " ").replace("\n", " ").strip()


def run(staging: str) -> Dict:
    manifest = json.load(open(os.path.join(staging, "import_manifest.json"),
                              encoding="utf-8"))
    entries: List[Dict] = manifest.get("entries", [])

    tsv = os.path.join(staging, "review.tsv")
    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write("file\tpage\toriginal\tcorrected\tflags\tverdict\tnotes\n")
        for e in entries:
            fh.write("\t".join([
                e["file"], _san(e["page"]), _san(e.get("original") or ""),
                _san(e["text"]), ",".join(e.get("flags", [])),
                "", ""]) + "\n")

    rows = []
    for e in entries:
        rows.append(
            f'<tr>'
            f'<td><img src="lines/{html.escape(e["file"])}"></td>'
            f'<td class="small">{html.escape(e["page"])}</td>'
            f'<td class="mono small">{html.escape(e.get("original") or "")}'
            f'</td>'
            f'<td class="mono"><b>{html.escape(e["text"])}</b></td>'
            f'<td class="small">{html.escape(", ".join(e.get("flags", [])))}'
            f'</td></tr>')
    doc = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(manifest.get('name', 'staging'))} review</title>
<style>
 body {{ font: 14px/1.45 system-ui, sans-serif; margin: 24px; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border: 1px solid #ddd; padding: 4px 6px; text-align: left;
           vertical-align: top; }}
 img {{ max-height: 44px; max-width: 720px; }}
 .mono {{ font-family: ui-monospace, monospace; }}
 .small {{ font-size: 12px; color: #444; }}
 tr:nth-child(even) {{ background: #fafafa; }}
</style>
<h1>{html.escape(manifest.get('name', 'staging'))} &mdash; owner review</h1>
<p>{len(entries)} digit-bearing labels from the correction-loop batch
(crops shown at original size). Fill <code>review.tsv</code>:
<b>verdict</b> = <code>ok</code> (label is right) or <code>fix</code>
(+ the correct reading in <code>notes</code>).</p>
<p class="small">source: {html.escape(manifest.get('source', ''))} &middot;
labels sha256 {html.escape(manifest.get('labels_sha256', '')[:12])}</p>
<table>
<tr><th>crop</th><th>page</th><th>engine reading (original)</th>
<th>staged label (corrected)</th><th>flags</th></tr>
{''.join(rows)}
</table>
"""
    with open(os.path.join(staging, "review.html"), "w",
              encoding="utf-8") as fh:
        fh.write(doc)
    print(json.dumps({"staging": staging, "labels": len(entries),
                      "review_html": os.path.join(staging, "review.html"),
                      "review_tsv": tsv}, indent=2))
    return {"labels": len(entries)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    args = ap.parse_args()
    run(args.staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
