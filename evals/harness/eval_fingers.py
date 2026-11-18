"""Finger cleanup for book mode (docs/TECH_UPGRADE_PLAN.md, F3).

Measures veriscript/document/fingers.py. No set of real book photos with
fingers exists here, so fingers are drawn: rounded finger shapes entering a
page from the left, right or bottom edge, in six skin tones from light to
dark, shaded across the finger with a nail highlight and sensor noise, often
over the text margin and sometimes over text.

Pages: 120 pages of the four scanned Nepali books (aged paper, the real
colour problem) and DocUNet's 130 real phone photos (colour print: ads,
faces, product photos), which are not book pages but show where the skin
test would fire on content.

Targets (written before measuring):
* at least 90% of finger pixels blanked, over all tones;
* no pixel that is ink on the clean page is ever changed (outside the
  finger: zero by construction; this checks it);
* clean book pages: blanking on <= 2% of pages;
* DocUNet (stress, reported): pages with any blanking.

python -m evals.harness.eval_fingers
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np

from evals.harness.eval_batch_helpers import book_pages
from veriscript.document.fingers import clean_fingers, _ink

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUNET = os.path.join(ROOT, "data", "external", "docunet", "crop")
OUT = os.path.join(ROOT, "build", "fingers")
#: Skin tones (sRGB), light to dark (Fitzpatrick I-VI style swatches).
TONES = [(241, 194, 167), (224, 172, 135), (198, 134, 96), (161, 102, 66),
         (120, 72, 44), (84, 50, 33)]


def draw_finger(page, rng, tone):
    """Page with one finger, and the finger's mask."""
    import cv2

    h, w = page.shape[:2]
    side = rng.choice(["left", "right", "bottom"])
    width = int(rng.uniform(0.045, 0.08) * (w if side == "bottom" else h))
    length = int(rng.uniform(0.08, 0.22) * (h if side == "bottom" else w))
    mask = np.zeros((h, w), np.uint8)
    if side == "bottom":
        cx = int(rng.uniform(0.15, 0.85) * w)
        p0, p1 = (cx, h + width), (cx + int(rng.uniform(-0.3, 0.3) * length), h - length)
    else:
        cy = int(rng.uniform(0.15, 0.85) * h)
        x0 = -width if side == "left" else w + width
        x1 = length if side == "left" else w - length
        p0, p1 = (x0, cy), (x1, cy + int(rng.uniform(-0.3, 0.3) * length))
    cv2.line(mask, p0, p1, 1, width)
    cv2.circle(mask, p1, width // 2, 1, -1)
    # Shading across the finger: darker at its sides, as a round finger is.
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    shade = 0.70 + 0.30 * np.clip(dist / max(1, width / 2), 0, 1)
    base = np.array(tone[::-1], np.float32) * rng.uniform(0.9, 1.08)
    skin = base[None, None, :] * shade[..., None]
    skin += rng.normal(0, 5, skin.shape)
    nail = np.zeros_like(mask)
    cv2.circle(nail, p1, max(2, width // 4), 1, -1)
    skin[nail.astype(bool)] = np.clip(skin[nail.astype(bool)] * 1.15 + 20, 0, 255)
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.2)[..., None]
    out = (page.astype(np.float32) * (1 - soft) + np.clip(skin, 0, 255) * soft).astype(np.uint8)
    return out, mask.astype(bool)


def main() -> None:
    import cv2

    rng = np.random.default_rng(0)
    pages = book_pages()
    rows = []
    for _book, _i, page in pages:
        grey = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        ink = _ink(grey, max(15, int(round(15 * max(page.shape[:2]) / 1000)) | 1))
        clean, info = clean_fingers(page)
        row = {"clean_blanked": info["area"] > 0}
        for t, tone in enumerate(TONES):
            shot, finger = draw_finger(page, rng, tone)
            out, _ = clean_fingers(shot)
            changed = np.any(out != shot, axis=2)
            # The drawn finger's soft edge (blur sigma 1.2) reaches ~4 px past
            # its mask; those pixels were already altered by the finger.
            zone = cv2.dilate(finger.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
            row[f"tone{t}_recall"] = float(changed[finger].mean())
            row[f"tone{t}_outside"] = float(changed[~zone].mean())
            row[f"tone{t}_ink_changed"] = int((changed & ink & ~zone).sum())
        rows.append(row)
    du = []
    for path in sorted(glob.glob(os.path.join(DOCUNET, "*.png"))):
        _out, info = clean_fingers(cv2.imread(path))
        du.append({"photo": os.path.basename(path), "area": info["area"], "regions": info["fingers"]})

    summary = {
        "book_pages": len(rows),
        "finger_pixels_blanked_by_tone": [round(float(np.mean([r[f"tone{t}_recall"] for r in rows])), 3)
                                          for t in range(len(TONES))],
        "finger_pixels_blanked_all": round(float(np.mean([r[f"tone{t}_recall"] for r in rows
                                                          for t in range(len(TONES))])), 3),
        "non_finger_pixels_changed_mean": float(np.mean([r[f"tone{t}_outside"] for r in rows
                                                         for t in range(len(TONES))])),
        "ink_pixels_changed_total": int(sum(r[f"tone{t}_ink_changed"] for r in rows
                                            for t in range(len(TONES)))),
        "clean_book_pages_blanked": float(np.mean([r["clean_blanked"] for r in rows])),
        "docunet_photos_blanked": float(np.mean([d["area"] > 0 for d in du])),
        "docunet_blanked_area_max": float(max(d["area"] for d in du)),
        "docunet_blanked": [d for d in du if d["area"] > 0][:20],
    }
    os.makedirs(OUT, exist_ok=True)
    json.dump(summary, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
