"""Paired OCR comparison: identical image bytes, explicit GT authority, no missing-output wins.

python -m evals.harness.compare_apps prepare
python -m evals.harness.compare_apps prepare-camera --pack build/ocr-comparison/camera
python -m evals.harness.compare_apps desktop
python -m evals.harness.compare_apps score
Place competitor TXT exports at <pack>/outputs/<engine>/<page-id>.txt.
Only public/generated pages belong in this pack; no personal documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

from veriscript.core.metrics import cer, wer, cer_bag, digit_string

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACK = ROOT / "build/ocr-comparison/pack"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draw_shaped(image, line, font_path, size, x, baseline):
    """Shape Indic clusters before rasterization, including on Windows Pillow."""
    import freetype
    import uharfbuzz as hb
    face = freetype.Face(str(font_path))
    face.set_char_size(size * 64)
    font = hb.Font(hb.Face(font_path.read_bytes()))
    font.scale = (size * 64, size * 64)
    hb.ot_font_set_funcs(font)
    buffer = hb.Buffer()
    buffer.add_str(line)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    cursor_x, cursor_y = x * 64, baseline * 64
    for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions):
        face.load_glyph(info.codepoint, freetype.FT_LOAD_RENDER)
        glyph, bitmap = face.glyph, face.glyph.bitmap
        if bitmap.width and bitmap.rows:
            mask = Image.frombytes('L', (bitmap.width, bitmap.rows), bytes(bitmap.buffer),
                                   'raw', 'L', bitmap.pitch)
            image.paste('black', (round((cursor_x + pos.x_offset) / 64) + glyph.bitmap_left,
                                 round((cursor_y - pos.y_offset) / 64) - glyph.bitmap_top), mask)
        cursor_x += pos.x_advance
        cursor_y -= pos.y_advance


def prepare(pack: Path) -> None:
    if (pack / "manifest.json").exists():
        raise SystemExit("Pack already exists. Reuse it or select a new --pack directory.")
    (pack / "pages").mkdir(parents=True, exist_ok=True)
    (pack / "gt").mkdir(exist_ok=True)
    font_path = ROOT / "mobile/assets/Mukta-Regular.ttf"
    font = ImageFont.truetype(str(font_path), 42)
    if not features.check_feature('raqm'):
        # Fail before making fixtures rather than silently drawing broken Indic text.
        try:
            import freetype, uharfbuzz  # noqa: F401
        except ImportError as error:
            raise RuntimeError('Install evals/requirements-comparison.txt for shaped Nepali fixtures') from error
    nepali = [
        "नेपाल सरकार", "शिक्षा, विज्ञान तथा प्रविधि मन्त्रालय",
        "विद्यार्थीको नाम: सरिता शर्मा", "विद्यालयको नाम: जनसेवा माध्यमिक विद्यालय",
        "आजको मिति: २०८३/०७/०१", "जम्मा विद्यार्थी संख्या: १२३४५",
        "पुस्तक पढ्ने बानीले ज्ञान र सीप बढाउँछ।", "हामी सबै मिलेर आफ्नो गाउँ सफा राखौँ।",
        "सम्पर्क नम्बर: ९८४१२३४५६७", "कुल रकम: रु. १२,५००.७५",
    ]
    english = [
        "VERISCRIPT TEST INVOICE", "Customer: Sarita Sharma", "Invoice: 12345",
        "Date: 2026/10/17", "Books: 12 x 250.00", "Total: Rs. 3,000.00",
        "Reference: 9841234567", "Please check the amount before payment.",
    ]
    entries = []

    def save(page_id, image, text, lang, family, authority, source):
        path = pack / "pages" / f"{page_id}.png"
        image.save(path)
        gt = pack / "gt" / f"{page_id}.txt"
        gt.write_text(text, encoding="utf-8")
        entries.append(dict(id=page_id, image=f"pages/{page_id}.png", gt=f"gt/{page_id}.txt",
                            sha256=digest(path), gt_sha256=digest(gt), lang=lang,
                            family=family, authority=authority, source=source,
                            width=image.width, height=image.height))

    for lang, lines in [("ne", nepali), ("en", english)]:
        im = Image.new("RGB", (1500, 1800), "white")
        draw = ImageDraw.Draw(im)
        for i, line in enumerate(lines):
            if lang == 'ne' and not features.check_feature('raqm'):
                draw_shaped(im, line, font_path, 42, 90, 130 + i * 105)
            else:
                draw.text((90, 90 + i * 105), line, font=font, fill="black")
        save(f"{lang}_clean", im, "\n".join(lines), lang, "synthetic",
             "exact-rendered-text", "Generated with bundled Mukta OFL font")
        if lang == "ne":
            a = np.asarray(im).astype(float)
            shadow = np.linspace(.45, 1, im.width)[None, :, None]
            a = cv2.GaussianBlur(np.uint8(a * shadow), (3, 3), .7)
            save("ne_shadow", Image.fromarray(a), "\n".join(lines), lang, "synthetic",
                 "exact-rendered-text", "Deterministic shadow/blur of ne_clean")
        else:
            save("en_rotated", im.rotate(90, expand=True), "\n".join(lines), lang,
                 "synthetic", "exact-rendered-text", "90-degree rotation of en_clean")

    # Frozen by book before looking at outputs. No training-book pages in this smoke pack.
    base = ROOT / "data/doc_eval/heidata_holdout"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest.get("entries", []) if isinstance(manifest, dict) else manifest
    for book in ["saktidharasukla1930", "simha1914"]:
        row = next(r for r in rows if r.get("book") == book and r.get("gt_chars", 0) >= 400)
        im = Image.open(base / row["degraded"]).convert("RGB")
        im.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
        save(row["id"], im, (base / row["gt"]).read_text(encoding="utf-8"), "ne",
             "historical-hindi", "upstream-human-corrected-ALTO",
             "heiDATA doi:10.11588/data/EGOKEI; CC BY 4.0; held-out book")
    (pack / "manifest.json").write_text(json.dumps(dict(version=1, entries=entries),
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(entries)} pages at {pack}", flush=True)


CAMERA_NEPALI = [
    "नेपाल सरकार", "शिक्षा, विज्ञान तथा प्रविधि मन्त्रालय",
    "विद्यार्थीको नाम: सरिता शर्मा", "विद्यालयको नाम: जनसेवा माध्यमिक विद्यालय",
    "आजको मिति: २०८३/०७/०१", "जम्मा विद्यार्थी संख्या: १२३४५",
    "पुस्तक पढ्ने बानीले ज्ञान र सीप बढाउँछ।", "हामी सबै मिलेर आफ्नो गाउँ सफा राखौँ।",
    "सम्पर्क नम्बर: ९८४१२३४५६७", "कुल रकम: रु. १२,५००.७५",
    "कित्ता नम्बर: ४४७१ क्षेत्रफल: ०-३-२-१", "वडा नम्बर: ७ टोल: शान्तिनगर",
    "दर्ता मिति: २०८२/११/२९ दर्ता नम्बर: ५६०८", "बैंक खाता: ०१२३४५६७८९०१",
    "यो प्रमाणपत्र तीन वर्षसम्म मान्य हुनेछ।", "आवेदकको सही र औंठाछाप तल राख्नुहोस्।",
]
CAMERA_ENGLISH = [
    "VERISCRIPT TEST INVOICE", "Customer: Sarita Sharma", "Invoice: 12345",
    "Date: 2026/10/17", "Books: 12 x 250.00", "Total: Rs. 3,000.00",
    "Reference: 9841234567", "Please check the amount before payment.",
    "Plot number: 4471 Area: 0-3-2-1", "Ward: 7 Street: Shantinagar",
    "Registered: 2026/03/13 No. 5608", "Account: 0123456789012",
    "This certificate is valid for three years.", "Sign below and keep a copy.",
    "Delivery charge: Rs. 145.50", "Balance due: Rs. 2,854.50",
]


def prepare_camera(pack: Path) -> None:
    """12 MP 'phone photo' proxies of an A4 page (docs/TECH_UPGRADE_PLAN.md C1/D1).

    A white A4 page fills ~88% of a 3024x4032 frame on a grey desk, with
    7-8 pt text, mild optical blur and sensor noise, saved as JPEG like a
    camera would. Rotated copies record the rotation the app must apply
    (`expected_rotation`, clockwise degrees). Synthetic: these test
    resolution handling and orientation, not real-photo accuracy.
    """
    if (pack / "manifest.json").exists():
        raise SystemExit("Pack already exists. Reuse it or select a new --pack directory.")
    (pack / "pages").mkdir(parents=True, exist_ok=True)
    (pack / "gt").mkdir(exist_ok=True)
    font_path = ROOT / "mobile/assets/Mukta-Regular.ttf"
    rng = np.random.default_rng(20261115)
    entries = []
    frame_w, frame_h = 3024, 4032
    page_h = int(frame_h * 0.88)
    page_w = int(page_h * 210 / 297)
    px_per_mm = page_h / 297.0

    def render(lines, lang, points, soft):
        size = round(points * 0.3528 * px_per_mm)  # em size in pixels
        page = Image.new("RGB", (page_w, page_h), "white")
        margin = int(20 * px_per_mm)
        step = int(size * 1.9)
        draw = ImageDraw.Draw(page)
        font = ImageFont.truetype(str(font_path), size)
        for i, line in enumerate(lines):
            if lang == "ne" and not features.check_feature("raqm"):
                draw_shaped(page, line, font_path, size, margin, margin + size + i * step)
            else:
                draw.text((margin, margin + i * step), line, font=font, fill="black")
        frame = Image.new("RGB", (frame_w, frame_h), (118, 112, 104))
        frame.paste(page, ((frame_w - page_w) // 2, (frame_h - page_h) // 2))
        a = np.asarray(frame).astype(np.float32)
        a = cv2.GaussianBlur(a, (0, 0), 1.3 if soft else 0.9)
        if soft:  # uneven light across the page
            a *= np.linspace(0.78, 1.0, frame_w, dtype=np.float32)[None, :, None]
        a += rng.normal(0, 4.0 if soft else 2.5, a.shape).astype(np.float32)
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    def save(page_id, image, text, lang, source, rotation=0):
        path = pack / "pages" / f"{page_id}.jpg"
        image.save(path, quality=92)
        gt = pack / "gt" / f"{page_id}.txt"
        gt.write_text(text, encoding="utf-8")
        entries.append(dict(id=page_id, image=f"pages/{page_id}.jpg", gt=f"gt/{page_id}.txt",
                            sha256=digest(path), gt_sha256=digest(gt), lang=lang,
                            family="camera-proxy", authority="exact-rendered-text",
                            source=source, width=image.width, height=image.height,
                            expected_rotation=rotation))

    for lang, lines in [("ne", CAMERA_NEPALI), ("en", CAMERA_ENGLISH)]:
        text = "\n".join(lines)
        base = render(lines, lang, 8, soft=False)
        save(f"cam_{lang}_8pt", base, text, lang, "12 MP frame, 8 pt, mild blur/noise")
        save(f"cam_{lang}_7pt_soft", render(lines, lang, 7, soft=True), text, lang,
             "12 MP frame, 7 pt, more blur/noise, uneven light")
        # PIL rotates counter-clockwise; the app must turn it back clockwise.
        for ccw in (90, 180, 270):
            save(f"cam_{lang}_8pt_r{ccw}", base.rotate(ccw, expand=True), text, lang,
                 f"cam_{lang}_8pt rotated {ccw} degrees counter-clockwise", rotation=ccw)
    (pack / "manifest.json").write_text(json.dumps(dict(version=1, entries=entries),
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(entries)} camera-proxy pages at {pack}", flush=True)


def prepare_columns(pack: Path) -> None:
    """Two-column 12 MP page proxies (docs/TECH_UPGRADE_PLAN.md D4).

    Same frame and degradations as `prepare_camera`, but the text sits in two
    columns; the ground truth is the left column, then the right column (how
    a person reads it). Synthetic: tests reading order, not photo accuracy.
    """
    if (pack / "manifest.json").exists():
        raise SystemExit("Pack already exists. Reuse it or select a new --pack directory.")
    (pack / "pages").mkdir(parents=True, exist_ok=True)
    (pack / "gt").mkdir(exist_ok=True)
    font_path = ROOT / "mobile/assets/Mukta-Regular.ttf"
    rng = np.random.default_rng(20261116)
    frame_w, frame_h = 3024, 4032
    page_h = int(frame_h * 0.88)
    page_w = int(page_h * 210 / 297)
    px_per_mm = page_h / 297.0
    entries = []
    for lang, lines in [("en", CAMERA_ENGLISH), ("ne", CAMERA_NEPALI)]:
        size = round(8 * 0.3528 * px_per_mm)
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        font = ImageFont.truetype(str(font_path), size)
        margin, gutter = int(15 * px_per_mm), int(10 * px_per_mm)
        col_w = (page_w - 2 * margin - gutter) // 2
        step = int(size * 1.9)
        # Each column holds the 16 lines, split at word boundaries to fit.
        columns = [[], []]
        for c, chunk in enumerate((lines[:8], lines[8:])):
            for line in chunk:
                words, cur = line.split(), ""
                for w in words:
                    trial = f"{cur} {w}".strip()
                    if draw.textlength(trial, font=font) > col_w and cur:
                        columns[c].append(cur)
                        cur = w
                    else:
                        cur = trial
                if cur:
                    columns[c].append(cur)
        for c, col in enumerate(columns):
            x = margin + c * (col_w + gutter)
            for i, line in enumerate(col):
                if lang == "ne" and not features.check_feature("raqm"):
                    draw_shaped(page, line, font_path, size, x, margin + size + i * step)
                else:
                    draw.text((x, margin + i * step), line, font=font, fill="black")
        frame = Image.new("RGB", (frame_w, frame_h), (118, 112, 104))
        frame.paste(page, ((frame_w - page_w) // 2, (frame_h - page_h) // 2))
        a = cv2.GaussianBlur(np.asarray(frame).astype(np.float32), (0, 0), 0.9)
        a += rng.normal(0, 2.5, a.shape).astype(np.float32)
        image = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        page_id = f"cols_{lang}_8pt"
        path = pack / "pages" / f"{page_id}.jpg"
        image.save(path, quality=92)
        gt = pack / "gt" / f"{page_id}.txt"
        gt.write_text("\n".join(columns[0] + columns[1]), encoding="utf-8")
        entries.append(dict(id=page_id, image=f"pages/{page_id}.jpg", gt=f"gt/{page_id}.txt",
                            sha256=digest(path), gt_sha256=digest(gt), lang=lang,
                            family="camera-proxy-columns", authority="exact-rendered-text",
                            source="12 MP frame, two columns, 8 pt", width=image.width,
                            height=image.height, expected_rotation=0, **{"import": True}))
    (pack / "manifest.json").write_text(json.dumps(dict(version=1, entries=entries),
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(entries)} two-column pages at {pack}", flush=True)


def entries(pack):
    rows = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))["entries"]
    for row in rows:
        for key, hash_key in [("image", "sha256"), ("gt", "gt_sha256")]:
            if digest(pack / row[key]) != row[hash_key]:
                raise ValueError(f"Changed {key}: {row['id']}")
    return rows


def desktop(pack, modes=None):
    from veriscript.document.ocr import get_backend
    from veriscript.document.pipeline import run_document_pipeline
    backend = get_backend("rapidocr")
    # Avoid oversubscribing the host while an Android emulator is running.
    modes = modes or ["desktop_raw", "desktop_pipeline", "desktop_deva_auto"]
    if "desktop_deva_auto" in modes:
        import torch
        torch.set_num_threads(2)
    base_params = backend._base_params
    backend._base_params = lambda: {**base_params(),
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1}
    for mode in modes:
        out = pack / "outputs" / mode
        out.mkdir(parents=True, exist_ok=True)
        for row in entries(pack):
            saved = out / f"{row['id']}.json"
            if saved.exists() and (out / f"{row['id']}.txt").exists():
                if json.loads(saved.read_text(encoding="utf-8")).get("image_sha256") == row["sha256"]:
                    continue
            image = cv2.imdecode(np.fromfile(pack / row["image"], dtype=np.uint8), cv2.IMREAD_COLOR)
            start = time.perf_counter()
            if mode == "desktop_raw":
                result = backend.run(image, lang=row["lang"])
                meta = result.meta
            else:
                page = run_document_pipeline(image, lang=row["lang"], backend="rapidocr",
                                             deva_lines="auto" if mode.endswith("auto") else "off",
                                             make_pdf=False)
                result, meta = page.ocr, page.meta
            seconds = time.perf_counter() - start
            (out / f"{row['id']}.txt").write_text(result.text, encoding="utf-8")
            (out / f"{row['id']}.json").write_text(json.dumps(dict(
                seconds=seconds, meta=meta, image_sha256=row["sha256"],
                tokens=[dict(text=t.text, confidence=t.conf, bbox=t.bbox, flags=t.flags)
                        for t in result.tokens]), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(mode, row["id"], f"{seconds:.2f}s", flush=True)


def score(pack):
    rows = entries(pack)
    report = {"pages": len(rows), "engines": {}, "limitations": [
        "Six-page smoke comparison, not representative market validation.",
        "Synthetic Nepali is not a real camera corpus; historical pages are Hindi, not Nepali.",
        "Missing outputs are unmeasured; only complete engines have aggregate scores.",
        "Emulator and desktop latency are not comparable hardware benchmarks."]}
    for out in sorted((pack / "outputs").glob('*')):
        if not out.is_dir(): continue
        scores, missing = [], []
        for row in rows:
            path = out / f"{row['id']}.txt"
            provenance = out / f"{row['id']}.json"
            if not path.exists() or not provenance.exists():
                missing.append(row["id"])
                continue
            if json.loads(provenance.read_text(encoding="utf-8")).get("image_sha256") != row["sha256"]:
                raise ValueError(f"Output uses a different image: {out.name}/{row['id']}")
            gt, hyp = (pack / row["gt"]).read_text(encoding="utf-8"), path.read_text(encoding="utf-8")
            gtd, hypd = digit_string(gt), digit_string(hyp)
            meta = json.loads(provenance.read_text(encoding="utf-8"))
            item = dict(id=row["id"], family=row["family"], cer=cer(gt, hyp),
                        wer=wer(gt, hyp), bag_cer=cer_bag(gt, hyp),
                        digit_cer=cer(gtd, hypd) if gtd else None,
                        digit_exact=gtd == hypd if gtd else None,
                        seconds=meta.get("seconds"))
            if "expected_rotation" in row and "rotation" in meta:
                item["rotation_ok"] = (meta["rotation"] % 360) == row["expected_rotation"]
            scores.append(item)
        value = dict(status="complete" if not missing else "incomplete", missing=missing, pages=scores)
        if not missing:
            value["mean_cer"] = float(np.mean([s["cer"] for s in scores]))
            value["by_family"] = {family: float(np.mean([s["cer"] for s in scores if s["family"] == family]))
                                  for family in sorted({s["family"] for s in scores})}
            seconds = [s["seconds"] for s in scores if s["seconds"] is not None]
            if seconds:
                value["mean_seconds"] = float(np.mean(seconds))
            judged = [s["rotation_ok"] for s in scores if "rotation_ok" in s]
            if judged:
                value["orientation_correct"] = f"{sum(judged)}/{len(judged)}"
        report["engines"][out.name] = value
    (pack / "scores.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "prepare-camera", "prepare-columns",
                                           "desktop", "score"])
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--modes", nargs='+', choices=["desktop_raw", "desktop_pipeline", "desktop_deva_auto"])
    args = parser.parse_args()
    if args.action == 'desktop':
        desktop(args.pack.resolve(), args.modes)
    elif args.action == 'prepare-camera':
        prepare_camera(args.pack.resolve())
    elif args.action == 'prepare-columns':
        prepare_columns(args.pack.resolve())
    else:
        globals()[args.action](args.pack.resolve())
