"""Bounded, offline book-video capture. No OCR runs during frame selection.

The selector keeps the sharpest frame of each stable view, crops the paper
region (a clean convex quad is rectified; otherwise a bright, low-saturation
paper mask is segmented and its rectangle is cropped), and splits an open
book at its detected binding gutter — never at the frame midpoint when the
book sits off-centre. Sides that are not pages (furniture, a turning leaf) are
dropped, not emitted. Similarity is alignment-tolerant so hand-held wobble
does not read as a page change. Scores are heuristics, not calibrated
probabilities. Review the captured pages before trusting coverage.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

import cv2
import numpy as np

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm"}

# Blurred-detail normalized cross-correlation floors. The continuity floor is
# chosen so a steady page with ordinary hand-held wobble stays above it while
# page turns fall below. Duplicate suppression needs a higher bar: pages that
# share a layout can otherwise correlate past the continuity floor. A learned
# model would replace this if real-book review demands it.
_VIEW_SIMILARITY = 0.78
_VIEW_DUPLICATE = 0.90


@dataclass(frozen=True)
class VideoOptions:
    layout: Literal["auto", "single", "spread"] = "auto"
    sample_fps: float = 4.0
    hold_seconds: float = 0.75
    max_pages: int = 150
    max_seconds: float = 600.0
    max_megapixels: float = 30.0

    def __post_init__(self):
        if self.layout not in {"auto", "single", "spread"}:
            raise ValueError("layout must be auto, single, or spread")
        if (not all(math.isfinite(v) and v > 0 for v in
                    (self.sample_fps, self.hold_seconds, self.max_seconds,
                     self.max_megapixels)) or not 1 <= self.max_pages <= 1000
                or self.sample_fps > 30):
            raise ValueError("invalid video capture limits")


def _check_cancel(cancel: Callable[[], bool] | None):
    if cancel and cancel():
        raise TimeoutError("Video processing cancelled.")


def _ordered_quad(points: np.ndarray) -> np.ndarray:
    # Sort cyclically, then choose the top-left corner. Avoid sum/difference
    # argmins, which can assign the same corner twice on diamond shapes.
    points = points.astype(np.float32).reshape(4, 2)
    centre = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
    points = points[np.argsort(angles)]
    return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)


def _page_view(frame: np.ndarray) -> tuple[np.ndarray, bool, float]:
    """Locate the page (open book or single sheet) and return a tight view.

    Two-stage, deterministic: a clean convex quadrilateral still wins (it
    supports perspective rectification), and when no such quad exists - curved
    pages, patterned furniture, a low-contrast background - the paper region
    itself (bright and barely saturated) is segmented and its rectangle is
    cropped out. Without either cue the full frame is preserved so review
    never silently loses content.
    """
    h, w = frame.shape[:2]
    scale = min(1.0, 960.0 / max(h, w))
    small = cv2.resize(frame, None, fx=scale, fy=scale)
    # Cheap quad first (perspective rectification when the light is clean).
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        area = cv2.contourArea(contour) / gray.size
        if not 0.25 <= area <= 0.98:
            continue
        poly = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        if len(poly) != 4 or not cv2.isContourConvex(poly):
            continue
        quad = _ordered_quad(poly) / scale
        tl, tr, br, bl = quad
        width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        if min(width, height) < 100 or not 0.35 < width / height < 2.5:
            continue
        # A very skewed quadrilateral is likely a turning leaf or an obstruction.
        lengths = [np.linalg.norm(tr - tl), np.linalg.norm(br - bl),
                   np.linalg.norm(bl - tl), np.linalg.norm(br - tr)]
        alignment = min(lengths[:2]) / max(lengths[:2])
        alignment *= min(lengths[2:]) / max(lengths[2:])
        if alignment < 0.55:
            continue
        target = np.float32([[0, 0], [width - 1, 0],
                             [width - 1, height - 1], [0, height - 1]])
        transform = cv2.getPerspectiveTransform(quad, target)
        return cv2.warpPerspective(frame, transform, (width, height)), True, alignment
    # Paper-region fallback: books off-centre, patterned backgrounds, warm light.
    return _paper_rect_view(frame, scale, small)


def _paper_rect_view(frame: np.ndarray, scale: float,
                     small: np.ndarray) -> tuple[np.ndarray, bool, float]:
    """Paper-region fallback: bright, low-saturation segment -> tight rectangle.

    Handles the real-world failure modes of edge quads: books not centered in
    the frame, patterned dark backgrounds (carpet, blanket), shadowed page
    corners and warm light. The rectangle is axis-aligned (no perspective
    rectification), and the page mask is recomputed later for the spread split.
    """
    paper = _paper_mask(small)
    if paper is None:
        return frame, False, 0.5
    ys, xs = np.nonzero(paper)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if bw < 60 or bh < 60 or bw * bh < 0.12 * frame.shape[0] * frame.shape[1]:
        return frame, False, 0.5
    pad_x = int(0.02 * frame.shape[1])
    pad_y = int(0.02 * frame.shape[0])
    box_x0 = max(0, int(x0 / scale) - pad_x)
    box_y0 = max(0, int(y0 / scale) - pad_y)
    box_x1 = min(frame.shape[1], int(x1 / scale) + pad_x + 1)
    box_y1 = min(frame.shape[0], int(y1 / scale) + pad_y + 1)
    if (box_x1 - box_x0) >= frame.shape[1] and (box_y1 - box_y0) >= frame.shape[0]:
        return frame, False, 0.5  # boundary covers the frame; nothing to crop
    crop = frame[box_y0:box_y1, box_x0:box_x1]
    if crop.shape[0] * crop.shape[1] > 0.92 * frame.shape[0] * frame.shape[1]:
        return frame, False, 0.5
    return crop, True, 0.5


def _paper_mask(small: np.ndarray) -> np.ndarray | None:
    """Largest bright, low-saturation connected region (paper) at work scale.

    Returns None when no plausible paper region exists. Blur + morphology close
    bridge the dark text and gutter inside the page; Otsu adapts to the light;
    the saturation guard keeps patterned colourful backgrounds (carpet,
    blanket, book covers) out of the paper region.
    """
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    _, bright = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inside = sat[bright > 0]
    if inside.size == 0:
        return None
    s_hi = min(120.0, float(np.percentile(inside, 85)) * 1.4)
    mask = ((bright > 0) & (sat <= s_hi)).astype(np.uint8) * 255
    k = max(7, min(small.shape[:2]) // 48)
    kernel = np.ones((k, k), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[best, cv2.CC_STAT_AREA] < 0.12 * mask.size:
        return None
    paper = (labels == best).astype(np.uint8) * 255
    return cv2.morphologyEx(paper, cv2.MORPH_CLOSE, kernel)


def _features(view: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    gray = cv2.cvtColor(cv2.resize(view, (224, 224)), cv2.COLOR_BGR2GRAY)
    # Subtract low-frequency lighting; shadows and exposure changes should not
    # alone imply a new page. Edge detail separates pages with similar layouts.
    detail = gray.astype(np.float32) - cv2.GaussianBlur(gray, (0, 0), 5)
    edges = cv2.Canny(gray, 40, 100) > 0
    sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    return detail, edges, sharpness


def _same_view(a, b, needed: float = _VIEW_SIMILARITY) -> bool:
    """Motion-tolerant view match: blurred-detail normalized cross-correlation.

    A fixed pixel diff rejects every hand-held frame because sub-pixel text
    shifts alias heavily. Smoothing and a small translation search let the same
    page match across ordinary camera wobble while different pages stay apart.
    A view without detail (transition frame, blank page) matches nothing.
    """
    if a is None or b is None:
        return False
    if float(np.std(a[0])) < 1.0 or float(np.std(b[0])) < 1.0:
        return False
    left = cv2.GaussianBlur(a[0], (0, 0), 1.5)
    right = cv2.GaussianBlur(b[0], (0, 0), 1.5)
    pad = 10
    padded = cv2.copyMakeBorder(right, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    score = float(cv2.matchTemplate(padded, left, cv2.TM_CCOEFF_NORMED).max())
    return math.isfinite(score) and score >= needed


def _fixed_split(view: np.ndarray, layout: str):
    """Split without a paper mask: binding search near the frame midpoint."""
    h, w = view.shape[:2]
    spread = layout == "spread" or (layout == "auto" and w / h > 1.15)
    if not spread:
        return [("single", view)]
    gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    profile = gray[int(h * .15):int(h * .85)].mean(axis=0)
    profile = cv2.GaussianBlur(profile.astype(np.float32)[None, :], (0, 0), 3)[0]
    lo, hi = int(w * .45), int(w * .55)
    cut = lo + int(np.argmin(profile[lo:hi]))
    if float(np.median(profile[lo:hi]) - profile[cut]) < 15:
        cut = w // 2
    return [("left", view[:, :cut]), ("right", view[:, cut:])]


def _gutter_cut(view: np.ndarray, paper: np.ndarray) -> int | None:
    """Binding column inside the paper bounding box, or None when unsure.

    The profile averages brightness only over columns where paper spans at
    least half of its height, so furniture beside the book cannot darken the
    profile. The binding is the darkest *valley* with real prominence over
    flanking page brightness — text columns are light, shadows are not.
    """
    x, y, w, h = cv2.boundingRect(paper)
    if w < 240:
        return None
    span = (paper > 0).mean(axis=0)
    gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    profile = np.where(span > 0.5, gray.mean(axis=0), 255.0).astype(np.float32)
    profile = cv2.GaussianBlur(profile[None, :], (0, 0), 3)[0]
    lo, hi = x + int(w * 0.26), x + int(w * 0.78)
    # When the paper bbox tails off (a leaf or finger crossing the page), the
    # bulk of the book ends before that tail: cap the search at the end of the
    # first contiguous full-span run, so a tail's shadow cannot pull the cut.
    peaks = np.nonzero(span >= 0.9 * float(span.max()))[0]
    if peaks.size and lo < peaks[0] < hi:
        last = peaks[0]
        for p in peaks[1:]:
            if p == last + 1:
                last = p
            else:
                break
        hi = max(lo + 32, min(int(last), hi))
    band = profile[lo:hi]
    if band.size < 16:
        return None
    base = float(np.median(band))
    valleys = []
    for i in range(2, band.size - 2):
        j = lo + i
        if (profile[j] <= profile[j - 2] - 6 and profile[j] <= profile[j + 2] - 6
                and base - profile[j] >= 12):
            valleys.append((abs(j - (lo + band.size / 2)), j))
    if valleys:
        return min(valleys)[1]
    # No sharp valley: a broad binding curve still shows as the global minimum
    # with a real drop around it. Require one clean flank at least — a shadowed
    # page edge sits inside a monotone dark run, so its flank never rises.
    cut = lo + int(np.argmin(band))
    r = int(0.06 * w) + 20
    left_flank = profile[max(x, cut - r)]
    right_flank = profile[min(x + w - 1, cut + r)]
    rises = (profile[cut] <= left_flank - 8 and profile[cut] <= right_flank + 90
             and (left_flank - profile[cut] >= 8)) or (
        profile[cut] <= right_flank - 8 and left_flank - profile[cut] >= 8)
    if float(np.median(band) - profile[cut]) >= 12 and rises:
        return cut
    return None


def _side_crop(frame: np.ndarray, paper: np.ndarray, x_from: int, x_to: int
               ) -> np.ndarray | None:
    """Tight paper bounding box for one side; None when it is not a page.

    A side is dropped when its paper region is a sliver (under 8% of frame
    width or 60 px) — blank beyond the spine or a turning leaf — rather than
    emitted as a furniture shot. Outer edges are then trimmed against ink
    evidence: the mask's bbox can include a curled leaf or a finger, which
    shows up as a mostly-dark outer band.
    """
    w = frame.shape[1]
    x_to = min(x_to, w)
    side = paper[:, max(0, x_from):x_to]
    ys, xs = np.nonzero(side)
    if len(xs) < 60:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    if x1 - x0 < 60 or y1 - y0 < 80:
        return None
    if (x1 - x0 + 1) / w < 0.08:
        return None
    pad_x = max(2, int(0.02 * w))
    pad_y = max(2, int(0.02 * frame.shape[0]))
    xa = max(0, x0 - pad_x)
    xb = min(x_to, x1 + pad_x + 1)
    crop = frame[max(0, y0 - pad_y):min(frame.shape[0], y1 + pad_y + 1), xa:xb]
    crop = _trim_ink_edge(crop, right=True)
    if x_from == 0:  # left page: its outer edge is this crop's left edge
        crop = _trim_ink_edge(crop, right=False)
    crop = _trim_dark_rows(crop)
    if crop.shape[1] < 60 or crop.shape[0] < 80:
        return None
    return crop


def _trim_ink_edge(crop: np.ndarray, right: bool) -> np.ndarray:
    """Drop right/left paper-bbox columns that are mostly ink (leaf/curl).

    Bounding boxes include what the mask connected — a curled next leaf,
    a finger over the page edge. Those show up as an outer band that is
    mostly dark. Trim inward while the outer 8%-band stays over 25% ink;
    stop at the first clean band. Never trims into the text side of a
    healthy page (its margin ink is a few percent).
    """
    if crop.shape[1] < 100:
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    band = max(4, int(0.08 * gray.shape[1]))
    while crop.shape[1] > 100:
        strip = gray[:, -band:] if right else gray[:, :band]
        if float((strip < 100).mean()) <= 0.25:
            break
        drop = max(1, band // 2)
        crop = crop[:, :-drop] if right else crop[:, drop:]
        gray = gray[:, :-drop] if right else gray[:, drop:]
    return crop


def _trim_dark_rows(crop: np.ndarray) -> np.ndarray:
    """Drop bottom rows whose band stays mostly dark (turned-leaf bundle).

    The paper bbox inherits the book's row extent, but a leaf bundle under
    the page darkens only the lower rows; the page text sits above. Only the
    bottom is trimmed — a top band that dark never hides body text in a
    held-still view. Same ink-evidence rule as the column trim.
    """
    if crop.shape[0] < 120:
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    band = max(4, int(0.08 * gray.shape[0]))
    while crop.shape[0] > 120:
        strip = gray[-band:, :]
        if float((strip < 100).mean()) <= 0.25:
            break
        drop = max(1, band // 2)
        crop = crop[:-drop, :]
        gray = gray[:-drop, :]
    return crop


def _split_view(view: np.ndarray, layout: str):
    """Reading-order split into pages, each cropped to the paper region.

    The spread decision in auto follows the detected book shape (aspect ratio
    plus a confirmed gutter); a forced layout is honoured verbatim. Pages that
    carry no paper region are dropped rather than emitted as furniture shots.
    """
    h, w = view.shape[:2]
    paper = _paper_mask(view if max(h, w) <= 1600
                        else cv2.resize(view, None, fx=.5, fy=.5))
    if paper is None or (paper > 0).mean() < 0.08:
        return _fixed_split(view, layout)
    paper = cv2.resize(paper, (w, h), interpolation=cv2.INTER_NEAREST)
    # A curled leaf or finger over a page introduces columns/rows whose paper
    # presence drops to a fraction of the bbox peak. From each outer edge
    # inward, such pixels are dropped only while the column/row carries no
    # ink: a leaf lying over live text must never cut the text, blank tails
    # (a turned-up leaf corner at the frame edge) may go. The remaining sliver
    # gets dropped wholesale by the width-ratio rule in the caller.
    gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    span = (paper > 0).mean(axis=0)
    ink_col = ((paper > 0) & (gray < 100)).sum(axis=0)
    weak = np.nonzero(span < 0.5 * float(span.max()))[0]
    for sweep in (weak, weak[::-1]):
        for x in sweep:
            if ink_col[x] > 2:
                break
            paper[:, x] = 0
    rowspan = (paper > 0).mean(axis=1)
    ink_row = ((paper > 0) & (gray < 100)).sum(axis=1)
    weak_rows = np.nonzero(rowspan < 0.5 * float(rowspan.max()))[0]
    for sweep in (weak_rows, weak_rows[::-1]):
        for y in sweep:
            if ink_row[y] > 2:
                break
            paper[y, :] = 0
    bx, by, bw, bh = cv2.boundingRect(paper)
    aspect = bw / max(1, bh)
    cut = _gutter_cut(view, paper)
    spread = layout == "spread" or (layout == "auto" and
                                    (w / h > 1.15 or (cut is not None and
                                                     aspect > 1.15)))
    if not spread:
        crop = view[max(0, by - int(0.02 * h)):min(h, by + bh + int(0.02 * h)),
                    max(0, bx - int(0.02 * w)):min(w, bx + bw + int(0.02 * w))]
        if crop.shape[0] * crop.shape[1] > 0.92 * h * w:
            return [("single", view)]
        return [("single", crop)]
    if cut is None:
        cut = bx + bw // 2  # forced spread without a visible binding
    pages = []
    for side, (x_from, x_to) in (("left", (0, cut)), ("right", (cut, w))):
        image = _side_crop(view, paper, x_from, x_to)
        if image is not None:
            pages.append((side, image))
    return pages if pages else _fixed_split(view, layout)


def extract_video_pages(path: str, out_dir: str, options: VideoOptions | None = None,
                        *, cancel: Callable[[], bool] | None = None) -> dict:
    """Stream video to disk-backed pages + provenance; retain one best view.

    Memory is bounded by the current frame and candidate, not the book length.
    Truncation and uncertain crops are reported, never implied complete.
    """
    options = options or VideoOptions()
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    pages: list[dict] = []
    warnings = ["Check page order and completeness: automatic capture can miss pages."]
    sampled = 0
    capped = False
    candidate = None
    previous = None
    previous_saved = None
    stable_since = 0.0
    last_time = 0.0

    def flush():
        nonlocal candidate, previous_saved, capped
        if candidate is None:
            return
        score, timestamp, view, _, features = candidate
        candidate = None
        if previous_saved is not None and _same_view(features, previous_saved,
                                                     _VIEW_DUPLICATE):
            return
        split = _split_view(view, options.layout)
        # A real spread's two halves have similar widths (paired halves of the
        # same book read 0.83+ on the reference footage). One normal half plus
        # one sliver is an obstruction over that page - a turning leaf or a
        # hand - which no crop can repair. Drop the sliver with an explicit
        # warning instead of exporting a torn page.
        if len(split) == 2 and split[0][0] != split[1][0]:
            wl, wr = split[0][1].shape[1], split[1][1].shape[1]
            if min(wl, wr) < 0.6 * max(wl, wr):
                narrow = split[0] if wl <= wr else split[1]
                split = [s for s in split if s is not narrow]
                warnings.append(
                    f"{narrow[0].capitalize()} side at t={timestamp:.2f}s is "
                    "mostly covered (turning leaf or hand); dropped - "
                    "re-record that page.")
        if len(pages) + len(split) > options.max_pages:
            capped = True
            return
        previous_saved = features
        for side, image in split:
            page_id = len(pages)
            name = f"capture_{page_id:04d}.jpg"
            if not cv2.imwrite(str(Path(out_dir) / name), image,
                               [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise OSError("Could not save captured page.")
            # Provenance is per page: a side that keeps the whole view
            # (no paper region found) must not claim a crop it did not do.
            page_cropped = (image.shape[0], image.shape[1]) != view.shape[:2]
            pages.append({"id": page_id, "file": name,
                          "timestamp": round(timestamp, 3), "side": side,
                          "width": image.shape[1], "height": image.shape[0],
                          "score": round(float(score), 2),
                          "cropped": page_cropped,
                          "warnings": [] if page_cropped else ["Page boundary uncertain; full frame retained."]})

    try:
        if not cap.isOpened():
            raise ValueError("Could not decode this video. Try an MP4 encoded with H.264.")
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not math.isfinite(fps) or not 0 < fps <= 240:
            raise ValueError("Video has no usable frame rate.")
        if (not math.isfinite(width * height) or width * height <= 0
                or width * height > options.max_megapixels * 1_000_000):
            raise ValueError("Video frame dimensions exceed the capture limit.")
        stride = max(1, round(fps / options.sample_fps))
        index = 0
        while True:
            _check_cancel(cancel)
            timestamp = index / fps
            if timestamp >= options.max_seconds:
                # Probe just one frame to distinguish EOF from truncation.
                capped = bool(cap.grab()) or capped
                if capped:
                    warnings.append(f"Capture stopped at the {options.max_seconds:g}-second limit.")
                break
            if not cap.grab():
                break
            if index % stride:
                index += 1
                continue
            ok, frame = cap.retrieve()
            index += 1
            if not ok or frame is None:
                raise ValueError("Video decoding failed before the end; try re-encoding the video.")
            if frame.shape[0] * frame.shape[1] > options.max_megapixels * 1_000_000:
                raise ValueError("Decoded video frame exceeds the capture limit.")
            sampled += 1
            last_time = timestamp
            view, view_cropped, alignment = _page_view(frame)
            features = _features(view)
            # Compare with the previous sample, not a fixed anchor: a hand-held
            # camera drifts, so an old anchor of the same page stops matching.
            changed = previous is None or not _same_view(features, previous)
            previous = features
            if changed:
                flush()
                if capped:
                    break
                stable_since = timestamp
            if timestamp - stable_since < options.hold_seconds:
                continue
            # Reject extremely blurred / almost uniform views. Alignment and
            # focus rank qualifying frames; there is no neural-model download.
            if features[2] < 35 or np.mean(features[1]) < .008:
                continue
            score = math.log1p(features[2]) * alignment
            if candidate is None or score > candidate[0]:
                candidate = (score, timestamp, view.copy(), view_cropped, features)
        flush()
    finally:
        cap.release()
    if not pages:
        raise ValueError("No steady readable page views found. Hold each spread still for 1–2 seconds in good light.")
    if capped and not any("second" in w for w in warnings):
        warnings.append(f"Capture reached the {options.max_pages}-page limit; the book may be incomplete.")
    manifest = {"version": 1, "options": asdict(options), "pages": pages,
                "sampled_frames": sampled, "seconds_scanned": round(last_time, 3),
                "capped": capped, "warnings": warnings}
    with open(Path(out_dir) / "capture.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def export_video_pdf(out_dir: str, pages: list[dict], *, searchable: bool = False,
                     lang: str | None = None, backend: str | None = None,
                     scale: int | None = None,
                     cancel: Callable[[], bool] | None = None) -> str:
    """Stream selected pages into one PDF, optionally using the shared OCR path.

    `searchable=True` runs the shared document pipeline per page (restore,
    deskew, OCR) and lays the invisible text over the page image; small
    captures are upscaled 2x first so OCR sees usable stroke heights.
    Per-page side artifacts (txt/md/json) are written next to the captures.
    """
    from veriscript.document.export import write_searchable_pdf_pages

    if not pages:
        raise ValueError("Select at least one page.")

    def images():
        for page in pages:
            _check_cancel(cancel)
            # Paths come from the server's capture manifest, never client text.
            image = cv2.imread(str(Path(out_dir) / page["file"]))
            if image is None:
                raise ValueError("A captured page is unavailable. Scan the video again.")
            tokens = []
            if searchable:
                from veriscript.document.pipeline import run_document_pipeline
                # Video captures are often small (a spread half from an 848px
                # frame is ~330x478) and glyph strokes land under the OCR
                # detector's floor. Upscale the *grayscale* page with Lanczos
                # before OCR — grayscale keeps JPEG chroma noise out of the
                # interpolation, and plain Lanczos (measured) beats sharpening
                # and the restoration pipeline for token count here.
                upscale = scale if scale is not None else (
                    2.5 if min(image.shape[:2]) < 700 else 1)
                if upscale != 1:
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    h, w = gray.shape[:2]
                    gray = cv2.resize(gray, (int(w * upscale), int(h * upscale)),
                                      interpolation=cv2.INTER_LANCZOS4)
                    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                result = run_document_pipeline(
                    image, lang=lang, backend=backend, deskew=True,
                    out_dir=out_dir, stem=f"capture_{page['id']:04d}_ocr",
                    make_pdf=False, make_overlay=False, make_txt=True,
                    make_md=True, make_json=True)
                image, tokens = result.display_bgr, result.ocr.tokens
            yield image, tokens, None

    target = str(Path(out_dir) / "book.pdf")
    temporary = str(Path(out_dir) / ".book.pdf")
    try:
        write_searchable_pdf_pages(temporary, images(), title="Captured book")
        _check_cancel(cancel)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return target
