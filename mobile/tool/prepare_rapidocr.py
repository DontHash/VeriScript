"""Bundle the desktop OCR weights in Android; no downloads at app runtime.

Uses the installed RapidOCR cache, or retrieves the exact published artifact.
Every file must match the pinned upstream SHA256 before it enters the APK.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = root / 'rapidocr-models.json'
    spec = importlib.util.find_spec('rapidocr')
    cache = Path(spec.origin).parent / 'models' if spec else None
    target = root / 'android/app/src/main/assets/rapidocr'
    target.mkdir(parents=True, exist_ok=True)
    for row in json.loads(manifest.read_text())['models']:
        out = target / row['file']
        if out.exists() and hashlib.sha256(out.read_bytes()).hexdigest() == row['sha256']:
            continue
        source = cache / row['file'] if cache else None
        if source and source.exists():
            data = source.read_bytes()
        else:
            with urllib.request.urlopen(row['url'], timeout=120) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Model checksum mismatch: ' + row['file'])
        out.write_bytes(data)
        print(row['file'], len(data))
    shutil.copyfile(manifest, target / 'manifest.json')
    for notice in (root / 'licenses/rapidocr').glob('*.txt'):
        shutil.copyfile(notice, target / notice.name)


if __name__ == '__main__':
    main()
