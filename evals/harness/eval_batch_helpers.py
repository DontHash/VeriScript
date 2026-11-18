"""Batch helpers at capture: same-page detection and keeping the sharper shot
(docs/TECH_UPGRADE_PLAN.md, C4).

Reference implementation of the phone's native `pageFingerprint`
(OfflinePages.kt). When a new photo looks like the previous one in the batch,
the phone asks "Same page again?" and offers to keep only the sharper of the
two (sharpness = the C3 blur measure, eval_capture_quality.py).

Fingerprint: a grey copy with a 1024 px long side, the central 80% (the
frame edge moves most between two shots), equalised, then a 16x16 difference
hash (256 bits; dHash, as planned in mobile/docs/SCAN_CAMERA_PLAN.md).
Two photos are "the same page" when the hashes differ in <= SAME_BITS bits
(88 of 256: set on books 1-2 with a margin below the closest next page).

The hard negative is the next page of the same book: same layout, same
margins, same font. Data:
* books: pages 20-49 of the four scanned Nepali books in
  data/doc_eval/nepali_textbook_scans (120 pages), each "photographed" twice
  with independent jitter (perspective <= 3% of the side, rotation <= 3
  degrees, brightness +-15%, blur sigma <= 1, sensor noise, a desk
  background around it);
* positives: the two shots of one page; negatives: shot of page i vs shot of
  page i+1 (same book).
* DocUNet's two photos of each document (taken from different angles and
  with different folds) are reported as a stress case, not a target.

Best frame: on the same pages, a sharp shot vs one blurred (sigma 1.5 or
3 px motion): how often the C3 sharpness picks the sharp one.

Targets (written before measuring): same-page recall >= 90% on re-shoots,
next-page false alarms <= 1%, best-frame pick >= 95%.

python -m evals.harness.eval_batch_helpers [--parity values.json | --make-parity]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

import numpy as np

from evals.harness.eval_capture_quality import measures

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOKS = os.path.join(ROOT, "data", "doc_eval", "nepali_textbook_scans")
DOCUNET = os.path.join(ROOT, "data", "external", "docunet", "crop")
OUT = os.path.join(ROOT, "build", "batch-helpers")
SIDE = 1024
HASH = 16
SAME_BITS = 88


def fingerprint(bgr) -> np.ndarray:
    """256 booleans: horizontal brightness steps on a 17x16 grid."""
    import cv2

    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    s = SIDE / max(g.shape)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    h, w = g.shape
    g = g[int(h * 0.1):h - int(h * 0.1), int(w * 0.1):w - int(w * 0.1)]
    g = cv2.equalizeHist(g)
    small = cv2.resize(g, (HASH + 1, HASH), interpolation=cv2.INTER_AREA).astype(np.int16)
    return (small[:, 1:] > small[:, :-1]).reshape(-1)


def distance(a, b) -> int:
    return int(np.count_nonzero(np.asarray(a) != np.asarray(b)))


def to_hex(bits) -> str:
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return f"{v:0{len(bits) // 4}x}"


def from_hex(text: str) -> np.ndarray:
    v = int(text, 16)
    n = len(text) * 4
    return np.array([(v >> (n - 1 - i)) & 1 for i in range(n)], bool)


def book_pages():
    import cv2
    import pypdfium2 as pdfium

    pages = []
    for pdf in sorted(glob.glob(os.path.join(BOOKS, "*.pdf"))):
        doc = pdfium.PdfDocument(pdf)
        for i in range(20, min(50, len(doc))):
            page = doc[i]
            scale = 1400 / max(page.get_size())
            img = np.array(page.render(scale=scale).to_pil().convert("RGB"))
            pages.append((os.path.basename(pdf), i, cv2.cvtColor(img, cv2.COLOR_RGB2BGR)))
    return pages


def shoot(page, rng, blur=None):
    """A phone-like photo of a flat page: jittered perspective on a desk."""
    import cv2

    h, w = page.shape[:2]
    W, H = int(w * 1.25), int(h * 1.25)
    desk = np.full((H, W, 3), rng.integers(60, 140, 3), np.uint8)
    desk = cv2.add(desk, rng.normal(0, 8, desk.shape).astype(np.int16).clip(0, 255).astype(np.uint8))
    ox, oy = (W - w) / 2, (H - h) / 2
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + np.float32([ox, oy]) + rng.uniform(-0.03, 0.03, (4, 2)).astype(np.float32) * [w, h]
    angle = rng.uniform(-3, 3)
    rot = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    dst = cv2.transform(dst[None], rot)[0].astype(np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(page, m, (W, H), dst=desk.copy(), borderMode=cv2.BORDER_TRANSPARENT)
    out = np.clip(out.astype(np.float32) * rng.uniform(0.85, 1.15) + rng.normal(0, 4, out.shape), 0, 255).astype(np.uint8)
    sigma = rng.uniform(0, 1.0) if blur is None else 0
    if sigma > 0.2:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    if blur == "gauss":
        out = cv2.GaussianBlur(out, (0, 0), 1.5)
    elif blur == "motion":
        k = np.zeros((7, 7), np.float32)
        k[3, 2:5] = 1 / 3
        k = cv2.warpAffine(k, cv2.getRotationMatrix2D((3, 3), rng.uniform(0, 180), 1), (7, 7))
        out = cv2.filter2D(out, -1, k / k.sum())
    return out


def main() -> None:
    import cv2

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--make-parity", action="store_true",
                    help="write a few shots to build/batch-helpers/parity for the phone")
    ap.add_argument("--parity", help="JSON {file name: native hex hash} from the phone to compare")
    args = ap.parse_args()
    if args.make_parity or args.parity:
        folder = os.path.join(OUT, "parity")
        if args.make_parity:
            os.makedirs(folder, exist_ok=True)
            rng = np.random.default_rng(3)
            for book, i, page in book_pages()[:6]:
                cv2.imwrite(os.path.join(folder, f"{book[:-4]}_{i}.jpg"), shoot(page, rng))
            return
        native = json.load(open(args.parity, encoding="utf-8"))
        worst = 0
        for name, hx in sorted(native.items()):
            ref = fingerprint(cv2.imread(os.path.join(folder, name)))
            d = distance(ref, from_hex(hx))
            worst = max(worst, d)
            print(f"{name}: {d} bits differ")
        print(f"worst {worst} of {HASH * HASH} bits")
        return

    rng = np.random.default_rng(0)
    pages = book_pages()
    shots = [(b, i, shoot(p, rng), shoot(p, rng)) for b, i, p in pages]
    fps = [(b, i, fingerprint(x), fingerprint(y)) for b, i, x, y in shots]
    same = [distance(a, c) for _, _, a, c in fps]
    nxt = [distance(fps[k][3], fps[k + 1][2]) for k in range(len(fps) - 1)
           if fps[k][0] == fps[k + 1][0]]

    docunet = sorted(glob.glob(os.path.join(DOCUNET, "*_1 copy.png")),
                     key=lambda p: int(re.findall(r"\d+", os.path.basename(p))[0]))
    du_same, du_other, du_fp = [], [], []
    for p in docunet:
        q = p.replace("_1 copy", "_2 copy")
        if os.path.isfile(q):
            du_same.append(distance(fingerprint(cv2.imread(p)), fingerprint(cv2.imread(q))))
        du_fp.append(fingerprint(cv2.imread(p)))
    du_other = [distance(du_fp[k], du_fp[k + 1]) for k in range(len(du_fp) - 1)]

    picks = []
    for _b, _i, page in pages:
        sharp = measures(shoot(page, rng, blur="none"))["sharpness"]
        for kind in ("gauss", "motion"):
            picks.append(sharp > measures(shoot(page, rng, blur=kind))["sharpness"])

    def rate(v, t):
        return float(np.mean(np.asarray(v) <= t))

    books = sorted({b for b, _i, _p in pages})
    held = [k for k in range(len(fps)) if fps[k][0] in books[2:]]
    held_same = [same[k] for k in held]
    held_next = [distance(fps[k][3], fps[k + 1][2]) for k in held[:-1]
                 if k + 1 < len(fps) and fps[k][0] == fps[k + 1][0]]
    summary = {
        "book pages": len(pages),
        "held_out_books (threshold set on the first two)": {
            "same_page_recall": rate(held_same, SAME_BITS),
            "next_page_false_alarm": rate(held_next, SAME_BITS),
        },
        "threshold_bits": SAME_BITS,
        "same_page_recall": rate(same, SAME_BITS),
        "next_page_false_alarm": rate(nxt, SAME_BITS),
        "same_bits_p50_p95": [float(np.percentile(same, 50)), float(np.percentile(same, 95))],
        "next_bits_min_p5": [int(min(nxt)), float(np.percentile(nxt, 5))],
        "docunet_two_angles_recall (stress)": rate(du_same, SAME_BITS),
        "docunet_other_document_false_alarm": rate(du_other, SAME_BITS),
        "best_frame_pick": float(np.mean(picks)),
        "sweep": {t: [rate(same, t), rate(nxt, t)] for t in (72, 80, 88, 94, 100)},
    }
    os.makedirs(OUT, exist_ok=True)
    json.dump(summary, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
