from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import pandas as pd
from scipy import stats

import biostat_tool.web as web
from biostat_tool.examples import get_example, teaching_plot_presets

TOKENS = ',NA,N/A,NaN,nan'


def _args(key: str):
    ex = web.load_example_callback(key)
    return (
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4], ex[6], ex[7].value, ex[8], ex[9],
        ex[10], ex[11], ex[12], 10, 9999, 20260915, TOKENS, TOKENS,
    )


def _teaching_frames():
    ex = get_example('pearson_spearman_teaching')
    a = pd.read_csv(ex['a']['path']).set_index('sample_id')
    b = pd.read_csv(ex['b']['path']).set_index('sample_id')
    return a, b


def test_teaching_plot_presets_are_visually_and_statistically_distinct():
    a, b = _teaching_frames()
    presets = teaching_plot_presets()
    required = {
        ('linear_signal', 'linear_partner'),
        ('negative_driver', 'negative_partner'),
        ('monotonic_driver', 'monotonic_nonlinear'),
        ('outlier_driver', 'outlier_partner'),
        ('null_a', 'null_b'),
        ('missing_driver', 'missing_partner'),
    }
    assert required <= set(presets)

    def corr(pair):
        x, y = a[pair[0]], b[pair[1]]
        mask = x.notna() & y.notna()
        return int(mask.sum()), float(stats.pearsonr(x[mask], y[mask]).statistic), float(stats.spearmanr(x[mask], y[mask]).statistic)

    n, pearson, spearman = corr(('linear_signal', 'linear_partner'))
    assert n == 80 and pearson > 0.98 and spearman > 0.98

    n, pearson, spearman = corr(('negative_driver', 'negative_partner'))
    assert n == 80 and pearson < -0.98 and spearman < -0.98

    n, pearson, spearman = corr(('monotonic_driver', 'monotonic_nonlinear'))
    assert n == 80 and spearman > 0.96 and spearman - pearson > 0.05

    n, pearson, spearman = corr(('outlier_driver', 'outlier_partner'))
    assert n == 80 and abs(pearson) < 0.30 and spearman > 0.80

    n, pearson, spearman = corr(('null_a', 'null_b'))
    assert n == 80 and abs(pearson) < 0.20 and abs(spearman) < 0.20

    n, pearson, spearman = corr(('missing_driver', 'missing_partner'))
    assert n == 64 and pearson > 0.80 and spearman > 0.80


def test_teaching_pairs_are_promoted_and_labeled_in_browser_selector():
    request = gr.Request(session_hash='rc4-teaching-labels')
    inspected = web.inspect_callback(*_args('pearson_spearman_teaching'), request=request)
    state = inspected[5]
    result = web.analyze_callback(state, True, request=request)
    selector = result[6]
    choices = selector.choices
    labels = [c[0] if isinstance(c, (tuple, list)) else str(c) for c in choices[:6]]
    assert any('Strong positive linear' in label for label in labels)
    assert any('Strong negative linear' in label for label in labels)
    assert any('Monotonic nonlinear' in label for label in labels)
    assert any('Outlier-sensitive' in label for label in labels)
    web.invalidate_run_state(request=request)


def test_plot_export_includes_png_svg_and_pdf_from_same_figure():
    request = gr.Request(session_hash='rc4-pdf-export')
    inspected = web.inspect_callback(*_args('pearson_spearman_teaching'), request=request)
    cstate = web.analyze_callback(inspected[5], True, request=request)[7]
    selector = json.dumps(['monotonic_driver', 'monotonic_nonlinear'])
    fig, meta, png, svg, pdf = web.plot_pair_callback(cstate, selector, 'raw', request=request)
    assert fig is not None
    assert 'Teaching pattern:' in meta
    for p in (png, svg, pdf):
        assert Path(p).is_file() and Path(p).stat().st_size > 500
    assert Path(pdf).read_bytes().startswith(b'%PDF-')
    assert Path(svg).read_text(encoding='utf-8').lstrip().startswith('<?xml')
    web.invalidate_run_state(request=request)


def test_example_generator_reproduces_teaching_files(tmp_path):
    # The checked-in generator is the source of truth for deterministic example structure.
    root = Path(__file__).resolve().parents[2]
    text = (root / 'scripts' / 'generate_synthetic_examples.py').read_text(encoding='utf-8')
    assert 'TEACHING_SEED = SEED + 404' in text
    truth = json.loads((root / 'biostat_tool' / 'example_data' / 'truth.json').read_text(encoding='utf-8'))
    assert len(truth['pearson_spearman_teaching']['plot_presets']) == 6
