"""Paired OCR comparison: identical image bytes, explicit GT authority, no missing-output wins.

python -m evals.harness.compare_apps prepare
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
            scores.append(dict(id=row["id"], family=row["family"], cer=cer(gt, hyp),
                               wer=wer(gt, hyp), bag_cer=cer_bag(gt, hyp),
                               digit_cer=cer(gtd, hypd) if gtd else None,
                               digit_exact=gtd == hypd if gtd else None))
        value = dict(status="complete" if not missing else "incomplete", missing=missing, pages=scores)
        if not missing:
            value["mean_cer"] = float(np.mean([s["cer"] for s in scores]))
            value["by_family"] = {family: float(np.mean([s["cer"] for s in scores if s["family"] == family]))
                                  for family in sorted({s["family"] for s in scores})}
        report["engines"][out.name] = value
    (pack / "scores.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "desktop", "score"])
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--modes", nargs='+', choices=["desktop_raw", "desktop_pipeline", "desktop_deva_auto"])
    args = parser.parse_args()
    if args.action == 'desktop':
        desktop(args.pack.resolve(), args.modes)
    else:
        globals()[args.action](args.pack.resolve())
