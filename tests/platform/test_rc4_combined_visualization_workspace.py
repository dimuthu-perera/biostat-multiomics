from __future__ import annotations

import inspect
from pathlib import Path

import gradio as gr
import pandas as pd
import pytest

import biostat_tool.web as web
from biostat_tool.resource_limits import resource_markdown, assess_resources
from biostat_tool.visualization import (
    BUBBLE_MAX_POINTS,
    SCATTER_MATRIX_MAX_VARIABLES,
    make_bubble_figure,
    make_scatter_matrix_figure,
)
from correlation_tool.analysis import CorrelationConfig

TOKENS = ',NA,N/A,NaN,nan'


def _completed(key: str = 'metabolomics_proteomics', session: str = 'rc5-viz'):
    ex = web.load_example_callback(key)
    args = (
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4], ex[6], ex[7].value, ex[8], ex[9],
        ex[10], ex[11], ex[12], 10, 9999, 20260915, TOKENS, TOKENS,
    )
    request = gr.Request(session_hash=session)
    prepared = web.inspect_callback(*args, request=request)[5]
    analyzed = web.analyze_callback(prepared, True, request=request)
    return request, analyzed


def _assert_three_exports(result):
    fig, meta, png, svg, pdf = result
    assert fig is not None
    assert isinstance(meta, str) and meta
    for path in (png, svg, pdf):
        p = Path(path)
        assert p.is_file() and p.stat().st_size > 500
    assert Path(pdf).read_bytes().startswith(b'%PDF-')
    assert '<svg' in Path(svg).read_text(encoding='utf-8')[:1000]


def test_summary_visualizations_export_png_svg_pdf_from_validated_results():
    request, analyzed = _completed(session='rc5-summary-exports')
    cstate = analyzed[7]
    features_a = analyzed[8].value[:4]
    features_b = analyzed[9].value[:4]
    _assert_three_exports(web.heatmap_callback(cstate, features_a, features_b, 0.05, True, request=request))
    _assert_three_exports(web.correlogram_callback(cstate, features_a, features_b, 0.05, request=request))
    _assert_three_exports(web.bubble_callback(cstate, features_a, features_b, 0.05, 'effect', request=request))
    web.invalidate_run_state(request=request)


def test_scatter_matrix_exports_and_limits_total_variables_to_nine():
    request, analyzed = _completed(session='rc5-matrix')
    cstate = analyzed[7]
    a = analyzed[8].value[:3]
    b = analyzed[9].value[:3]
    result = web.scatter_matrix_callback(cstate, a, b, request=request)
    _assert_three_exports(result)
    assert 'no new correlation tests' in result[1]
    too_many_a = [str(x) for x in cstate.prepared.inspected.aligned_a.columns[:5]]
    too_many_b = [str(x) for x in cstate.prepared.inspected.aligned_b.columns[:5]]
    bad = web.scatter_matrix_callback(cstate, too_many_a, too_many_b, request=request)
    assert bad[0] is None and f'at most {SCATTER_MATRIX_MAX_VARIABLES}' in bad[1]
    web.invalidate_run_state(request=request)


def test_scatter_matrix_does_not_compute_within_dataset_inferential_correlations():
    source = inspect.getsource(make_scatter_matrix_figure)
    assert 'pearsonr' not in source
    assert 'spearmanr' not in source
    assert 'no added inference' in source


def test_bubble_plot_refuses_unreadable_selection_over_render_limit():
    n_a, n_b = 25, 25
    rows = []
    for i in range(n_a):
        for j in range(n_b):
            rows.append({'feature_a':f'A{i}', 'feature_b':f'B{j}', 'estimate':0.1, 'q_value':0.5, 'status':'ok'})
    results = pd.DataFrame(rows)
    assert len(results) > BUBBLE_MAX_POINTS
    with pytest.raises(ValueError, match='at most'):
        make_bubble_figure(results, [f'A{i}' for i in range(n_a)], [f'B{j}' for j in range(n_b)])


def test_resource_copy_uses_compute_readiness_not_internal_envelope_language(tmp_path):
    a = tmp_path/'a.csv'; b = tmp_path/'b.csv'; a.write_text('x\n1\n'); b.write_text('x\n1\n')
    assessment = assess_resources(samples=80, features_a=10, features_b=12, file_a=a, file_b=b, config=CorrelationConfig())
    text = resource_markdown(assessment, method='pearson', permutations=9999)
    assert 'Compute readiness' in text
    assert 'Supported analysis limits' in text
    assert 'resource envelope' not in text.lower()


def test_browser_copy_and_structure_expose_modern_results_workspace():
    source = Path(web.__file__).read_text(encoding='utf-8')
    assert 'Validated v1 resource envelope' not in source
    assert 'Analysis readiness' in source
    assert 'Scientific visualization workspace' in source
    for label in ('Heatmap', 'Correlogram', 'Bubble', 'Scatter matrix', 'Provenance'):
        assert f'gr.Tab("{label}")' in source


def test_analyze_callback_populates_shared_feature_selection_from_completed_results():
    request, analyzed = _completed(session='rc5-shared-selection')
    assert len(analyzed) == 10
    a_update, b_update = analyzed[8], analyzed[9]
    assert a_update.multiselect is True and b_update.multiselect is True
    assert a_update.value and b_update.value
    valid = analyzed[7].completed.primary_results.query("status == 'ok'")
    assert set(a_update.value) <= set(valid.feature_a.astype(str))
    assert set(b_update.value) <= set(valid.feature_b.astype(str))
    web.invalidate_run_state(request=request)


def test_registered_gradio_heatmap_path_uses_session_bound_completed_state():
    import asyncio
    from gradio.state_holder import SessionState

    def fn_index(name: str) -> int:
        matches = [idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, '__name__', None) == name]
        assert matches, name
        return min(matches)

    async def run():
        state = SessionState(web.demo)
        request = gr.Request(session_hash='rc5-registered-heatmap')
        load = await web.demo.process_api(fn_index('load_example_callback'), ['metabolomics_proteomics'], state=state, request=request, session_hash=request.session_hash)
        d = load['data']
        inspect_args = [
            d[0], d[5], d[1], d[2]['value'], d[3], d[4], d[6], d[7]['value'], d[8], d[9],
            d[10], d[11], d[12], 10, 9999, 20260915, TOKENS, TOKENS,
        ]
        await web.demo.process_api(fn_index('inspect_ui'), inspect_args, state=state, request=request, session_hash=request.session_hash)
        analyzed = await web.demo.process_api(fn_index('analyze_ui'), [None, True], state=state, request=request, session_hash=request.session_hash)
        a = analyzed['data'][8]['value'][:3]
        b = analyzed['data'][9]['value'][:3]
        heatmap = await web.demo.process_api(fn_index('heatmap_ui'), [None, a, b, 0.05, True], state=state, request=request, session_hash=request.session_hash)
        assert '**Heatmap**' in heatmap['data'][1] and Path(heatmap['data'][2]['path']).is_file()
        corr = await web.demo.process_api(fn_index('correlogram_ui'), [None, a, b, 0.05], state=state, request=request, session_hash=request.session_hash)
        assert '**Correlogram**' in corr['data'][1] and Path(corr['data'][2]['path']).is_file()
        bubble = await web.demo.process_api(fn_index('bubble_ui'), [None, a, b, 0.05, 'effect'], state=state, request=request, session_hash=request.session_hash)
        assert '**Bubble plot**' in bubble['data'][1] and Path(bubble['data'][2]['path']).is_file()
        matrix = await web.demo.process_api(fn_index('scatter_matrix_ui'), [None, a[:2], b[:2]], state=state, request=request, session_hash=request.session_hash)
        assert '**Scatter matrix**' in matrix['data'][1] and Path(matrix['data'][2]['path']).is_file()
        pair_value = analyzed['data'][6]['value']
        pair = await web.demo.process_api(fn_index('plot_pair_ui'), [None, pair_value, 'raw'], state=state, request=request, session_hash=request.session_hash)
        assert pair['data'][0] is not None and Path(pair['data'][2]['path']).is_file()
        web.invalidate_run_state(request=request)

    asyncio.run(run())


def test_publication_header_reserves_separate_title_subtitle_and_plot_band():
    from biostat_tool.visualization import PairPlotData, make_pair_figure
    import numpy as np

    data = PairPlotData(
        feature_a='very_long_feature_identifier_dataset_a_' + 'X' * 55,
        feature_b='very_long_feature_identifier_dataset_b_' + 'Y' * 55,
        x=np.arange(12, dtype=float),
        y=np.arange(12, dtype=float) * 1.3,
        n_pairwise=12,
        missing_or_excluded=0,
    )
    fig = make_pair_figure(data, method='pearson', estimate=0.91, p_value=1e-7, q_value=2e-6)
    try:
        assert len(fig.texts) >= 2
        title, subtitle = fig.texts[0], fig.texts[1]
        assert title.get_position()[1] - subtitle.get_position()[1] >= 0.05
        # Plot axes must start below the reserved header band.
        ax = fig.axes[0]
        assert ax.get_position().y1 <= 0.80
        assert ax.get_title() == ''
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
