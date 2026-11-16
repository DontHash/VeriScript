"""Curved-page flattening with UVDoc (docs/TECH_UPGRADE_PLAN.md, F1).

UVDoc (MIT, github.com/tanguymagne/UVDoc) predicts a 45x31 grid that maps a
photographed, curved or folded page to a flat one. The grid is predicted on
a 488x712 copy and applied to the full-resolution photo, so text keeps its
pixels.

Opt-in until it passes its gate on real photos (evals/harness/eval_dewarp.py).
Two ways to run the same model, the first available wins:

* ONNX (`VERISCRIPT_UVDOC_ONNX` or `data/external/uvdoc/model/uvdoc.onnx`,
  made by scripts/export_uvdoc_onnx.py; grid within 0.002 px of PyTorch at
  2000 px). Needs only onnxruntime, which the studio and the phone already
  ship, so flattening works in the desktop studio without PyTorch.
* PyTorch: `VERISCRIPT_UVDOC` or `data/external/uvdoc/model/best_model.pkl`
  (docs/EXTERNAL_ASSETS.md), always with `torch.load(weights_only=True)`,
  which refuses arbitrary pickled objects.

The grid is applied with OpenCV (`cv2.remap`, bilinear, the same sampling
as torch's grid_sample with align_corners=True).
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CKPT = os.path.join(_ROOT, "data", "external", "uvdoc", "model", "best_model.pkl")
DEFAULT_ONNX = os.path.join(_ROOT, "data", "external", "uvdoc", "model", "uvdoc.onnx")
INPUT_SIZE = (488, 712)  # width, height the model was trained at

_model = None
_session = None


def checkpoint_path() -> str:
    return os.environ.get("VERISCRIPT_UVDOC") or DEFAULT_CKPT


def onnx_path() -> str:
    """The ONNX model: the environment, next to a frozen app, or the repo."""
    env = os.environ.get("VERISCRIPT_UVDOC_ONNX")
    if env:
        return env
    frozen = os.path.join(getattr(sys, "_MEIPASS", ""), "uvdoc", "uvdoc.onnx")
    return frozen if getattr(sys, "frozen", False) and os.path.isfile(frozen) else DEFAULT_ONNX


def _onnx_ok() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return os.path.isfile(onnx_path())


def available() -> bool:
    if _onnx_ok():
        return True
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


def _onnx():
    global _session
    if _session is None:
        import onnxruntime as ort

        _session = ort.InferenceSession(onnx_path(), providers=["CPUExecutionProvider"])
    return _session


def predict_grid(image_bgr: np.ndarray) -> np.ndarray:
    """UVDoc's sampling grid for the page, a (1, 2, 45, 31) array in [-1, 1]."""
    import cv2

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    small = cv2.resize(rgb, INPUT_SIZE, interpolation=cv2.INTER_AREA)
    x = np.ascontiguousarray(small.transpose(2, 0, 1)[None])
    if _onnx_ok():
        return _onnx().run(None, {"image": x})[0]
    import torch

    net = _load()
    with torch.no_grad():
        points, _ = net(torch.from_numpy(x))
    return points.numpy()


def page_size(points, image_hw) -> tuple[int, int]:
    """The flattened page's (height, width) in photo pixels.

    The grid's rows run across the page and its columns down it, so their
    lengths in the photo are the page's real width and height. Using them
    keeps letter shapes (a narrow receipt stretched to the photo's frame
    gets letters about twice as wide)."""
    h, w = image_hw
    g = np.asarray(points)[0]
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

    src_h, src_w = image_bgr.shape[:2]
    h, w = src_h, src_w
    if points is None:
        points = predict_grid(image_bgr)
    if keep_aspect:
        h, w = page_size(points, (h, w))
    return apply_grid(image_bgr, np.asarray(points)[0], (h, w))


def apply_grid(image_bgr: np.ndarray, grid: np.ndarray, out_hw) -> np.ndarray:
    """Sample `image_bgr` through `grid` (2, gh, gw) in [-1, 1].

    Same as torch's interpolate(bilinear) + grid_sample(bilinear), both with
    align_corners=True: the small grid is stretched corner to corner over
    the output, then each output pixel reads the photo at that point."""
    import cv2

    h, w = out_hw
    src_h, src_w = image_bgr.shape[:2]
    gh, gw = grid.shape[1:]
    # align_corners=True: output pixel i sits at grid position i*(g-1)/(n-1).
    # Exact bilinear weights (cv2.remap's 1/32-pixel fixed point is fine on
    # the photo but would move points by about 2 px when stretching the
    # 45x31 grid over a 2000 px page).
    def weights(n: int, g: int) -> np.ndarray:
        pos = np.arange(n, dtype=np.float64) * ((g - 1) / max(1, n - 1))
        lo = np.minimum(np.floor(pos).astype(int), g - 2)
        frac = pos - lo
        m = np.zeros((n, g))
        m[np.arange(n), lo] = 1 - frac
        m[np.arange(n), lo + 1] = frac
        return m

    ry, rx = weights(h, gh), weights(w, gw)
    gx = (ry @ grid[0].astype(np.float64) @ rx.T).astype(np.float32)
    gy = (ry @ grid[1].astype(np.float64) @ rx.T).astype(np.float32)
    map_x = (gx + 1) / 2 * (src_w - 1)
    map_y = (gy + 1) / 2 * (src_h - 1)
    return cv2.remap(image_bgr, map_x, map_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))


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
