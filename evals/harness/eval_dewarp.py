"""Gate for curved-page flattening on real phone photos (docs/TECH_UPGRADE_PLAN.md, F1).

DocUNet (docs/EXTERNAL_ASSETS.md): 130 phone photos of 65 curved or folded
English documents, each with a flatbed scan. There is no transcription, so
the reference is the pipeline's reading of the flat scan. For every photo the
pipeline reads it as is (today's behaviour) and after UVDoc flattening; both
are scored against that reference:

* CER and WER (order-sensitive), mean with a 95% bootstrap interval of the
  paired difference, and how many photos got better or worse;
* invented-word rate (words in the reading that are not in the reference):
  the honesty check. Flattening must not create text.

Adopt-if (written before the run): mean CER improves and the paired 95%
interval of the difference excludes zero, and the invented-word rate does
not rise by more than 1 percentage point.

python -m evals.harness.eval_dewarp [--limit N]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "external", "docunet")
OUT = os.path.join(ROOT, "build", "dewarp-eval")


def read_text(img):
    from veriscript.document.pipeline import run_document_pipeline

    res = run_document_pipeline(img, lang=None, make_pdf=False, make_overlay=False,
                                make_txt=False, make_json=False, make_md=False)
    return res.ocr.text


def bootstrap_ci(deltas, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    d = np.asarray(deltas, dtype=float)
    means = [rng.choice(d, size=len(d), replace=True).mean() for _ in range(n)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> None:
    import cv2

    from veriscript.core.metrics import bag_stats, cer, wer
    from veriscript.document import dewarp

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not dewarp.available():
        raise SystemExit("UVDoc weights missing; see docs/EXTERNAL_ASSETS.md")
    os.makedirs(OUT, exist_ok=True)
    cache_path = os.path.join(OUT, "cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    def cached(key, fn):
        if key not in cache:
            cache[key] = fn()
            json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        return cache[key]

    photos = sorted(glob.glob(os.path.join(DATA, "crop", "*.png")),
                    key=lambda p: [int(x) for x in re.findall(r"\d+", os.path.basename(p))])
    if args.limit:
        photos = photos[:args.limit]
    rows = []
    for i, path in enumerate(photos, 1):
        doc = os.path.basename(path).split("_")[0]
        scan = os.path.join(DATA, "scan", f"{doc}.png")
        ref = cached(f"scan/{doc}", lambda: read_text(cv2.imread(scan)))
        if len(ref.split()) < 20:
            continue  # nearly textless scan (figures): CER is meaningless
        photo = cv2.imread(path)
        raw = cached(f"raw/{os.path.basename(path)}", lambda: read_text(photo))

        def flat_read():
            t = time.time()
            flat = dewarp.flatten(photo)
            secs = time.time() - t
            cv2.imwrite(os.path.join(OUT, f"flat_{os.path.basename(path)}"),
                        cv2.resize(flat, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA))
            return {"text": read_text(flat), "seconds": secs}
        flat = cached(f"flat/{os.path.basename(path)}", flat_read)
        row = {"photo": os.path.basename(path), "ref_words": len(ref.split()),
               "cer_raw": cer(ref, raw), "cer_flat": cer(ref, flat["text"]),
               "wer_raw": wer(ref, raw), "wer_flat": wer(ref, flat["text"]),
               "inv_raw": bag_stats(ref, raw)["invented_rate"],
               "inv_flat": bag_stats(ref, flat["text"])["invented_rate"],
               "flatten_s": flat["seconds"]}
        rows.append(row)
        print(f"[{i}/{len(photos)}] {row['photo']}: CER {row['cer_raw']:.3f} -> {row['cer_flat']:.3f}",
              flush=True)

    d_cer = [r["cer_flat"] - r["cer_raw"] for r in rows]
    d_wer = [r["wer_flat"] - r["wer_raw"] for r in rows]
    summary = {
        "photos": len(rows),
        "cer_raw": float(np.mean([r["cer_raw"] for r in rows])),
        "cer_flat": float(np.mean([r["cer_flat"] for r in rows])),
        "cer_delta_ci95": bootstrap_ci(d_cer),
        "wer_raw": float(np.mean([r["wer_raw"] for r in rows])),
        "wer_flat": float(np.mean([r["wer_flat"] for r in rows])),
        "wer_delta_ci95": bootstrap_ci(d_wer),
        "better": sum(d < -0.01 for d in d_cer), "worse": sum(d > 0.01 for d in d_cer),
        "invented_raw": float(np.mean([r["inv_raw"] for r in rows])),
        "invented_flat": float(np.mean([r["inv_flat"] for r in rows])),
        "flatten_seconds_mean": float(np.mean([r["flatten_s"] for r in rows])),
    }
    ci = summary["cer_delta_ci95"]
    summary["gate"] = {
        "cer_improves": summary["cer_flat"] < summary["cer_raw"] and ci[1] < 0,
        "invented_ok": summary["invented_flat"] - summary["invented_raw"] <= 0.01,
    }
    summary["gate"]["adopt"] = all(summary["gate"].values())
    json.dump({"summary": summary, "rows": rows}, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
