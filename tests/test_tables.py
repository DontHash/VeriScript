"""
test_tables.py — tables to CSV/XLSX with uncertain cells marked
(docs/TECH_UPGRADE_PLAN.md, F2; veriscript/document/tables.py).
"""
from __future__ import annotations

import csv
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veriscript.document import tables  # noqa: E402
from veriscript.document.ocr import Token  # noqa: E402


def _grid(rows=5, cols=6, flag=(2, 3)):
    """A register-like grid: wrapped two-line cells, one flagged number."""
    toks = []
    for r in range(rows):
        for line in range(2):
            for c in range(cols):
                y = 100 + r * 100 + line * 30  # register-like row gaps
                text = f"r{r}c{c}" if line == 0 else f"२०८{r}"
                tok = Token(text=text, conf=95, bbox=(60 + c * 170, y, 160 + c * 170, y + 24))
                if (r, c) == flag and line == 1:
                    tok.flags = ["digit_conflict"]
                    tok.alt_text = "२०८९"
                toks.append(tok)
    return toks


def test_grid_becomes_rows_of_cells_with_flags():
    found = tables.extract_tables(_grid(), page=3)
    assert len(found) == 1
    t = found[0]
    assert (t.page, t.index, t.kind) == (3, 1, "grid")
    assert len(t.rows) == 5 and t.n_cols == 6
    assert t.rows[0][0].text == "r0c0 २०८0"
    cell = t.rows[2][3]
    assert cell.flagged and cell.flags == ["digit_conflict"] and cell.alt_text == "२०८९"
    assert sum(c.flagged for row in t.rows for c in row) == 1


def test_prose_and_receipts_have_no_tables():
    prose = [Token(text="a line of running text here", conf=95,
                   bbox=(60, 100 + i * 40, 900 - (i % 4) * 50, 126 + i * 40)) for i in range(20)]
    receipt = []
    for i in range(10):
        receipt.append(Token(text=f"Item {i}", conf=95, bbox=(60, 100 + i * 40, 400, 126 + i * 40)))
        receipt.append(Token(text=f"{i}0.00", conf=95, bbox=(820, 100 + i * 40, 980, 126 + i * 40)))
    assert tables.extract_tables(prose) == []
    assert tables.extract_tables(receipt) == []


def test_csv_has_a_bom_and_a_heading_per_table(tmp_path):
    found = tables.extract_tables(_grid()) + tables.extract_tables(_grid(), page=2)
    path = tables.write_csv(str(tmp_path / "t.csv"), found)
    raw = open(path, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    assert rows[0] == ["Page 1, table 1"]
    assert rows[1][0] == "r0c0 २०८0"
    assert ["Page 2, table 1"] in rows


def test_xlsx_opens_marks_flagged_cells_and_lists_them(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tables.write_xlsx(str(tmp_path / "t.xlsx"), tables.extract_tables(_grid()))
    assert zipfile.is_zipfile(path)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Page 1 table 1", "Review"]
    sheet = wb["Page 1 table 1"]
    assert sheet["A1"].value == "r0c0 २०८0"
    flagged = sheet["D3"]
    assert flagged.value == "r2c3 २०८2"
    assert flagged.fill.fgColor.rgb == "FFFFD966"
    assert sheet["A1"].fill.fill_type in (None, "none")
    review = [[c.value for c in row] for row in wb["Review"].iter_rows()]
    assert review[0][:3] == ["Sheet", "Cell", "Reading"]
    assert review[1][:5] == ["Page 1 table 1", "D3", "r2c3 २०८2", "२०८९", "digit_conflict"]


def test_no_flags_still_writes_a_review_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tables.write_xlsx(str(tmp_path / "t.xlsx"), tables.extract_tables(_grid(flag=None)))
    review = list(openpyxl.load_workbook(path)["Review"].iter_rows(values_only=True))
    assert review[1][0] == "Nothing in these tables was flagged."


def test_export_tables_skips_pages_without_tables(tmp_path):
    assert tables.export_tables(str(tmp_path), "p", []) == {}
    out = tables.export_tables(str(tmp_path), "p", tables.extract_tables(_grid()))
    assert os.path.basename(out["tables_xlsx"]) == "p_tables.xlsx"
    assert os.path.isfile(out["tables_csv"])


def test_studio_run_offers_the_spreadsheet(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
    import numpy as np
    import vvweb.pipeline as web_pipeline
    from veriscript.document import pipeline as document_pipeline
    from veriscript.document.ocr import OCRResult
    from veriscript.document.pipeline import DocumentResult
    from PIL import Image

    def fake(img, **kw):
        return DocumentResult(display_bgr=np.full((64, 64, 3), 255, np.uint8),
                              ocr=OCRResult(text="", tokens=_grid(), backend="fake"),
                              meta={"seconds": 0.1}, outputs={})

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", fake)
    img = tmp_path / "p.png"
    Image.new("RGB", (64, 64), "white").save(img)
    run = tmp_path / "run"
    run.mkdir()
    payload = web_pipeline.process_page(str(img), str(run), "0123456789abcdef", lang=None,
                                        deskew=False, kind="image")
    assert payload["meta"]["tables"] == 1
    assert payload["files"]["tables_xlsx"].endswith("/tables.xlsx")
    assert "tables_csv" in payload["files"]
