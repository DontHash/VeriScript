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


def flatten(image_bgr: np.ndarray) -> np.ndarray:
    """The page flattened, same size as the input (BGR uint8)."""
    import cv2
    import torch
    import torch.nn.functional as F

    net = _load()
    h, w = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    small = cv2.resize(rgb, INPUT_SIZE, interpolation=cv2.INTER_AREA)
    with torch.no_grad():
        points, _ = net(torch.from_numpy(small.transpose(2, 0, 1)).unsqueeze(0))
        grid = F.interpolate(points, size=(h, w), mode="bilinear", align_corners=True)
        out = F.grid_sample(torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0),
                            grid.permute(0, 2, 3, 1), mode="bilinear", align_corners=True)
    flat = (out[0].numpy().transpose(1, 2, 0) * 255.0).clip(0, 255).astype(np.uint8)
    return cv2.cvtColor(flat, cv2.COLOR_RGB2BGR)


def maybe_flatten(image_bgr: np.ndarray, enabled: Optional[bool]) -> np.ndarray:
    """Flatten when asked and the model is present; otherwise unchanged."""
    if not enabled or not available():
        return image_bgr
    return flatten(image_bgr)
