"""
test_fingers.py — finger cleanup for book pages (docs/TECH_UPGRADE_PLAN.md, F3).

Fingers at page edges are blanked with the paper colour; ink is never
changed; clean pages and pictures printed to the edge are left alone.
Measured on drawn fingers in evals/harness/eval_fingers.py.
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veriscript.document.fingers import clean_fingers, finger_mask  # noqa: E402


def _page():
    img = np.full((1200, 900, 3), (228, 236, 240), np.uint8)  # warm paper (BGR)
    for i in range(20):
        cv2.putText(img, "Total 12,500 ward record", (60, 120 + i * 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (30, 30, 30), 2)
    return img


def _with_finger(img, tone_bgr=(96, 134, 198)):
    out = img.copy()
    cv2.line(out, (-40, 600), (140, 620), tone_bgr, 70)  # a thumb from the left edge
    cv2.circle(out, (140, 620), 35, tone_bgr, -1)
    return out


def test_clean_page_is_untouched():
    page = _page()
    out, info = clean_fingers(page)
    assert out is page and info == {"fingers": 0, "area": 0.0}


def test_finger_is_blanked_and_ink_never_changes():
    page = _page()
    shot = _with_finger(page)
    out, info = clean_fingers(shot)
    assert info["fingers"] >= 1
    finger = np.any(shot != page, axis=2)
    changed = np.any(out != shot, axis=2)
    assert changed[finger].mean() > 0.9
    grey = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)
    assert not (changed & (grey < 120)).any()  # no dark (ink) pixel was touched
    # Filled with paper colour, not with anything that looks like content.
    fill = np.median(out[finger & changed].reshape(-1, 3), axis=0)
    assert np.abs(fill - (228, 236, 240)).max() < 15


def test_dark_skin_next_to_text_keeps_the_text():
    page = _page()
    shot = _with_finger(page, tone_bgr=(33, 50, 84))
    mask = finger_mask(shot)
    ycc = cv2.cvtColor(shot, cv2.COLOR_BGR2YCrCb).astype(int)
    neutral = np.hypot(ycc[..., 1] - 128, ycc[..., 2] - 128) < 6
    assert not (mask & neutral).any()


def test_picture_printed_to_the_edge_is_left_alone():
    page = _page()
    page[300:900, 0:300] = (60, 120, 200)  # an orange photo bleeding off the left edge
    assert not finger_mask(page).any()


def test_video_option_is_off_by_default():
    from veriscript.document.video import VideoOptions

    assert VideoOptions().clean_fingers is False
    assert VideoOptions(clean_fingers=True).clean_fingers is True
