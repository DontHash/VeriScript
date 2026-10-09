"""Unit tests for the corrected digit-content scorer (v3, PLAN Appendix AN).

Pure functions: no OCR engine involved. The behavioral contract under test:
grouping, token boundaries, separator style and reading order never create
errors; digit-content differences (substitution, transposition, extra, whole
missing atom) are detected; corrupted atoms charge their token; missing atoms
are reported without a token charge.
"""
from veriscript.core import digit_content as dc
from veriscript.document.ocr import Token


def _tok(text, y=0, flags=None):
    return Token(text=text, conf=95.0, bbox=(0, y, 100, y + 10),
                 flags=list(flags or []))


def test_grouping_and_separator_style_is_not_an_error():
    tok = _tok("मिति २०८१|०४।२७ देखि २०८१|०४|३२")
    rep = dc.content_errors([tok], "मिति २०८१-०४-२७ देखि २०८१-०४-३२")
    assert rep["error_tokens"] == []
    assert rep["missing_gt_atoms"] == []


def test_separator_style_difference_is_not_an_error():
    tok = _tok("०७६/०२५३/०४२७२")
    rep = dc.content_errors([tok], "०७६-०२५३-०४२७२")
    assert rep["error_tokens"] == []


def test_digit_substitution_is_charged():
    tok = _tok("२०८१-०४-३९")
    rep = dc.content_errors([tok], "२०८१-०४-२७")
    assert rep["error_tokens"] == [0]
    assert rep["missing_gt_atoms"] == ["27"]


def test_transposed_digits_are_charged():
    tok = _tok("९३")
    rep = dc.content_errors([tok], "३९")
    assert rep["error_tokens"] == [0]


def test_extra_run_is_charged():
    tok = _tok("३. कोभिड-१९")
    rep = dc.content_errors([tok], "कोभिड-१९")
    assert rep["error_tokens"] == [0]


def test_truncated_read_is_missing_not_charged():
    tok = _tok("०७६-WO-")
    rep = dc.content_errors([tok], "०७६-WO-०९६२")
    assert rep["error_tokens"] == []
    assert rep["missing_gt_atoms"] == ["0962"]


def test_whole_missing_number_is_reported_not_charged():
    tok = _tok("आज मिति")
    rep = dc.content_errors([tok], "आज मिति २०८१")
    assert rep["error_tokens"] == []
    assert rep["missing_gt_atoms"] == ["2081"]


def test_reading_order_divergence_is_not_an_error():
    a = _tok("ऐन, २०७६ को", y=0)
    b = _tok("दफा (२) बमोजिम", y=20)
    gt = "दफा (२) बमोजिम ऐन, २०७६ को"
    rep = dc.content_errors([a, b], gt)
    assert rep["error_tokens"] == []
    assert rep["missing_gt_atoms"] == []


def test_queue_stats_follow_review_queue():
    err = _tok("२०८१-०४-३९", y=0, flags=["digit_conflict"])
    clean = _tok("मिति २०८१-०४-२७", y=20)
    stats = dc.content_queue_stats([err, clean], "मिति २०८१-०४-२७")
    assert stats["errors"] == 1
    assert stats["recall@10"] == 1.0
