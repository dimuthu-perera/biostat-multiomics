from __future__ import annotations

from pathlib import Path

import gradio as gr
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import biostat_tool.web as web
from biostat_tool.visualization import make_bubble_figure, make_correlogram_figure, make_heatmap_figure

TOKENS = ",NA,N/A,NaN,nan"


def _args(key: str = "metabolomics_proteomics") -> list[object]:
    ex = web.load_example_callback(key)
    return [
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4],
        ex[6], ex[7].value, ex[8], ex[9], ex[10], ex[11],
        ex[12], 10, 9999, 20260915, TOKENS, TOKENS,
    ]


def _completed(session: str = "rc9-usability"):
    request = gr.Request(session_hash=session)
    inspected = web.inspect_callback(*_args(), request=request)
    assert isinstance(inspected[5], web.WebPreparedState)
    analyzed = web.analyze_callback(inspected[5], True, request=request)
    assert isinstance(analyzed[7], web.WebCompletedState)
    return request, inspected, analyzed


def _glyph_results() -> pd.DataFrame:
    rows = []
    for i, a in enumerate(["A1", "A2", "A3"]):
        for j, b in enumerate(["B1", "B2", "B3"]):
            value = (i - j) / 3
            rows.append({"feature_a": a, "feature_b": b, "estimate": value, "q_value": 0.01 + 0.02*(i+j), "status": "ok"})
    return pd.DataFrame(rows)


def test_rc9_header_theme_readiness_and_tooltip_contracts_present():
    assert "#biostat-header h1, #biostat-header h1 *" in web.APP_CSS
    assert "biostat-theme-switcher" in web.APP_CSS
    assert "biostat-dark" in web.APP_JS
    assert "position:fixed" in web.APP_CSS and "biostat-tooltip" in web.APP_CSS
    assert "getBoundingClientRect" in web.APP_JS
    assert "PASS" in web.READINESS_LEGEND_HTML
    assert "WARNING" in web.READINESS_LEGEND_HTML
    assert "BLOCKED" in web.READINESS_LEGEND_HTML


def test_missing_analysis_spec_is_non_destructive_and_blocked_state_disables_analysis():
    request = gr.Request(session_hash="rc9-no-spec")
    result = web.load_spec_ui(request, None)
    assert "Choose a saved analysis setup" in result[-1]
    assert all(isinstance(v, dict) and v.get("__type__") == "update" for v in result[:-1])

    blocked = web.inspect_callback(*_args("rnaseq_raw_blocked"), request=request)
    assert isinstance(blocked[5], web.WebPreparedState)
    assert blocked[5].prepared.blocked
    inspect_btn, run_btn, gate, workflow = web.inspection_controls_ui(blocked[5])
    assert run_btn.interactive is False
    assert "Resolve blocked issues" in run_btn.value
    assert "Analysis blocked" in gate
    assert "blocked" in workflow
    web.invalidate_run_state(request=request)


def test_human_readable_choices_and_same_domain_examples_are_exposed():
    assert ("Dependent or clustered observations", "dependent_or_clustered") in web.DESIGN_CHOICES
    assert ("Samples in rows", "samples_rows") in web.ORIENTATION_CHOICES
    labels = dict(web.example_choices())
    assert "metabolomics_metabolomics" in labels.values()
    assert "rnaseq_rnaseq" in labels.values()
    assert "proteomics_proteomics" in labels.values()
    assert all("_" not in label for label, _ in web.DESIGN_CHOICES)
    assert all("_" not in label for label, _ in web.ORIENTATION_CHOICES)


def test_correlogram_is_cell_based_and_bubble_is_true_scatter_with_variable_sizes():
    results = _glyph_results()
    corr = make_correlogram_figure(results, ["A1", "A2", "A3"], ["B1", "B2", "B3"])
    bubble = make_bubble_figure(results, ["A1", "A2", "A3"], ["B1", "B2", "B3"], size_by="effect")
    try:
        # Correlogram is an image/cell matrix, not a bubble collection.
        assert len(corr.axes[0].images) == 1
        assert len(corr.axes[0].collections) == 0
        assert any("0." in text.get_text() or "-0." in text.get_text() for text in corr.axes[0].texts)
        # Bubble plot is a continuous x/y scatter with non-uniform marker sizes.
        collections = bubble.axes[0].collections
        assert collections
        sizes = collections[0].get_sizes()
        assert len(np.unique(np.round(sizes, 8))) > 1
        assert bubble.axes[0].get_xlabel() == "Correlation coefficient"
        assert "-log10" in bubble.axes[0].get_ylabel()
    finally:
        plt.close(corr)
        plt.close(bubble)


def test_summary_colorbar_labels_are_inside_native_canvas():
    results = _glyph_results()
    figs = [
        make_heatmap_figure(results, ["A1", "A2", "A3"], ["B1", "B2", "B3"]),
        make_correlogram_figure(results, ["A1", "A2", "A3"], ["B1", "B2", "B3"]),
        make_bubble_figure(results, ["A1", "A2", "A3"], ["B1", "B2", "B3"]),
    ]
    try:
        for fig in figs:
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            canvas_w, canvas_h = fig.canvas.get_width_height()
            labels = [ax.yaxis.label for ax in fig.axes[1:] if ax.yaxis.label.get_text()]
            assert labels, "expected a colorbar label"
            for label in labels:
                box = label.get_window_extent(renderer=renderer)
                assert box.x0 >= 0 and box.x1 <= canvas_w
                assert box.y0 >= 0 and box.y1 <= canvas_h
    finally:
        for fig in figs:
            plt.close(fig)


def test_batch_report_generates_combined_pdf_and_zip(tmp_path):
    request, _, analyzed = _completed("rc9-batch-report")
    cstate = analyzed[7]
    meta, pdf, archive = web.association_report_callback(cstate, 10, "q_value", request=request)
    try:
        assert "Generated 10 association pages" in meta
        assert pdf and Path(pdf).is_file() and Path(pdf).stat().st_size > 0
        assert archive and Path(archive).is_file() and Path(archive).stat().st_size > 0
    finally:
        web.invalidate_run_state(request=request)
