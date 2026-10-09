"""
test_document_date_flags.py — impossible-date validator (Appendix AH).

A token that parses as a date with a provably impossible component (day 39,
month 13, year outside [1900, 2200]) is flagged `invalid_format` (flag-only).
Conservative by design: days 30-32 are valid in some BS months/years and are
never flagged; valid dates and non-date tokens are never flagged. Adopted ON
for Devanagari by `ocr_page` on 2026-10-09 (Appendix AN v3 re-adjudication);
`flag_tokens` keeps the explicit parameter and the `ocr_page` default resolves
via `resolve_date_flags`.
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.document.ocr import (RISK_WEIGHTS, Token,  # noqa: E402
                                     _impossible_date, flag_tokens,
                                     resolve_date_flags)


def test_impossible_date_detection():
    assert _impossible_date("मिति २०८१-०४-३९")

    assert not _impossible_date("२०८१-०४-२७")
    assert not _impossible_date("२०८१।०४।२७")
    assert not _impossible_date("२०८१/०४/२७")
    assert not _impossible_date("२०८१-४-७")
    assert not _impossible_date("कुल २०८१-०४-२७ मिति")


def test_impossible_date_boundaries():
    assert _impossible_date("२०८१-१३-०१")          # month 13
    assert _impossible_date("२०८१-०४-३९")          # day 39
    assert _impossible_date("१८५०-०१-०१")          # year out of range
    assert not _impossible_date("२०८१०४३२")        # day 32: BS months reach it
    assert not _impossible_date("२०८१०४२७")        # valid bare date
    assert _impossible_date("20810439")             # Latin digits, day 39


def test_impossible_date_ignores_non_dates():
    assert not _impossible_date("रु. १,२३,४५६.५०")
    assert not _impossible_date("०७६-W०-०९६२")
    assert not _impossible_date("को दफा ३(१), ४")
    assert not _impossible_date("")
    assert not _impossible_date("२०८१")


def test_flag_tokens_date_flags_primitive_is_explicit():
    """`flag_tokens` stays an explicit primitive: default False, True enables.

    The product default (ON for Devanagari) is resolved by `ocr_page` via
    `resolve_date_flags`; see `test_resolve_date_flags_policy`.
    """
    good = Token(text="मिति २०८१-०४-२७", conf=95.0,
                 bbox=(0, 0, 10, 10), backend="fake")
    bad = Token(text="मिति २०८१-०४-३९", conf=95.0,
                bbox=(0, 0, 10, 10), backend="fake")

    off = [Token(text=good.text, conf=95.0, bbox=good.bbox, backend="fake"),
           Token(text=bad.text, conf=95.0, bbox=bad.bbox, backend="fake")]
    flag_tokens(off, 60.0, devanagari=True)
    assert all("invalid_format" not in t.flags for t in off)

    n = flag_tokens([good, bad], 60.0, devanagari=True, date_flags=True)
    assert "invalid_format" in bad.flags
    assert "invalid_format" not in good.flags
    assert n == 1


def test_resolve_date_flags_policy():
    assert resolve_date_flags(None, "ne") is True
    assert resolve_date_flags(None, "hi") is True
    assert resolve_date_flags(None, "en") is False
    assert resolve_date_flags(None, None) is False
    assert resolve_date_flags(False, "ne") is False
    assert resolve_date_flags(True, "en") is True


def test_invalid_format_has_a_risk_weight():
    assert RISK_WEIGHTS["invalid_format"] > 0
