"""Finger cleanup for book pages (docs/TECH_UPGRADE_PLAN.md, F3).

Holding a book open puts thumbs and fingers on the page margins. This
blanks them with the page's own paper colour, and never repaints text:

* skin: YCrCb chroma inside the usual skin cluster (Cr 136-175, Cb 80-130)
  and not near-grey, which covers light to dark skin tones; paper and ink
  are near-grey, so they fall outside it;
* only regions that touch the left, right or bottom edge of the page (where
  a hand holds a book), are at most MAX_AREA of the page and reach at most
  MAX_DEPTH into it, meet the edge along a short stretch (a finger, not a
  picture printed to the edge) and are smooth inside (skin, not print);
* the blanked area is the region grown by a few pixels (soft finger edges),
  minus every ink pixel (black-hat ink map): text and lines under or next to
  a finger keep their pixels exactly. A dark finger region that reads as ink
  is left alone.
* the fill is flat: the median paper colour around the region. No
  inpainting: nothing that looks like content is invented.

Reference for the phone's port (OfflinePages.kt `cleanFingers`);
evaluated in evals/harness/eval_fingers.py.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

CR = (136, 175)
CB = (80, 130)
MIN_CHROMA = 12       # distance from grey in the Cr/Cb plane
MAX_AREA = 0.15       # of the page
MAX_DEPTH = 0.30      # of the page width (side edges) or height (bottom)
MIN_AREA = 0.0008     # of the page; smaller specks are colour noise
EDGE = 0.02           # a region must come within 2% of an edge
GROW = 3              # px at 1000 px long side
MAX_CONTACT = 0.20    # a finger meets the edge along at most 20% of it
MAX_TEXTURE = 25.0    # mean gradient inside: skin is smooth, print is not
NEUTRAL = 6           # chroma below this is grey: ink or paper, never skin


def _ink(grey: np.ndarray, k: int) -> np.ndarray:
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    return cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, kernel) > 35


def finger_mask(page_bgr: np.ndarray) -> np.ndarray:
    """Boolean mask of pixels to blank (already excludes ink)."""
    import cv2

    h, w = page_bgr.shape[:2]
    ycc = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2YCrCb)
    cr = ycc[..., 1].astype(np.int16)
    cb = ycc[..., 2].astype(np.int16)
    chroma = np.hypot(cr - 128, cb - 128)
    skin = ((cr >= CR[0]) & (cr <= CR[1]) & (cb >= CB[0]) & (cb <= CB[1])
            & (chroma >= MIN_CHROMA) & (ycc[..., 0] > 40)).astype(np.uint8)
    scale = max(h, w) / 1000.0
    k = max(3, int(round(5 * scale)) | 1)
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(skin, connectivity=8)
    keep = np.zeros((h, w), np.uint8)
    ex, ey = EDGE * w, EDGE * h
    grey = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.GaussianBlur(grey, (0, 0), max(1.0, scale))
    grad = np.hypot(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1))
    band_x, band_y = max(1, int(ex)), max(1, int(ey))
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (MIN_AREA * h * w <= area <= MAX_AREA * h * w):
            continue
        left, right, bottom = x <= ex, x + bw >= w - ex, y + bh >= h - ey
        if not (left or right or bottom):
            continue
        deep = ((left and bw > MAX_DEPTH * w) or (right and bw > MAX_DEPTH * w)
                or (bottom and not (left or right) and bh > MAX_DEPTH * h))
        if deep:
            continue
        region = labels == i
        contact = max(region[:, :band_x].any(1).sum() / h if left else 0,
                      region[:, w - band_x:].any(1).sum() / h if right else 0,
                      region[h - band_y:, :].any(0).sum() / w if bottom else 0)
        if contact > MAX_CONTACT:
            continue
        inner = cv2.erode(region.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)).astype(bool)
        if inner.sum() > 50 and float(grad[inner].mean()) > MAX_TEXTURE:
            continue
        keep[region] = 1
    if not keep.any():
        return keep.astype(bool)
    grow = max(1, int(round(GROW * scale)))
    keep = cv2.dilate(keep, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    # Skin is always coloured; text is not. Never change a colourless pixel:
    # next to a finger the black-hat map can miss a faint stroke (measured:
    # 16 such pixels in 180 shots), but its colour still says ink or paper.
    neutral = chroma < NEUTRAL
    ink = _ink(grey, max(15, int(round(15 * scale)) | 1))
    return keep.astype(bool) & ~ink & ~neutral


def clean_fingers(page_bgr: np.ndarray) -> Tuple[np.ndarray, Dict]:
    """The page with fingers blanked, and what was done.

    Returns (page, {"fingers": regions blanked, "area": fraction of page}).
    The input is not modified."""
    import cv2

    mask = finger_mask(page_bgr)
    if not mask.any():
        return page_bgr, {"fingers": 0, "area": 0.0}
    m8 = mask.astype(np.uint8)
    ring = cv2.dilate(m8, np.ones((25, 25), np.uint8)).astype(bool) & ~mask
    grey = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)
    paper = ring & (grey > np.percentile(grey[ring], 50) if ring.any() else ring)
    sample = page_bgr[paper] if paper.sum() >= 20 else page_bgr[~mask]
    colour = np.median(sample.reshape(-1, 3), axis=0).astype(np.uint8)
    out = page_bgr.copy()
    out[mask] = colour
    n, _ = cv2.connectedComponents(m8)
    return out, {"fingers": int(n - 1), "area": float(mask.mean())}
