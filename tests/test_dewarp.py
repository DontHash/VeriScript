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
def test_flatten_keeps_content(monkeypatch):
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
        pipeline.run_document_pipeline(np.full((40, 30, 3), 255, np.uint8), flatten="always",
                                       make_pdf=False, make_overlay=False, make_txt=False,
                                       make_json=False, make_md=False)


def _grid(gh=45, gw=31, x0=-1.0, x1=1.0, y0=-1.0, y1=1.0):
    torch = pytest.importorskip("torch")
    ys, xs = np.meshgrid(np.linspace(y0, y1, gh), np.linspace(x0, x1, gw), indexing="ij")
    return torch.from_numpy(np.stack([xs, ys])[None].astype(np.float32))


def test_page_size_follows_the_page_not_the_photo():
    # Grid covering the whole photo: the page is the photo.
    assert dewarp.page_size(_grid(), (1000, 600)) == (1000, 600)
    # A narrow receipt in the middle half of a wide photo stays narrow.
    h, w = dewarp.page_size(_grid(x0=-0.5, x1=0.5), (1000, 1200))
    assert (h, abs(w - 600) <= 1) == (1000, True)


def test_flatten_with_an_identity_grid_keeps_the_page(monkeypatch):
    pytest.importorskip("torch")
    img = np.zeros((90, 60, 3), np.uint8)
    img[30:40, 10:50] = 255
    for keep_aspect in (False, True):
        out = dewarp.flatten(img, points=_grid(), keep_aspect=keep_aspect)
        assert out.shape == img.shape
        assert np.abs(out.astype(int) - img).max() <= 1


def test_reading_confidence_weights_by_characters():
    from veriscript.document.ocr import Token

    toks = [Token("abcdefgh", 90, (0, 0, 1, 1)), Token("x", 10, (0, 0, 1, 1)), Token("  ", 0, (0, 0, 1, 1))]
    assert dewarp.reading_confidence(toks) == pytest.approx((8 * 90 + 10) / 9)
    assert dewarp.reading_confidence([]) == 0.0


class _Read:
    """A fake pipeline: confidence depends on which image it is given."""

    def __init__(self, conf_photo, conf_flat):
        self.conf = {0: conf_photo, 1: conf_flat}
        self.calls = []

    def __call__(self, image, write):
        from types import SimpleNamespace

        from veriscript.document.ocr import Token

        which = int(image[0, 0, 0])
        self.calls.append((which, write))
        return SimpleNamespace(meta={}, which=which,
                               ocr=SimpleNamespace(tokens=[Token("word", self.conf[which], (0, 0, 1, 1))]))


@pytest.mark.parametrize("photo, flat, expect_flat, calls", [
    (80, 90, True, [(0, True), (1, False), (1, True)]),   # flattened wins: rewritten with its files
    (90, 80, False, [(0, True), (1, False)]),             # photo wins: its files stay
    (85, 85, False, [(0, True), (1, False)]),             # a tie keeps the photo
])
def test_pick_keeps_the_more_confident_reading(monkeypatch, photo, flat, expect_flat, calls):
    monkeypatch.setattr(dewarp, "flatten", lambda img: np.ones_like(img))
    read = _Read(photo, flat)
    res = dewarp.pick_reading(np.zeros((4, 4, 3), np.uint8), read)
    assert res.which == int(expect_flat) and read.calls == calls
    assert res.meta["flatten"] == {"used": expect_flat, "confidence_photo": photo,
                                   "confidence_flattened": flat}


def test_pick_mode_without_the_model_reads_the_photo_once(monkeypatch):
    from veriscript.document import pipeline

    monkeypatch.setenv("VERISCRIPT_UVDOC", "missing.pkl")
    monkeypatch.setattr(dewarp, "pick_reading", lambda *a: pytest.fail("needs the model"))
    res = pipeline.run_document_pipeline(np.full((60, 60, 3), 255, np.uint8), flatten="pick",
                                         make_pdf=False, make_overlay=False, make_txt=False,
                                         make_json=False, make_md=False)
    assert "flatten" not in res.meta
