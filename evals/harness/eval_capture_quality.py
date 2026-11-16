"""Capture-time quality warnings: blur and glare (docs/TECH_UPGRADE_PLAN.md, C3).

Reference implementation of the phone's native `captureQuality`
(OfflinePages.kt); both work on a grey copy with a 1024 px long side.

* sharpness: on the strongest 10% of edges, median |Laplacian| over median
  gradient magnitude. Contrast-independent; blur lowers it.
* lapvar: variance of the Laplacian (catches very soft photos).
* glare: the largest connected area of near-white (>=245) pixels, as a
  fraction of the frame.

Warnings: blurry if sharpness < 0.40 or lapvar < 250; glare if >= 0.03.
Thresholds were chosen on DocUNet documents 1-32 and are reported on 33-65.

Targets (written before measuring): on DocUNet's real phone photos (all
usable captures) each warning fires on <= 5%; on the same photos with damage
added it fires on >= 90%. Damage, at a 1600 px long side: Gaussian blur
sigma 2, motion blur 15 px at a random angle, and a saturated ellipse over
6% of the frame.

python -m evals.harness.eval_capture_quality [--make-parity | --parity values.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "external", "docunet", "crop")
OUT = os.path.join(ROOT, "build", "capture-quality")
SIDE = 1024
BLUR_SHARPNESS = 0.40
BLUR_LAPVAR = 250.0
GLARE = 0.03


def measures(bgr) -> dict:
    import cv2

    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    s = SIDE / max(g.shape)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    g = g.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3))
    edges = mag > np.percentile(mag, 90)
    sharp = float(np.median(lap[edges]) / (np.median(mag[edges]) + 1e-6)) if edges.any() else 0.0
    lap_var = float(cv2.Laplacian(g, cv2.CV_32F).var())
    bright = (g >= 245).astype(np.uint8)
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    glare = float(stats[1:, cv2.CC_STAT_AREA].max() / g.size) if n > 1 else 0.0
    return {"sharpness": sharp, "lapvar": lap_var, "glare": glare}


def warnings(m: dict) -> dict:
    return {"blurry": m["sharpness"] < BLUR_SHARPNESS or m["lapvar"] < BLUR_LAPVAR,
            "glare": m["glare"] >= GLARE}


def damage(bgr, kind: str, rng):
    import cv2

    s = 1600 / max(bgr.shape[:2])
    img = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr.copy()
    if kind == "gauss":
        return cv2.GaussianBlur(img, (0, 0), 2.0)
    if kind == "motion":
        k = np.zeros((15, 15), np.float32)
        k[7, :] = 1 / 15
        k = cv2.warpAffine(k, cv2.getRotationMatrix2D((7, 7), rng.uniform(0, 180), 1), (15, 15))
        return cv2.filter2D(img, -1, k / k.sum())
    if kind == "glare":
        h, w = img.shape[:2]
        mask = np.zeros((h, w), np.float32)
        a = np.sqrt(0.06 * h * w / np.pi)
        cv2.ellipse(mask, (int(rng.uniform(0.3, 0.7) * w), int(rng.uniform(0.3, 0.7) * h)),
                    (int(a * 1.3), int(a / 1.3)), rng.uniform(0, 180), 0, 360, 1, -1)
        mask = np.clip(cv2.GaussianBlur(mask, (0, 0), a / 6) * 1.6, 0, 1)[..., None]
        return (img * (1 - mask) + 255 * mask).astype(np.uint8)
    return img


def main() -> None:
    import cv2

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parity", help="JSON {file name: native measures} from the phone to compare")
    ap.add_argument("--make-parity", action="store_true",
                    help="write damaged copies of a few photos to build/capture-quality/parity")
    args = ap.parse_args()
    if args.make_parity:
        rng = np.random.default_rng(1)
        os.makedirs(os.path.join(OUT, "parity"), exist_ok=True)
        for doc in ("1_1", "23_1", "47_1"):
            img = cv2.imread(os.path.join(DATA, f"{doc} copy.png"))
            for kind in ("gauss", "motion", "glare"):
                cv2.imwrite(os.path.join(OUT, "parity", f"{doc}_{kind}.png"), damage(img, kind, rng))
        return
    photos = sorted(glob.glob(os.path.join(DATA, "*.png")),
                    key=lambda p: [int(x) for x in re.findall(r"\d+", os.path.basename(p))])
    if args.parity:
        native = json.load(open(args.parity, encoding="utf-8"))
        for name, nm in sorted(native.items()):
            src = os.path.join(DATA, name)
            if not os.path.isfile(src):  # damaged copies made with --make-parity
                src = os.path.join(OUT, "parity", name)
            ref = measures(cv2.imread(src))
            same = warnings(ref) == warnings(nm)
            print(f"{name}: " + ", ".join(f"{k} {ref[k]:.4f}/{nm[k]:.4f}" for k in ref)
                  + ("" if same else "  WARNINGS DIFFER"))
        return
    rng = np.random.default_rng(0)
    rows = []
    for path in photos:
        img = cv2.imread(path)
        row = {"photo": os.path.basename(path), "doc": int(os.path.basename(path).split("_")[0])}
        for kind in ("clean", "gauss", "motion", "glare"):
            row[kind] = warnings(measures(damage(img, kind, rng)))
        rows.append(row)

    def rate(sub, kind, warning):
        return float(np.mean([r[kind][warning] for r in sub]))

    summary = {}
    for name, sub in (("tuning (docs 1-32)", [r for r in rows if r["doc"] <= 32]),
                      ("test (docs 33-65)", [r for r in rows if r["doc"] > 32])):
        summary[name] = {
            "photos": len(sub),
            "blurry_on_real": rate(sub, "clean", "blurry"),
            "blurry_on_gauss": rate(sub, "gauss", "blurry"),
            "blurry_on_motion": rate(sub, "motion", "blurry"),
            "glare_on_real": rate(sub, "clean", "glare"),
            "glare_on_glare": rate(sub, "glare", "glare"),
            "any_on_real": float(np.mean([r["clean"]["blurry"] or r["clean"]["glare"] for r in sub])),
        }
    os.makedirs(OUT, exist_ok=True)
    json.dump({"summary": summary, "rows": rows}, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
