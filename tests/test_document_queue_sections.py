"""Digit-first review queue sections (Appendix AO).

Contract: the number/text sections partition the generic review queue (no
token dropped, no duplicates), the number section keeps the risk ranking,
and the export surfaces (ocr.json, Markdown) show numbers first with their
section labelled.
"""
from __future__ import annotations

import json
import os
import tempfile

from veriscript.document.export import transcript_md_text, write_ocr_json
from veriscript.document.ocr import (OCRResult, Token, digit_review_queue,
                                     review_queue, review_queue_sections,
                                     text_review_queue)


def _tok(text, y=0, flags=None, conf=95.0):
    return Token(text=text, conf=conf, bbox=(0, y, 100, y + 10),
                 flags=list(flags or []))


def test_sections_partition_the_queue():
    digit = _tok("१२००", y=0, flags=["digit_conflict"])
    word = _tok("शब्द", y=20, flags=["unknown_word"])
    clean = _tok("सफा", y=40)
    secs = review_queue_sections([digit, word, clean])
    assert secs["number"] == [digit]
    assert secs["text"] == [word]
    assert [id(t) for t in secs["number"] + secs["text"]] == \
        [id(t) for t in review_queue([digit, word, clean])]


def test_digit_queue_keeps_risk_order():
    a = _tok("९", y=0, flags=["digit_uncertain"])
    b = _tok("१", y=20, flags=["digit_conflict"])
    assert digit_review_queue([a, b])[0] is b
    assert text_review_queue([a, b]) == []


def test_export_json_sections_numbers_first():
    digit = _tok("१२००", y=0, flags=["digit_conflict"])
    word = _tok("शब्द", y=20, flags=["unknown_word"], conf=70.0)
    res = OCRResult(text="x", tokens=[digit, word, _tok("सफा", y=40)],
                    backend="fake")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ocr.json")
        write_ocr_json(path, res)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    assert payload["review_sections"] == {"number": 1, "text": 1}
    assert [row["section"] for row in payload["review"]] == \
        ["number", "text"]
    assert payload["review"][0]["text"] == "१२००"


def test_markdown_has_section_headings():
    digit = _tok("१२००", y=0, flags=["digit_conflict"])
    word = _tok("शब्द", y=20, flags=["unknown_word"])
    res = OCRResult(text="x", tokens=[digit, word], backend="fake")
    md = transcript_md_text(res)
    assert "## Review queue" in md
    assert "### Numbers" in md
    assert "### Text" in md
