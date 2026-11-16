"""Curved-page flattening with UVDoc (docs/TECH_UPGRADE_PLAN.md, F1).

UVDoc (MIT, github.com/tanguymagne/UVDoc) predicts a 45x31 grid that maps a
photographed, curved or folded page to a flat one. The grid is predicted on
a 488x712 copy and applied to the full-resolution photo, so text keeps its
pixels.

Opt-in until it passes its gate on real photos (evals/harness/eval_dewarp.py).
The model is not shipped: it is loaded from `VERISCRIPT_UVDOC` or
`data/external/uvdoc/model/best_model.pkl` (docs/EXTERNAL_ASSETS.md), always
with `torch.load(weights_only=True)`, which refuses arbitrary pickled objects.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CKPT = os.path.join(_ROOT, "data", "external", "uvdoc", "model", "best_model.pkl")
INPUT_SIZE = (488, 712)  # width, height the model was trained at

_model = None


def checkpoint_path() -> str:
    return os.environ.get("VERISCRIPT_UVDOC") or DEFAULT_CKPT


def available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return os.path.isfile(checkpoint_path())


def _load():
    global _model
    if _model is not None:
        return _model
    import torch

    ckpt_path = checkpoint_path()
    if not os.path.isfile(ckpt_path):
        raise FileNotFoundError(f"UVDoc weights not found at {ckpt_path} (see docs/EXTERNAL_ASSETS.md)")
    repo = os.path.dirname(os.path.dirname(ckpt_path))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from model import UVDocnet  # the repository's model.py imports only torch

    ckpt = torch.load(ckpt_path, weights_only=True, map_location="cpu")
    net = UVDocnet(num_filter=32, kernel_size=5)
    net.load_state_dict(ckpt["model_state"])
    net.eval()
    _model = net
    return net


def predict_grid(image_bgr: np.ndarray):
    """UVDoc's sampling grid for the page, a (1, 2, 45, 31) tensor in [-1, 1]."""
    import cv2
    import torch

    net = _load()
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    small = cv2.resize(rgb, INPUT_SIZE, interpolation=cv2.INTER_AREA)
    with torch.no_grad():
        points, _ = net(torch.from_numpy(small.transpose(2, 0, 1)).unsqueeze(0))
    return points


def page_size(points, image_hw) -> tuple[int, int]:
    """The flattened page's (height, width) in photo pixels.

    The grid's rows run across the page and its columns down it, so their
    lengths in the photo are the page's real width and height. Using them
    keeps letter shapes (a narrow receipt stretched to the photo's frame
    gets letters about twice as wide)."""
    h, w = image_hw
    g = points[0].numpy()
    xy = np.stack([(g[0] + 1) / 2 * (w - 1), (g[1] + 1) / 2 * (h - 1)], -1)  # (gh, gw, 2)
    width = np.linalg.norm(np.diff(xy, axis=1), axis=-1).sum(1).mean()
    height = np.linalg.norm(np.diff(xy, axis=0), axis=-1).sum(0).mean()
    return max(16, int(round(height)) + 1), max(16, int(round(width)) + 1)  # pixels = span + 1


def flatten(image_bgr: np.ndarray, points=None, keep_aspect: bool = False) -> np.ndarray:
    """The page flattened (BGR uint8), in the input's frame (UVDoc's
    default), or in the page's own proportions with keep_aspect=True.

    On the 128 DocUNet photos keep_aspect fixed the worst case (a narrow
    receipt: CER 0.45 -> 0.18) but was slightly worse overall (mean CER
    0.284 vs 0.269), so the frame stays the default."""
    import cv2
    import torch
    import torch.nn.functional as F

    h, w = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    if points is None:
        points = predict_grid(image_bgr)
    if keep_aspect:
        h, w = page_size(points, (h, w))
    with torch.no_grad():
        grid = F.interpolate(points, size=(h, w), mode="bilinear", align_corners=True)
        out = F.grid_sample(torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0),
                            grid.permute(0, 2, 3, 1), mode="bilinear", align_corners=True)
    flat = (out[0].numpy().transpose(1, 2, 0) * 255.0).clip(0, 255).astype(np.uint8)
    return cv2.cvtColor(flat, cv2.COLOR_RGB2BGR)


def reading_confidence(tokens) -> float:
    """Mean engine confidence of a reading, weighted by characters (0-100)."""
    chars = [(len(t.text.strip()), t.conf) for t in tokens if t.text.strip()]
    total = sum(n for n, _ in chars)
    return sum(n * c for n, c in chars) / total if total else 0.0


def pick_reading(image_bgr: np.ndarray, read):
    """Read the photo and the flattened page; keep the more confident reading.

    `read(image, write)` runs the pipeline (writing its files only when
    `write`). The photo's reading is written first; when the flattened page
    wins it is read again with its files, replacing them. On DocUNet this kept
    most of flattening's gain and almost none of its damage (1 photo with
    invented words up >2 points, vs 16 when always flattening; F1 notes)."""
    raw = read(image_bgr, True)
    flat_img = flatten(image_bgr)
    flat = read(flat_img, False)
    c_raw, c_flat = reading_confidence(raw.ocr.tokens), reading_confidence(flat.ocr.tokens)
    chosen = read(flat_img, True) if c_flat > c_raw else raw
    chosen.meta["flatten"] = {"used": c_flat > c_raw, "confidence_photo": round(c_raw, 2),
                              "confidence_flattened": round(c_flat, 2)}
    # The files were written before the choice: record it in the saved JSON too.
    path = (getattr(chosen, "outputs", None) or {}).get("json")
    if path and os.path.isfile(path):
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("meta", {})["flatten"] = chosen.meta["flatten"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return chosen


def maybe_flatten(image_bgr: np.ndarray, enabled: Optional[bool]) -> np.ndarray:
    """Flatten when asked and the model is present; otherwise unchanged."""
    if not enabled or not available():
        return image_bgr
    return flatten(image_bgr)
