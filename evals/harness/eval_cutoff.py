"""Capture-time "page cut off" warning (docs/TECH_UPGRADE_PLAN.md, C3).

Reference implementation of the phone's native `cutOff` (RapidOcr.kt
`textBoxes` + OfflinePages-style counting). A page that runs past the edge
of the photo has text lines cut by the frame; a page fully in the frame has
a margin, so its text stops short of the edge.

* The bundled text detector (PP-OCRv6 det small, the phone's RapidOCR port)
  runs on a copy with a 1024 px long side: detection only, no reading.
* A text box "touches" a side when it comes within EDGE (1%) of the frame.
* Warning: CUT_LINES or more boxes touch one side.

Pixel-only measures (dark strokes reaching the edge) were tried first and
dropped: carpets, fabric and wood grain read as text and the warning fired
on 5-30% of usable photos (build/cutoff/proto*.py, not kept).

Data: DocUNet's real phone photos (crop set). They are tightly cropped
around the page, so many touch the frame with paper but not with text,
which is the hard case. "Cut" copies remove 25-40% of the photo from one
side, which cuts through the text on these pages; a second, milder set
removes 8-20% and counts only photos where a detected text line on the
uncut photo crosses the cut (the cut really goes through text).

Targets (written before measuring): fires on <= 5% of the real photos and
on >= 80% of the cut copies. Thresholds chosen on documents 1-32, reported
on 33-65.

Results (2026-11-16, build/cutoff/results.json), test half (docs 33-65):
warns on 3.0% of real photos, 76% of 25-40% cuts, 83% of the 36 milder
cuts that go through text (tuning half: 1.6%, 75%, 79%). The deep-cut
target (80%) is missed by 4 points; one line instead of two reaches 89%
but warns on 6% of usable photos. The warning is advice (owner decision
for C3), so fewer false alarms wins: two lines.

python -m evals.harness.eval_cutoff [--parity values.json]
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
MODEL = os.path.join(ROOT, "mobile", "android", "app", "src", "main", "assets", "rapidocr",
                     "PP-OCRv6_det_small.onnx")
OUT = os.path.join(ROOT, "build", "cutoff")
SIDE = 1024
EDGE = 0.01
CUT_LINES = 2

_session = None


def _det():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    return _session


def text_boxes(bgr):
    """Axis-aligned text boxes (x0, y0, x1, y1) on a SIDE copy, and its size.

    Mirrors RapidOcr.kt `detect` (threshold 0.3, box score 0.5, rectangle
    DB expansion 1.6) on the bounded copy `textBoxes` makes.
    """
    import cv2

    s = SIDE / max(bgr.shape[:2])
    img = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr
    rows, cols = img.shape[:2]
    ratio = max(1.0, 736.0 / min(rows, cols))
    h = max(32, int(round(int(rows * ratio) / 32.0)) * 32)
    w = max(32, int(round(int(cols * ratio) / 32.0)) * 32)
    x = cv2.resize(img, (w, h)).astype(np.float32) / 127.5 - 1.0
    prob = _det().run(None, {_det().get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    ph, pw = prob.shape
    binary = cv2.dilate((prob > 0.3).astype(np.uint8) * 255, np.ones((2, 2), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours[:1000]:
        rect = cv2.minAreaRect(c.astype(np.float32))
        if min(rect[1]) < 3:
            continue
        pts = np.int32(cv2.boxPoints(rect)).astype(np.float64)
        mask = np.zeros((ph, pw), np.uint8)
        cv2.fillPoly(mask, [pts.astype(np.int32)], 1)
        if cv2.mean(prob, mask)[0] < 0.5:
            continue
        area = abs(cv2.contourArea(pts.astype(np.float32)))
        perimeter = cv2.arcLength(pts.astype(np.float32), True)
        if perimeter <= 0:
            continue
        d = area * 1.6 / perimeter
        exp = (rect[0], (rect[1][0] + 2 * d, rect[1][1] + 2 * d), rect[2])
        if min(exp[1]) < 5:
            continue
        q = cv2.boxPoints(exp)
        qx = np.clip(np.rint(q[:, 0] / pw * cols), 0, cols - 1)
        qy = np.clip(np.rint(q[:, 1] / ph * rows), 0, rows - 1)
        boxes.append((qx.min(), qy.min(), qx.max(), qy.max()))
    return boxes, (cols, rows)


def touching(boxes, size) -> dict:
    cols, rows = size
    mx, my = EDGE * cols, EDGE * rows
    out = {"left": 0, "top": 0, "right": 0, "bottom": 0}
    for x0, y0, x1, y1 in boxes:
        out["left"] += int(x0 <= mx)
        out["top"] += int(y0 <= my)
        out["right"] += int(x1 >= cols - 1 - mx)
        out["bottom"] += int(y1 >= rows - 1 - my)
    return out


def cut_off(m: dict) -> bool:
    return max(m.values()) >= CUT_LINES


def _cut(img, side, f):
    h, w = img.shape[:2]
    return {0: lambda: img[int(h * f):], 1: lambda: img[:h - int(h * f)],
            2: lambda: img[:, int(w * f):], 3: lambda: img[:, :w - int(w * f)]}[side]()


def _crosses(boxes, size, side, f) -> bool:
    """A text box on the uncut photo spans the cut line."""
    cols, rows = size
    for x0, y0, x1, y1 in boxes:
        if side in (0, 1):
            y = rows * f if side == 0 else rows * (1 - f)
            if y0 < y < y1:
                return True
        else:
            x = cols * f if side == 2 else cols * (1 - f)
            if x0 < x < x1:
                return True
    return False


def main() -> None:
    import cv2

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parity", help="JSON {file name: native side counts} from the phone")
    args = ap.parse_args()
    photos = sorted(glob.glob(os.path.join(DATA, "*.png")),
                    key=lambda p: [int(x) for x in re.findall(r"\d+", os.path.basename(p))])
    if args.parity:
        native = json.load(open(args.parity, encoding="utf-8"))
        for name, nm in sorted(native.items()):
            src = os.path.join(DATA, name)
            if not os.path.isfile(src):
                src = os.path.join(OUT, "parity", name)
            ref = touching(*text_boxes(cv2.imread(src)))
            same = cut_off(ref) == cut_off(nm)
            print(f"{name}: python {ref} phone {nm}" + ("" if same else "  WARNING DIFFERS"))
        return
    rng = np.random.default_rng(0)
    rows = []
    for path in photos:
        img = cv2.imread(path)
        boxes, size = text_boxes(img)
        side, f = int(rng.integers(4)), float(rng.uniform(0.25, 0.4))
        mside, mf = int(rng.integers(4)), float(rng.uniform(0.08, 0.2))
        rows.append({
            "photo": os.path.basename(path),
            "doc": int(os.path.basename(path).split("_")[0]),
            "real": touching(boxes, size),
            "cut": touching(*text_boxes(_cut(img, side, f))),
            "mild": touching(*text_boxes(_cut(img, mside, mf))),
            "mild_through_text": bool(_crosses(boxes, size, mside, mf)),
        })
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(os.path.join(OUT, "rows.json"), "w"), indent=1)

    def rate(sub, key, t):
        return float(np.mean([max(r[key].values()) >= t for r in sub])) if sub else 0.0

    summary = {}
    for name, sub in (("tuning (docs 1-32)", [r for r in rows if r["doc"] <= 32]),
                      ("test (docs 33-65)", [r for r in rows if r["doc"] > 32])):
        mild = [r for r in sub if r["mild_through_text"]]
        summary[name] = {
            "photos": len(sub),
            "warns_on_real": rate(sub, "real", CUT_LINES),
            "warns_on_cut_25_40": rate(sub, "cut", CUT_LINES),
            "mild_cuts_through_text": len(mild),
            "warns_on_mild_cut": rate(mild, "mild", CUT_LINES),
            "sweep": {t: [rate(sub, "real", t), rate(sub, "cut", t), rate(mild, "mild", t)]
                      for t in (1, 2, 3, 4)},
        }
    json.dump(summary, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
