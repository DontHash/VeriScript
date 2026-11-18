"""Tables to CSV and XLSX, uncertain numbers marked (docs/TECH_UPGRADE_PLAN.md, F2).

Table regions are the ones the reading-order code already treats as grids
(`layout._grid_like`: short, column-aligned cells, >=4 columns and rows;
`layout._dense_grid_like`: one-line rows such as tables of contents), found
by the same band/column walk. Each becomes rows of cells; a cell keeps the
union of its tokens' review flags and any alternative reading.

Exports:
* CSV (UTF-8 with BOM so spreadsheet apps read Devanagari), tables one
  after another with a "Page N, table M" line before each;
* XLSX written directly (no extra dependency): one sheet per table, flagged
  cells filled amber, and a "Review" sheet listing every flagged cell with
  its alternative reading and the reasons. Text is never changed: a cell
  shows the engine's reading, exactly as the transcript does.
"""
from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from xml.sax.saxutils import escape

from veriscript.document import layout
from veriscript.document.ocr import Token

#: Flags that mark a cell for review (everything in the review queue).
REVIEW_FLAGS = None  # any flag counts; kept as a hook for narrowing later


@dataclass
class Cell:
    text: str
    flags: List[str] = field(default_factory=list)
    alt_text: Optional[str] = None

    @property
    def flagged(self) -> bool:
        return bool(self.flags)


@dataclass
class Table:
    page: int
    index: int
    kind: str  # "grid" | "dense"
    rows: List[List[Cell]]

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


def _cell(tokens: Sequence[Token]) -> Cell:
    toks = sorted(tokens, key=lambda t: (t.bbox[1], t.bbox[0]))
    flags: List[str] = []
    for t in toks:
        for f in t.flags:
            if f not in flags:
                flags.append(f)
    alts = [t.alt_text for t in toks if t.alt_text]
    return Cell(text=" ".join(t.text for t in toks if t.text),
                flags=flags, alt_text=" ".join(alts) if alts else None)


def _grid_table(tokens: Sequence[Token], med_h: float, dense: bool) -> List[List[Cell]]:
    cols = layout._grid_columns(tokens, med_h)
    col_of = {id(t): i for i, col in enumerate(cols) for t in col}
    rows = layout._y_rows(tokens, med_h) if dense else layout._grid_rows(tokens, med_h)
    rows = sorted(rows, key=lambda r: min(t.bbox[1] for t in r))
    out = []
    for row in rows:
        out.append([_cell([t for t in row if col_of[id(t)] == i]) for i in range(len(cols))])
    return out


def _walk(tokens: List[Token], depth: int, found: list) -> None:
    """The reading-order walk (columns, then bands), collecting grid regions."""
    if len(tokens) <= 1 or depth >= layout.MAX_DEPTH:
        return
    med_h = layout._median_height(tokens)
    stats = {"splits": 0}
    gutter = layout._column_split(tokens, med_h, layout.MIN_X_SIDE_TOKENS, stats)
    if gutter is not None:
        lo_mid = layout._find_gutter(tokens, med_h)
        mid = (lo_mid[0] + lo_mid[1]) / 2.0
        _walk([t for t in tokens if (t.bbox[0] + t.bbox[2]) / 2.0 < mid], depth + 1, found)
        _walk([t for t in tokens if (t.bbox[0] + t.bbox[2]) / 2.0 >= mid], depth + 1, found)
        return
    cw = layout._content_width(tokens)
    wide_ids = layout._standalone_wide_ids(tokens, cw)
    if len(wide_ids) >= 0.5 * len(tokens):
        wide_ids = set()
    bands = layout._bands(tokens, med_h, wide_ids)
    if len(bands) <= 1:
        if layout._grid_like(tokens, med_h):
            found.append(("grid", _grid_table(tokens, med_h, dense=False)))
        elif layout._dense_grid_like(tokens, med_h):
            found.append(("dense", _grid_table(tokens, med_h, dense=True)))
        return
    for band in bands:
        _walk(band, depth + 1, found)


def extract_tables(tokens: Sequence[Token], page: int = 1) -> List[Table]:
    """Tables on one page, in reading order (empty when there are none)."""
    found: list = []
    _walk(list(tokens), 0, found)
    return [Table(page=page, index=i + 1, kind=kind, rows=rows)
            for i, (kind, rows) in enumerate(found)]


# -- CSV ----------------------------------------------------------------------

def write_csv(path: str, tables: Sequence[Table]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    for n, table in enumerate(tables):
        if n:
            writer.writerow([])
        writer.writerow([f"Page {table.page}, table {table.index}"])
        for row in table.rows:
            writer.writerow([c.text for c in row])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    return path


# -- XLSX (minimal SpreadsheetML, inline strings) ----------------------------

def _col_name(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def _sheet_xml(rows: Sequence[Sequence[tuple]], widths: Sequence[int]) -> str:
    """rows of (text, style_id) cells."""
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(widths))
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, (text, style) in enumerate(row):
            ref = f"{_col_name(c)}{r}"
            s = f' s="{style}"' if style else ""
            if text == "":
                if style:
                    cells.append(f'<c r="{ref}"{s}/>')
                continue
            cells.append(f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">'
                         f"{escape(text)}</t></is></c>")
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData></worksheet>')


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFD966"/><bgColor indexed="64"/>'
    '</patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')
_FLAGGED, _BOLD = 1, 2


def write_xlsx(path: str, tables: Sequence[Table]) -> str:
    """One sheet per table (flagged cells amber) and a "Review" sheet."""
    sheets = []  # (name, xml)
    review = [[("Sheet", _BOLD), ("Cell", _BOLD), ("Reading", _BOLD),
               ("Alternative reading", _BOLD), ("Why it needs a look", _BOLD)]]
    for table in tables:
        name = f"Page {table.page} table {table.index}"[:31]
        rows = []
        widths = [10] * table.n_cols
        for r, row in enumerate(table.rows, start=1):
            out = []
            for c, cell in enumerate(row):
                widths[c] = min(60, max(widths[c], len(cell.text) + 2))
                out.append((cell.text, _FLAGGED if cell.flagged else 0))
                if cell.flagged:
                    review.append([(name, 0), (f"{_col_name(c)}{r}", 0), (cell.text, 0),
                                   (cell.alt_text or "", 0), (", ".join(cell.flags), 0)])
            rows.append(out)
        sheets.append((name, _sheet_xml(rows, widths)))
    if len(review) == 1:
        review.append([("Nothing in these tables was flagged.", 0)])
    sheets.append(("Review", _sheet_xml(review, [22, 8, 30, 30, 40])))

    ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                f'xmlns:r="{ns}"><sheets>'
                + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                          for i, (n, _x) in enumerate(sheets))
                + "</sheets></workbook>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i + 1}" Type="{ns}/worksheet" '
                      f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{ns}/styles" Target="styles.xml"/>'
            "</Relationships>")
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
             + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                       'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                       for i in range(len(sheets)))
             + "</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 f'<Relationship Id="rId1" Type="{ns}/officeDocument" Target="xl/workbook.xml"/>'
                 "</Relationships>")
    part = path + ".part"
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/styles.xml", _STYLES)
        for i, (_n, xml) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", xml)
    os.replace(part, path)
    return path


def export_tables(out_dir: str, stem: str, tables: Sequence[Table]) -> dict:
    """`<stem>_tables.csv` and `.xlsx` when there is at least one table."""
    if not tables:
        return {}
    os.makedirs(out_dir, exist_ok=True)
    return {"tables_csv": write_csv(os.path.join(out_dir, f"{stem}_tables.csv"), tables),
            "tables_xlsx": write_xlsx(os.path.join(out_dir, f"{stem}_tables.xlsx"), tables)}
