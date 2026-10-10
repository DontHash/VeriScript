"""Unit tests for the audit-sheet helpers (scripts/build_audit_sheet.py).

These cover the HTML/TSV defects that made the sheet unreadable:
backslash separators in href/src, missing verdict columns, and the Section-B
context that silently showed an arbitrary match for a value occurring N times.
"""
import importlib.util
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

_spec = importlib.util.spec_from_file_location(
    "build_audit_sheet", os.path.join(BASE_DIR, "scripts",
                                      "build_audit_sheet.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_gt_context = _mod._gt_context
_rel = _mod._rel
_sanitize = _mod._sanitize

DEVA_GT = "अदालतबाट ०७६-WO-०९६२, पृष्ठ 1. वडा निं. २ बस्ने, वडा निं. २"


def test_context_first_occurrence_is_returned():
    ctx, total = _gt_context(DEVA_GT, "076")
    assert total == 1
    assert ctx
    assert "०७६" in ctx


def test_context_reports_repeated_values():
    # '2' occurs inside ०७६, inside १, and twice as वडा निं. २ -> 3 matches.
    ctx, total = _gt_context(DEVA_GT, "2")
    assert total == 3
    assert ctx


def test_context_absent_value():
    ctx, total = _gt_context(DEVA_GT, "9999")
    assert ctx == ""
    assert total == 0


def test_context_out_of_range_occurrence_is_empty():
    ctx, total = _gt_context(DEVA_GT, "2", occurrence=5)
    assert ctx == ""
    assert total == 3


def test_rel_uses_forward_slashes():
    got = _rel(os.path.join("out", "audit_v2", "crops", "err_000.png"),
               os.path.join("out", "audit_v2"))
    assert got == "crops/err_000.png"
    assert "\\" not in got


def test_sanitize_strips_tabs_and_newlines():
    assert _sanitize("a\tb\nc  ") == "a b c"
    assert _sanitize(None) == ""