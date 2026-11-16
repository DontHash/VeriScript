"""
test_dewarp.py — curved-page flattening wrapper (docs/TECH_UPGRADE_PLAN.md, F1).

The model itself is a local download (docs/EXTERNAL_ASSETS.md); tests that
need it skip without it. The safety contract is tested either way: weights
load only through torch.load(weights_only=True), and nothing changes when
flattening is off or unavailable.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veriscript.document import dewarp  # noqa: E402


def test_off_or_missing_model_leaves_the_image_alone(monkeypatch, tmp_path):
    img = np.full((40, 30, 3), 200, np.uint8)
    assert dewarp.maybe_flatten(img, False) is img
    monkeypatch.setenv("VERISCRIPT_UVDOC", str(tmp_path / "missing.pkl"))
    assert not dewarp.available()
    assert dewarp.maybe_flatten(img, True) is img


def test_weights_load_only_in_weights_only_mode(monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    fake = tmp_path / "model" / "best_model.pkl"
    fake.parent.mkdir()
    fake.write_bytes(b"not a real checkpoint")
    (tmp_path / "model.py").write_text(
        "import torch\nclass UVDocnet(torch.nn.Module):\n"
        "    def __init__(self, **kw):\n        super().__init__()\n"
        "    def load_state_dict(self, s):\n        pass\n", encoding="utf-8")
    seen = {}

    def guarded_load(path, **kw):
        seen.update(kw)
        return {"model_state": {}}

    monkeypatch.setattr(torch, "load", guarded_load)
    monkeypatch.setattr(dewarp, "_model", None)
    monkeypatch.setenv("VERISCRIPT_UVDOC", str(fake))
    sys.modules.pop("model", None)
    dewarp._load()
    assert seen.get("weights_only") is True
    monkeypatch.setattr(dewarp, "_model", None)
    sys.modules.pop("model", None)


@pytest.mark.skipif(not dewarp.available(), reason="UVDoc weights not downloaded")
def test_flatten_keeps_size_and_content(monkeypatch):
    monkeypatch.setattr(dewarp, "_model", None)
    img = np.full((900, 640, 3), 245, np.uint8)
    img[200:260, 100:540] = 20  # a dark text-like bar
    flat = dewarp.flatten(img)
    assert flat.shape == img.shape and flat.dtype == np.uint8
    assert flat.min() < 100  # the dark bar survives


def test_pipeline_flattens_only_when_asked(monkeypatch):
    from veriscript.document import pipeline

    class Called(Exception):
        pass

    def boom(img, enabled):
        raise Called

    monkeypatch.setattr(dewarp, "maybe_flatten", boom)
    with pytest.raises(Called):
        pipeline.run_document_pipeline(np.full((40, 30, 3), 255, np.uint8), flatten=True,
                                       make_pdf=False, make_overlay=False, make_txt=False,
                                       make_json=False, make_md=False)
