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


def _load_existing_verdicts(tsv: str) -> Dict[str, List[str]]:
    """Re-read filled verdicts so rebuilding the sheet never wipes review work.

    Returns `{file: [verdict, notes]}`. A missing or malformed file yields {}.
    """
    import csv

    if not os.path.exists(tsv):
        return {}
    try:
        with open(tsv, encoding="utf-8", newline="") as fh:
            return {r.get("file", ""): [r.get("verdict", ""),
                                        r.get("notes", "")]
                    for r in csv.DictReader(fh, delimiter="\t")}
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}


def run(staging: str) -> Dict:
    manifest = json.load(open(os.path.join(staging, "import_manifest.json"),
                              encoding="utf-8"))
    entries: List[Dict] = manifest.get("entries", [])

    tsv = os.path.join(staging, "review.tsv")
    prior = _load_existing_verdicts(tsv)

    rows = []
    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write("file\tpage\toriginal\tcorrected\tflags\tverdict\tnotes\n")
        for e in entries:
            verdict, notes = prior.get(e["file"], ["", ""])
            rows.append((e, verdict, notes))
            fh.write("\t".join([
                e["file"], _san(e["page"]), _san(e.get("original") or ""),
                _san(e["text"]), ",".join(e.get("flags", [])),
                _san(verdict), _san(notes)]) + "\n")

    trs = []
    for e, verdict, notes in rows:
        src = html.escape(f"lines/{e['file']}", quote=True)
        img = f'<a href="{src}"><img src="{src}" loading="lazy"></a>'
        if verdict == "fix":
            cls = "v bad"
        elif verdict == "ok":
            cls = "v good"
        else:
            cls = "v"
        trs.append(
            f'<tr>'
            f'<td>{img}</td>'
            f'<td class="small">{html.escape(e["page"])}</td>'
            f'<td class="mono small">{html.escape(e.get("original") or "")}'
            f'</td>'
            f'<td class="mono"><b>{html.escape(e["text"])}</b></td>'
            f'<td class="small">{html.escape(", ".join(e.get("flags", [])))}'
            f'</td>'
            f'<td class="{cls}">{html.escape(verdict)}</td>'
            f'<td class="v small">{html.escape(notes)}</td></tr>')

    n_ok = sum(1 for _, v_, _ in rows if v_ == "ok")
    n_fix = sum(1 for _, v_, _ in rows if v_ == "fix")
    tally = ""
    if n_ok or n_fix:
        tally = (f'<p class="small">reviewed: <b>{n_ok + n_fix}</b>/'
                 f'{len(rows)} &mdash; {n_ok} ok, {n_fix} fix'
                 f'{" (fix pending)" if n_fix else ""}.</p>')

    doc = f"""<!doctype html>
<html lang="ne">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(manifest.get('name', 'staging'))} review</title>
<style>
 body {{ font: 14px/1.45 system-ui, sans-serif; margin: 24px; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border: 1px solid #ddd; padding: 4px 6px; text-align: left;
           vertical-align: top; }}
 img {{ max-height: 44px; max-width: 720px; }}
 .mono {{ font-family: ui-monospace, monospace; }}
 .small {{ font-size: 12px; color: #444; }}
 .v {{ font-size: 12px; background: #fffdf3; }}
 .v.good {{ background: #f2fbf2; color: #1c6b1c; }}
 .v.bad {{ background: #fdeeee; color: #a11; font-weight: 600; }}
 tr:nth-child(even) {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>{html.escape(manifest.get('name', 'staging'))} &mdash; owner review</h1>
<p>{len(entries)} digit-bearing labels from the correction-loop batch
(crops shown at original size). Fill <code>review.tsv</code>:
<b>verdict</b> = <code>ok</code> (label is right) or <code>fix</code>
(+ the correct reading in <code>notes</code>).</p>
<p class="small">source: {html.escape(manifest.get('source', ''))} &middot;
labels sha256 {html.escape(manifest.get('labels_sha256', '')[:12])} &middot;
reviewed_by: {html.escape(manifest.get('reviewed_by', ''))}</p>
{tally}
<table>
<tr><th>crop</th><th>page</th><th>engine reading (original)</th>
<th>staged label (corrected)</th><th>flags</th><th>verdict</th>
<th>notes</th></tr>
{''.join(trs)}
</table>
</body>
</html>
"""
    with open(os.path.join(staging, "review.html"), "w",
              encoding="utf-8") as fh:
        fh.write(doc)
    print(json.dumps({"staging": staging, "labels": len(entries),
                      "verdict_ok": n_ok, "verdict_fix": n_fix,
                      "review_html": os.path.join(staging, "review.html"),
                      "review_tsv": tsv}, indent=2))
    return {"labels": len(entries), "ok": n_ok, "fix": n_fix}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    args = ap.parse_args()
    run(args.staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
