import json

import pytest

from evals.harness.compare_apps import digest, score


def make_pack(tmp_path):
    (tmp_path / 'image').write_bytes(b'fixed image bytes')
    (tmp_path / 'gt').write_text('Total 123', encoding='utf-8')
    row = dict(id='page', image='image', gt='gt', sha256=digest(tmp_path / 'image'),
               gt_sha256=digest(tmp_path / 'gt'), family='synthetic')
    (tmp_path / 'manifest.json').write_text(json.dumps({'entries': [row]}))
    output = tmp_path / 'outputs/candidate'
    output.mkdir(parents=True)
    return row, output


def test_unproven_output_cannot_win(tmp_path):
    _, output = make_pack(tmp_path)
    (output / 'page.txt').write_text('Total 123')
    score(tmp_path)
    result = json.loads((tmp_path / 'scores.json').read_text())['engines']['candidate']
    assert result['status'] == 'incomplete'
    assert 'mean_cer' not in result


def test_changed_input_cannot_be_scored(tmp_path):
    _, output = make_pack(tmp_path)
    (output / 'page.txt').write_text('Total 123')
    (output / 'page.json').write_text(json.dumps({'image_sha256': 'old-fixture'}))
    with pytest.raises(ValueError, match='different image'):
        score(tmp_path)


def test_empty_ocr_counts_as_failure(tmp_path):
    row, output = make_pack(tmp_path)
    (output / 'page.txt').write_text('')
    (output / 'page.json').write_text(json.dumps({'image_sha256': row['sha256']}))
    score(tmp_path)
    result = json.loads((tmp_path / 'scores.json').read_text())['engines']['candidate']
    assert result['status'] == 'complete'
    assert result['mean_cer'] == 1
