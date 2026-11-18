"""Book-video capture: actual encoded clips, physical page order, and PDF output."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from veriscript.document.video import (VideoOptions, _page_view, _split_view,
                                       export_video_pdf, extract_video_pages)


def _spread(seed, *, single=False):
    frame = np.full((480, 720, 3), 35, np.uint8)
    x0, x1 = (180, 500) if single else (50, 670)
    cv2.rectangle(frame, (x0, 20), (x1, 460), (242, 242, 242), -1)
    rng = np.random.default_rng(seed)
    for left in ([x0] if single else [x0, 360]):
        for line in range(12):
            x = left + 20 + int(rng.integers(0, 40))
            y = 70 + line * 27
            cv2.putText(frame, f"{seed} BOOK {rng.integers(1000, 9999)}", (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, (20, 20, 20), 1, cv2.LINE_AA)
    if not single:
        cv2.line(frame, (360, 20), (360, 460), (80, 80, 80), 4)
    return frame


def _offcenter_spread(seed):
    """Real-recording shape: the open book sits left of centre; the right of
    the frame is a patterned dark blanket. No clean Canny quad survives."""
    frame = np.full((480, 720, 3), 40, np.uint8)
    # patterned "carpet" right of x=430
    rng = np.random.default_rng(seed)
    carpet = frame[:, 430:]
    carpet[..., 2] = rng.integers(60, 160, carpet[..., 2].shape)
    carpet[..., 0] = rng.integers(0, 60, carpet[..., 0].shape)
    cv2.rectangle(frame, (20, 30), (400, 470), (242, 242, 242), -1)
    for left in (20, 210):
        for line in range(12):
            x = left + 20 + int(rng.integers(0, 40))
            y = 70 + line * 27
            cv2.putText(frame, f"{seed} BOOK {rng.integers(1000, 9999)}", (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.line(frame, (210, 30), (210, 470), (80, 80, 80), 4)
    return frame


def _clip(path, views, hold=20):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (720, 480))
    if not writer.isOpened():
        pytest.skip("MJPG encoder unavailable")
    try:
        for index, view in enumerate(views):
            if index:
                for _ in range(5):
                    writer.write(np.full_like(view, 80))
            for _ in range(hold):
                writer.write(view)
    finally:
        writer.release()
    return path


def test_spread_capture_has_separate_ordered_pages_and_provenance(tmp_path):
    src = _clip(tmp_path / "book.avi", [_spread(1), _spread(2), _spread(3)])
    out = tmp_path / "out"
    capture = extract_video_pages(str(src), str(out))
    assert len(capture["pages"]) == 6
    assert [p["side"] for p in capture["pages"]] == ["left", "right"] * 3
    times = [p["timestamp"] for p in capture["pages"]]
    assert times == sorted(times)
    assert times[0] == times[1] and times[2] > times[1]
    assert all(p["cropped"] for p in capture["pages"])
    assert all(p["height"] > p["width"] for p in capture["pages"])
    assert json.loads((out / "capture.json").read_text())["pages"] == capture["pages"]


def test_single_page_auto_and_repeat_hold_not_duplicated(tmp_path):
    image = _spread(4, single=True)
    src = _clip(tmp_path / "page.avi", [image, image], hold=30)
    capture = extract_video_pages(str(src), str(tmp_path / "out"))
    assert len(capture["pages"]) == 1
    assert capture["pages"][0]["side"] == "single"


def test_return_to_previous_page_is_retained(tmp_path):
    a, b = _spread(1), _spread(9)
    src = _clip(tmp_path / "book.avi", [a, b, a])
    assert len(extract_video_pages(str(src), str(tmp_path / "out"))["pages"]) == 6


def test_page_cap_preserves_whole_spreads_and_reports_truncation(tmp_path):
    src = _clip(tmp_path / "book.avi", [_spread(1), _spread(2), _spread(3)])
    capture = extract_video_pages(str(src), str(tmp_path / "out"), VideoOptions(max_pages=3))
    assert len(capture["pages"]) == 2
    assert capture["capped"]
    assert any("page limit" in w for w in capture["warnings"])


def test_duration_cap_is_explicit(tmp_path):
    src = _clip(tmp_path / "book.avi", [_spread(1), _spread(2)])
    capture = extract_video_pages(str(src), str(tmp_path / "out"), VideoOptions(max_seconds=1.8))
    assert capture["capped"] and len(capture["pages"]) == 2
    assert any("second limit" in w for w in capture["warnings"])


def test_fast_or_blank_clip_rejected(tmp_path):
    for label, views, hold in (("fast", [_spread(1)], 4),
                                ("blank", [np.full((480, 720, 3), 240, np.uint8)], 20)):
        src = _clip(tmp_path / f"{label}.avi", views, hold=hold)
        with pytest.raises(ValueError, match="No steady"):
            extract_video_pages(str(src), str(tmp_path / label))


def test_bad_video_limits_and_cancellation(tmp_path):
    for kwargs in ({"hold_seconds": float("nan")}, {"sample_fps": 0},
                   {"max_pages": 0}, {"layout": "bogus"}):
        with pytest.raises(ValueError):
            VideoOptions(**kwargs)
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    with pytest.raises(ValueError, match="decode"):
        extract_video_pages(str(bad), str(tmp_path / "bad"))
    src = _clip(tmp_path / "book.avi", [_spread(1)])
    with pytest.raises(TimeoutError):
        extract_video_pages(str(src), str(tmp_path / "out"), cancel=lambda: True)


def test_pdf_uses_reviewed_selection_order(tmp_path):
    import pypdfium2 as pdfium

    pages = []
    for i, level in enumerate([40, 220, 100]):
        name = f"capture_{i:04d}.jpg"
        cv2.imwrite(str(tmp_path / name), np.full((200, 140, 3), level, np.uint8))
        pages.append({"id": i, "file": name})
    path = export_video_pdf(str(tmp_path), [pages[2], pages[0]])
    with pdfium.PdfDocument(path) as pdf:
        assert len(pdf) == 2
        values = [np.asarray(pdf[i].render().to_pil()).mean() for i in range(2)]
        assert values[0] > values[1] + 40
        assert not pdf[0].get_textpage().get_text_range().strip()


def test_searchable_export_uses_shared_pipeline(tmp_path, monkeypatch):
    import pypdfium2 as pdfium
    from types import SimpleNamespace
    from veriscript.document import pipeline
    from veriscript.document.ocr import Token

    name = "capture_0000.jpg"
    image = np.full((200, 140, 3), 240, np.uint8)
    cv2.imwrite(str(tmp_path / name), image)
    calls = []
    def fake(img, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(display_bgr=img, ocr=SimpleNamespace(tokens=[
            Token(text="BOOK PAGE", conf=99, bbox=(5, 5, 100, 25))]))
    monkeypatch.setattr(pipeline, "run_document_pipeline", fake)
    path = export_video_pdf(str(tmp_path), [{"id": 0, "file": name}], searchable=True, lang="ne")
    assert calls[0]["lang"] == "ne" and calls[0]["deskew"]
    with pdfium.PdfDocument(path) as pdf:
        assert "BOOK PAGE" in pdf[0].get_textpage().get_text_range()


def test_digital_export_retypesets_text_without_page_images(tmp_path, monkeypatch):
    """The word-style PDF: real flowing text on A4, no captured pixels."""
    import pypdfium2 as pdfium
    from types import SimpleNamespace
    from veriscript.document import pipeline
    from veriscript.document.ocr import Token

    name = "capture_0000.jpg"
    cv2.imwrite(str(tmp_path / name), np.full((200, 140, 3), 240, np.uint8))
    def fake(img, **kwargs):
        return SimpleNamespace(display_bgr=img, ocr=SimpleNamespace(tokens=[
            Token(text="SEVEN", conf=99, bbox=(30, 10, 90, 24), granularity="line"),
            Token(text="KNOX HAD A BIG MOUTH.", conf=99, bbox=(10, 60, 120, 80),
                  granularity="line")]))
    monkeypatch.setattr(pipeline, "run_document_pipeline", fake)
    path = export_video_pdf(str(tmp_path), [{"id": 0, "file": name}],
                            digital=True)
    with pdfium.PdfDocument(path) as pdf:
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        assert "SEVEN" in text and "KNOX" in text
        # A4 word-style page, not the capture's aspect ratio
        size = pdf[0].get_size()
        assert abs(size[0] / size[1] - 595.0 / 842.0) < 0.02


def test_clean_export_pristine_upscale(tmp_path):
    """Small captures are upscaled 2x in the default clean PDF."""
    import pypdfium2 as pdfium

    name = "capture_0000.jpg"
    cv2.imwrite(str(tmp_path / name), np.full((150, 200, 3), 240, np.uint8))
    path = export_video_pdf(str(tmp_path), [{"id": 0, "file": name}])
    with pdfium.PdfDocument(path) as pdf:
        width = pdf[0].get_size()[0]
    # 150 dpi estimate doubled from 200px: 200*2*72/150 = 192pt, plus smooth
    assert width > 140


def test_perspective_rectification_and_explicit_single_override():
    frame = _spread(2)
    transform = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [719, 0], [719, 479], [0, 479]]),
        np.float32([[30, 0], [700, 35], [680, 460], [0, 430]]))
    skewed = cv2.warpPerspective(frame, transform, (720, 480), borderValue=(35, 35, 35))
    view, cropped, _ = _page_view(skewed)
    assert cropped
    assert len(_split_view(view, "single")) == 1
    assert len(_split_view(view, "spread")) == 2


def _found_at(frame, crop):
    """x where the crop sits in the frame (exact pixels, best match)."""
    scores = cv2.matchTemplate(frame, crop, cv2.TM_SQDIFF)
    return int(cv2.minMaxLoc(scores)[2][0])


@pytest.mark.parametrize("make", [_spread, _offcenter_spread])
def test_right_page_is_cut_from_right_of_the_binding(make):
    # Regression: the right side's paper box was measured from the cut but
    # cropped from x=0, so every "right page" repeated the left page.
    frame = make(7)
    pages = dict(_split_view(frame, "spread"))
    binding = 360 if make is _spread else 210
    assert _found_at(frame, pages["left"]) < binding
    assert _found_at(frame, pages["right"]) >= binding - 4
    assert not np.array_equal(pages["left"][:, :50], pages["right"][:, :50])


def test_one_sided_shadow_cuts_at_the_fold_not_inside_the_shaded_page():
    # A page curving into shadow at the binding has its darkest columns inside
    # its own text, not at the fold; the left page must not carry that text.
    frame = np.full((480, 720, 3), 35, np.uint8)
    cv2.rectangle(frame, (40, 20), (680, 460), (238, 238, 238), -1)
    fold = 350
    for x in range(fold, 680):  # right page: 150 at the fold, recovering
        level = int(150 + min(1.0, (x - fold) / 160) * 80)
        frame[20:461, x] = level
    rng = np.random.default_rng(3)
    for left in (60, fold + 4):
        for line in range(14):
            y = 60 + line * 27
            cv2.putText(frame, f"LINE {rng.integers(1000, 9999)} text",
                        (left + int(rng.integers(0, 10)), y),
                        cv2.FONT_HERSHEY_SIMPLEX, .5, (20, 20, 20), 1, cv2.LINE_AA)
    pages = dict(_split_view(frame, "spread"))
    left_end = _found_at(frame, pages["left"]) + pages["left"].shape[1]
    assert left_end <= fold + 3
    assert _found_at(frame, pages["right"]) >= fold - 4


def test_failed_export_preserves_previous_pdf(tmp_path):
    previous = tmp_path / "book.pdf"
    previous.write_bytes(b"previous export")
    with pytest.raises(ValueError, match="unavailable"):
        export_video_pdf(str(tmp_path), [{"id": 0, "file": "missing.jpg"}])
    assert previous.read_bytes() == b"previous export"
    assert not (tmp_path / ".book.pdf").exists()


def test_cli_video_dispatch_exports_and_review_only(tmp_path, monkeypatch):
    import sys
    from veriscript.cli import main

    source = _clip(tmp_path / "book.avi", [_spread(1)])
    for review in (False, True):
        output = tmp_path / ("review" if review else "pdf")
        args = ["veriscript", "--mode", "video", "--input", str(source),
                "--output", str(output), "--video-layout", "spread"]
        if review:
            args.append("--video-review-only")
        monkeypatch.setattr(sys, "argv", args)
        with pytest.raises(SystemExit) as result:
            main()
        assert result.value.code == 0
        assert (output / "capture.json").exists()
        assert (output / "book.pdf").exists() is not review


def test_cli_pdf_mode_routes_to_digital_export(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from veriscript.document import video as video_mod
    from veriscript.cli import main

    source = _clip(tmp_path / "book.avi", [_spread(1)])
    seen = {}

    def fake_export(out_dir, pages, **kwargs):
        out = tmp_path / "dig"
        out.mkdir(exist_ok=True)
        seen.update(kwargs)
        return str(out / "book.pdf")

    monkeypatch.setattr(video_mod, "extract_video_pages", lambda *a, **k: {
        "pages": [{"id": 0, "file": "capture_0000.jpg"}], "warnings": []})
    monkeypatch.setattr(video_mod, "export_video_pdf", fake_export)
    args = ["veriscript", "--mode", "video", "--input", str(source),
            "--output", str(tmp_path / "dig"), "--video-layout", "spread",
            "--video-pdf", "digital"]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    assert seen["digital"] is True and seen["searchable"] is False

    monkeypatch.setattr(sys, "argv", ["veriscript", "--mode", "video",
                                      "--input", str(source),
                                      "--output", str(tmp_path / "clean"),
                                      "--video-searchable"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    assert seen["digital"] is False and seen["searchable"] is True


def test_hundred_page_book_streams_to_pdf(tmp_path):
    import pypdfium2 as pdfium

    src = _clip(tmp_path / "book.avi", [_spread(i) for i in range(50)])
    out = tmp_path / "out"
    capture = extract_video_pages(str(src), str(out))
    assert len(capture["pages"]) == 100
    assert not capture["capped"]
    path = export_video_pdf(str(out), capture["pages"])
    with pdfium.PdfDocument(path) as pdf:
        assert len(pdf) == 100


def test_offcenter_book_over_patterned_background_is_split_and_cropped(tmp_path):
    """Regression for the real recording: book left of centre, blanket right,
    no Canny quad. The midpoint split used to slice through page text."""
    src = _clip(tmp_path / "book.avi", [_offcenter_spread(1), _offcenter_spread(2)])
    out = tmp_path / "out"
    capture = extract_video_pages(str(src), str(out), VideoOptions(layout="spread"))
    pages = capture["pages"]
    assert len(pages) == 4  # 2 spreads x (left+right)
    assert [p["side"] for p in pages] == ["left", "right"] * 2
    for page in pages:
        assert page["cropped"]
        assert page["width"] >= 100
        # no patterned-carpet pixels: paper region must be bright on average
        image = cv2.imread(str(out / page["file"]))
        assert float(np.median(image)) > 100


def test_side_with_no_real_paper_is_dropped(tmp_path):
    """A spread whose right half is bare background splits to left + right
    only when the paper region itself covers both halves; the dark half
    cannot pass as a page (checked at the view level here)."""
    frame = _offcenter_spread(3)
    frame[:, 430:] = 40  # kill the paper-coloured noise right of the book
    src = _clip(tmp_path / "book.avi", [frame])
    capture = extract_video_pages(str(src), str(tmp_path / "out"))
    sides = [p["side"] for p in capture["pages"]]
    assert sides in (["left", "right"], ["single"])


def test_no_paper_side_dropped_when_book_is_single_page(tmp_path):
    """A single page plus bare background must not emit a background 'page'."""
    frame = _spread(5, single=True)
    frame[:, 560:] = 45  # dark furniture right of the page
    src = _clip(tmp_path / "book.avi", [frame])
    capture = extract_video_pages(str(src), str(tmp_path / "out"))
    assert [p["side"] for p in capture["pages"]] == ["single"]
    assert capture["pages"][0]["width"] < frame.shape[1]  # cropped to the page


def test_mostly_obstructed_spread_side_is_dropped_with_warning(tmp_path):
    """One normal half + one sliver is a turning leaf over that page, not a
    page seen narrowly: drop the sliver and say which page needs re-capture."""
    frame = _spread(9)
    # right page: text strip beside the gutter, then a featureless white leaf
    # bundle filling the rest of the half (the real obstruction shape)
    right_patch = frame[:, 360:].copy()
    frame[:, 360:] = 35
    frame[:, 360:430] = right_patch[:, :70]
    frame[:, 430:470] = (242, 242, 242)
    src = _clip(tmp_path / "book.avi", [frame])
    capture = extract_video_pages(str(src), str(tmp_path / "out"),
                                  VideoOptions(layout="spread"))
    sides = [p["side"] for p in capture["pages"]]
    assert sides == ["left"], sides
    assert any("re-record" in w for w in capture["warnings"])
