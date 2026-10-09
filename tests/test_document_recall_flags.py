"""Structural recall signals (Appendix AP): `digit_list` + `separator_corrupt`.

Pure primitives: `flag_tokens(recall_flags=True)` adds the two flags; the
`ocr_page`/pipeline default resolves via `resolve_recall_flags` (None -> ON
for Devanagari). A danda between digits is a legitimate date separator in this
corpus and must never be flagged; only the pipe is a corruption signature.
"""
from veriscript.document.ocr import (RISK_WEIGHTS, Token, flag_tokens,
                                     resolve_recall_flags)


def _tok(text, flags=None):
    return Token(text=text, conf=95.0, bbox=(0, 0, 10, 10),
                 flags=list(flags or []))


def test_digit_list_flags_long_enumerations():
    long_list = _tok("१, २, ३, ४, ५, ६, ७, ८, ९")
    short = _tok("मिति २०८१-०४-२७")
    flag_tokens([long_list, short], 60.0, devanagari=True,
                recall_flags=True)
    assert "digit_list" in long_list.flags
    assert "digit_list" not in short.flags


def test_separator_corrupt_flags_pipe_between_digits():
    pipe = _tok("२०८३|०३|३०")
    pipe_spaced = _tok("२०८३ |०३|३०")
    danda = _tok("२०८१।०४।२७")  # legitimate date separator: never flagged
    flag_tokens([pipe, pipe_spaced, danda], 60.0, devanagari=True,
                recall_flags=True)
    assert "separator_corrupt" in pipe.flags
    assert "separator_corrupt" in pipe_spaced.flags
    assert "separator_corrupt" not in danda.flags


def test_recall_flags_are_an_explicit_primitive():
    tok = _tok("१, २, ३, ४, ५, ६, ७, ८")
    flag_tokens([tok], 60.0, devanagari=True)
    assert "digit_list" not in tok.flags


def test_resolve_recall_flags_policy():
    assert resolve_recall_flags(None, "ne") is True
    assert resolve_recall_flags(None, "en") is False
    assert resolve_recall_flags(False, "ne") is False
    assert resolve_recall_flags(True, "en") is True


def test_recall_flag_weights_exist():
    assert RISK_WEIGHTS["digit_list"] > 0
    assert RISK_WEIGHTS["separator_corrupt"] > 0
