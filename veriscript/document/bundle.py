"""Phone -> desktop document bundles (docs/TECH_UPGRADE_PLAN.md, B4).

A `.veriscript` file is a zip the phone app writes ("Desktop bundle"
export). It carries the original page photos and the phone's readings, so
the desktop can run its full pipeline (layout, digit queue, verifier) on the
same pixels. It travels through any channel (cable, USB stick, email);
nothing is uploaded anywhere.

    manifest.json
      {"format": "veriscript-bundle", "version": 1, "title": ..., "created": ...,
       "source": ..., "pages": [{"image": "pages/0001.jpg", "width": ..,
       "height": .., "recognized": bool, "note": str, "lines": [...]}]}
    pages/0001.jpg ...

A bundle is untrusted input: the zip is never extracted to disk, entry names
come only from the manifest and must match `pages/NNNN.ext`, sizes and the
pixel budget are checked before decoding, and only known line fields with
the right types survive.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

FORMAT = "veriscript-bundle"
VERSION = 1
EXTENSION = ".veriscript"
MAX_PAGES = 2000
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_RATIO = 50  # page images are already compressed; a huge ratio is a zip bomb
_IMAGE_NAME = re.compile(r"^pages/\d{4}\.(jpg|jpeg|png)$")
_LINE_FIELDS = {"text": str, "original": str, "reviewed": bool, "confidence": (int, float),
                "digitCheck": str, "digitAlternative": str, "digitScript": str}


class BundleError(ValueError):
    """The file is not a usable VeriScript bundle (message is user-facing)."""


@dataclass
class BundlePage:
    image: str
    width: int
    height: int
    recognized: bool
    note: str
    lines: List[Dict] = field(default_factory=list)


@dataclass
class Bundle:
    path: str
    title: str
    created: str
    source: str
    pages: List[BundlePage]

    def phone_reading(self) -> Dict:
        """What the phone read and what its user changed, for the run record."""
        corrected = confirmed = 0
        for p in self.pages:
            for line in p.lines:
                if "original" in line and line.get("text") != line["original"]:
                    corrected += 1
                elif line.get("reviewed"):
                    confirmed += 1
        return {"title": self.title, "created": self.created, "source": self.source,
                "pages": [{"page": i + 1, "recognized": p.recognized, "note": p.note,
                           "lines": p.lines} for i, p in enumerate(self.pages)],
                "corrected_lines": corrected, "confirmed_lines": confirmed}


def is_bundle_name(name: Optional[str]) -> bool:
    return (name or "").strip().lower().endswith(EXTENSION)


def _clean_line(raw) -> Optional[Dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
        return None
    def ok(v, t) -> bool:  # bool is an int in Python: only accept it where bool is meant
        return isinstance(v, t) and (t is bool or not isinstance(v, bool))

    line = {k: raw[k] for k, t in _LINE_FIELDS.items() if k in raw and ok(raw[k], t)}
    box = raw.get("bbox")
    if (isinstance(box, list) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
        line["bbox"] = [float(v) for v in box]
    return line


def _int(v, name: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 100_000:
        raise BundleError(f"The bundle's page list is damaged ({name}).")
    return v


def open_bundle(path: str) -> Bundle:
    """Read and check the manifest; raises BundleError with a plain reason."""
    if not zipfile.is_zipfile(path):
        raise BundleError("That file is not a VeriScript bundle.")
    with zipfile.ZipFile(path) as zf:
        try:
            info = zf.getinfo("manifest.json")
        except KeyError:
            raise BundleError("That file is not a VeriScript bundle (no manifest).") from None
        if info.file_size > MAX_MANIFEST_BYTES:
            raise BundleError("The bundle's page list is too large.")
        try:
            manifest = json.loads(zf.read(info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BundleError("The bundle's page list is damaged.") from None
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BundleError("That file is not a VeriScript bundle.")
        if manifest.get("version") != VERSION:
            raise BundleError("This bundle was made by a newer app version. Update VeriScript Desktop.")
        raw_pages = manifest.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise BundleError("The bundle has no pages.")
        if len(raw_pages) > MAX_PAGES:
            raise BundleError(f"The bundle has more than {MAX_PAGES} pages.")
        names = set(zf.namelist())
        pages = []
        for raw in raw_pages:
            if not isinstance(raw, dict):
                raise BundleError("The bundle's page list is damaged.")
            image = raw.get("image")
            if not isinstance(image, str) or not _IMAGE_NAME.match(image) or image not in names:
                raise BundleError("The bundle's page list names a missing or invalid image.")
            entry = zf.getinfo(image)
            if entry.file_size > MAX_IMAGE_BYTES or (
                    entry.compress_size and entry.file_size / entry.compress_size > MAX_RATIO):
                raise BundleError("A page image in the bundle is too large.")
            lines = raw.get("lines") if isinstance(raw.get("lines"), list) else []
            pages.append(BundlePage(
                image=image, width=_int(raw.get("width"), "width"),
                height=_int(raw.get("height"), "height"),
                recognized=raw.get("recognized") is True,
                note=raw.get("note") if isinstance(raw.get("note"), str) else "",
                lines=[c for c in (_clean_line(l) for l in lines) if c is not None]))

    def text(key: str) -> str:
        v = manifest.get(key)
        return v.strip()[:200] if isinstance(v, str) else ""

    return Bundle(path=path, title=text("title"), created=text("created"),
                  source=text("source"), pages=pages)


def iter_images(bundle: Bundle, max_megapixels: int = 60,
                limit: Optional[int] = None) -> Iterator[Tuple[int, np.ndarray]]:
    """Yield (index, BGR page) one at a time, EXIF orientation applied."""
    import cv2
    from PIL import Image, ImageOps

    with zipfile.ZipFile(bundle.path) as zf:
        for i, page in enumerate(bundle.pages):
            if limit is not None and i >= limit:
                return
            data = zf.read(page.image)
            try:
                with Image.open(io.BytesIO(data)) as im:
                    if im.width * im.height > max_megapixels * 1_000_000:
                        raise BundleError(f"Page {i + 1} is larger than {max_megapixels} megapixels.")
                    if im.format not in ("JPEG", "PNG"):
                        raise BundleError(f"Page {i + 1} is not a JPEG or PNG image.")
                    rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
            except BundleError:
                raise
            except Exception:  # noqa: BLE001 - any decoder failure is a damaged page
                raise BundleError(f"Page {i + 1} of the bundle could not be read.") from None
            yield i, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
