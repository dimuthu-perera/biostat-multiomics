from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import gradio as gr
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from gradio.state_holder import SessionState
from gradio.utils import get_upload_folder

import biostat_tool.web as web
from biostat_tool.visualization import (
    PairPlotData,
    export_figure,
    make_bubble_figure,
    make_correlogram_figure,
    make_pair_figure,
    pairwise_complete_data,
)

TOKENS = ",NA,N/A,NaN,nan"


def _args(key: str = "metabolomics_proteomics") -> list[object]:
    ex = web.load_example_callback(key)
    return [
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4],
        ex[6], ex[7].value, ex[8], ex[9], ex[10], ex[11],
        ex[12], 10, 9999, 20260915, TOKENS, TOKENS,
    ]


def _modified_csv(source: str | Path, destination: Path) -> Path:
    lines = Path(source).read_text(encoding="utf-8").splitlines()
    row = lines[1].split(",")
    row[1] = repr(float(row[1]) + 1.0)
    lines[1] = ",".join(row)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _completed(session: str):
    request = gr.Request(session_hash=session)
    inspected = web.inspect_callback(*_args(), request=request)
    assert isinstance(inspected[5], web.WebPreparedState)
    analyzed = web.analyze_callback(inspected[5], True, request=request)
    assert isinstance(analyzed[7], web.WebCompletedState)
    return request, analyzed


def _fn_index(name: str) -> int:
    matches = [idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, "__name__", None) == name]
    assert matches, name
    return min(matches)


def _file_payload(path: str | Path, *, orig_name: str | None = None) -> dict[str, object]:
    p = Path(path)
    return {
        "path": str(p),
        "orig_name": orig_name or p.name,
        "meta": {"_type": "gradio.FileData"},
    }


def test_registered_restored_spec_enforces_recorded_dataset_hashes(tmp_path):
    async def run():
        args = _args()
        spec, _ = web._build_spec_and_overrides(*args)
        upload_root = Path(get_upload_folder())
        upload_root.mkdir(parents=True, exist_ok=True)
        spec_path = upload_root / "rc5_restored_hash_analysis.json"
        spec_path.write_text(spec.canonical_json(), encoding="utf-8")
        modified = _modified_csv(args[0], upload_root / "rc5_modified_a.csv")
        copied_b = upload_root / "rc5_dataset_b.csv"
        shutil.copyfile(args[1], copied_b)

        state = SessionState(web.demo)
        request = gr.Request(session_hash="rc5-restored-hash-process-api")
        loaded = await web.demo.process_api(
            _fn_index("load_spec_ui"), [_file_payload(spec_path, orig_name="analysis.json")], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert "will be enforced" in loaded["data"][-1]

        changed_args = list(args)
        changed_args[0] = _file_payload(modified, orig_name="dataset_a.csv")
        changed_args[1] = _file_payload(copied_b, orig_name="dataset_b.csv")
        inspected = await web.demo.process_api(
            _fn_index("inspect_ui"), changed_args, state=state,
            request=request, session_hash=request.session_hash,
        )
        assert "Inspection failed" in inspected["data"][0]
        assert "dataset identity mismatch" in inspected["data"][0].lower()
        assert inspected["data"][5] is None

    asyncio.run(run())


def test_restored_hash_accepts_relocated_identical_bytes_and_new_request_can_clear_identity(tmp_path):
    args = _args()
    spec, _ = web._build_spec_and_overrides(*args)
    spec_path = tmp_path / "analysis.json"
    spec_path.write_text(spec.canonical_json(), encoding="utf-8")
    request = gr.Request(session_hash="rc5-restored-hash-relocation")
    web.load_spec_ui(request, str(spec_path))

    relocated = tmp_path / "renamed_dataset_a.csv"
    shutil.copyfile(args[0], relocated)
    relocated_args = list(args)
    relocated_args[0] = str(relocated)
    ok = web.inspect_callback(*relocated_args, request=request)
    assert "Inspection failed" not in ok[0]
    assert isinstance(ok[5], web.WebPreparedState)

    modified = _modified_csv(args[0], tmp_path / "intentional_new_a.csv")
    changed_args = list(args)
    changed_args[0] = str(modified)
    blocked = web.inspect_callback(*changed_args, request=request)
    assert "dataset identity mismatch" in blocked[0].lower()

    note = web.clear_restored_identity_ui(request)
    assert "new AnalysisSpec" in note
    fresh = web.inspect_callback(*changed_args, request=request)
    assert "Inspection failed" not in fresh[0]
    assert isinstance(fresh[5], web.WebPreparedState)
    web.invalidate_run_state(request=request)


@pytest.mark.parametrize("kind", ["pair", "heatmap", "correlogram", "bubble", "matrix"])
def test_inflight_visualization_invalidation_cannot_recreate_or_publish_artifacts(monkeypatch, kind):
    request, analyzed = _completed(f"rc5-inflight-{kind}")
    cstate = analyzed[7]
    features_a = analyzed[8].value[:3]
    features_b = analyzed[9].value[:3]
    artifact_root = Path(cstate.artifact_root)
    assert artifact_root.exists()

    real_export = web.export_figure

    def invalidating_export(fig, root, stem):
        # Reproduce the RC4 race after the pre-export generation check. The real
        # exporter then recreates the deleted path unless the post-export guard
        # removes the stale work.
        web.invalidate_run_state(request=request)
        return real_export(fig, root, stem)

    monkeypatch.setattr(web, "export_figure", invalidating_export)

    if kind == "pair":
        result = web.plot_pair_callback(cstate, analyzed[6].value, "raw", request=request)
    elif kind == "heatmap":
        result = web.heatmap_callback(cstate, features_a, features_b, 0.05, True, request=request)
    elif kind == "correlogram":
        result = web.correlogram_callback(cstate, features_a, features_b, 0.05, request=request)
    elif kind == "bubble":
        result = web.bubble_callback(cstate, features_a, features_b, 0.05, "effect", request=request)
    else:
        result = web.scatter_matrix_callback(cstate, features_a[:2], features_b[:2], request=request)

    assert result[0] is None
    assert "superseded" in result[1].lower()
    assert result[2:] == (None, None, None)
    assert not artifact_root.exists()
    assert artifact_root not in web._SESSION_ARTIFACTS.get(request.session_hash, set())


def test_ui_publication_guard_suppresses_result_if_generation_changes_after_callback(monkeypatch):
    request, analyzed = _completed("rc5-ui-publication-guard")
    cstate = analyzed[7]

    def stale_callback(*args, **kwargs):
        web.invalidate_run_state(request=request)
        return object(), "stale", "/tmp/a.png", "/tmp/a.svg", "/tmp/a.pdf"

    monkeypatch.setattr(web, "heatmap_callback", stale_callback)
    result = web.heatmap_ui(request, cstate, ["x"], ["y"], 0.05, True)
    assert result[0] is None
    assert "superseded" in result[1].lower()
    assert result[2:] == (None, None, None)


def test_spearman_rank_view_preserves_supported_large_integer_distinctions_and_ties():
    aligned_a = pd.DataFrame({
        "x": pd.array([2**60, 2**60 + 1, 2**60 + 2, 2**60 + 3], dtype="Int64")
    })
    aligned_b = pd.DataFrame({"y": pd.array([1, 2, 3, 4], dtype="Int64")})
    data = pairwise_complete_data(aligned_a, aligned_b, "x", "y")
    assert data.x.dtype == np.dtype("int64")
    assert data.x.tolist() == [2**60, 2**60 + 1, 2**60 + 2, 2**60 + 3]

    fig = make_pair_figure(data, method="spearman", estimate=1.0, p_value=0.01, q_value=0.02, view="ranks")
    try:
        offsets = fig.axes[0].collections[0].get_offsets()
        assert offsets[:, 0].tolist() == [1.0, 2.0, 3.0, 4.0]
    finally:
        plt.close(fig)

    tied_a = pd.DataFrame({"x": pd.array([2**60, 2**60, 2**60 + 1, 2**60 + 2], dtype="Int64")})
    tied = pairwise_complete_data(tied_a, aligned_b, "x", "y")
    tied_fig = make_pair_figure(tied, method="spearman", estimate=0.9, p_value=0.02, q_value=0.03, view="ranks")
    try:
        offsets = tied_fig.axes[0].collections[0].get_offsets()
        assert offsets[:, 0].tolist() == [1.5, 1.5, 3.0, 4.0]
    finally:
        plt.close(tied_fig)

    with pytest.raises(ValueError, match="collapse distinct integer coordinates"):
        make_pair_figure(data, method="spearman", estimate=1.0, p_value=0.01, q_value=0.02, view="raw")


def test_long_figure_header_uses_rendered_extents_without_title_subtitle_plot_overlap():
    long_a = " ".join(["long identifier"] * 16)
    long_b = " ".join(["long identifier"] * 16)
    data = PairPlotData(
        feature_a=long_a, feature_b=long_b,
        x=np.arange(12, dtype=float), y=np.arange(12, dtype=float) * 1.3,
        n_pairwise=12, missing_or_excluded=0,
    )
    fig = make_pair_figure(data, method="pearson", estimate=0.91, p_value=1e-7, q_value=2e-6)
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        title_box = fig.texts[0].get_window_extent(renderer=renderer)
        subtitle_box = fig.texts[1].get_window_extent(renderer=renderer)
        axes_box = fig.axes[0].get_window_extent(renderer=renderer)
        assert title_box.y0 > subtitle_box.y1
        assert subtitle_box.y0 > axes_box.y1
    finally:
        plt.close(fig)


def _glyph_results() -> pd.DataFrame:
    return pd.DataFrame([
        {"feature_a": "A", "feature_b": "B0", "estimate": 0.0, "q_value": 0.5, "status": "ok"},
        {"feature_a": "A", "feature_b": "B1", "estimate": 0.5, "q_value": 0.04, "status": "ok"},
        {"feature_a": "A", "feature_b": "B2", "estimate": 1.0, "q_value": 0.001, "status": "ok"},
    ])


def test_correlogram_is_cell_based_and_bubble_copy_describes_encoding():
    results = _glyph_results()
    corr = make_correlogram_figure(results, ["A"], ["B0", "B1", "B2"])
    bubble = make_bubble_figure(results, ["A"], ["B0", "B1", "B2"], size_by="effect")
    evidence = make_bubble_figure(results, ["A"], ["B0", "B1", "B2"], size_by="evidence")
    try:
        corr_copy = corr.texts[1].get_text()
        assert "Color = correlation coefficient" in corr_copy
        assert "values printed in cells" in corr_copy
        assert "Marker area" not in corr_copy
        assert "Bubble area emphasizes |correlation|" in bubble.texts[1].get_text()
        assert "Bubble area emphasizes -log10(BH q), capped at 12" in evidence.texts[1].get_text()
    finally:
        plt.close(corr)
        plt.close(bubble)
        plt.close(evidence)


def test_svg_export_preserves_editable_text_elements(tmp_path):
    data = PairPlotData(
        feature_a="feature_a", feature_b="feature_b",
        x=np.arange(5, dtype=float), y=np.arange(5, dtype=float),
        n_pairwise=5, missing_or_excluded=0,
    )
    fig = make_pair_figure(data, method="pearson", estimate=1.0, p_value=0.01, q_value=0.02)
    try:
        _, svg, _ = export_figure(fig, tmp_path, "editable_text")
    finally:
        plt.close(fig)
    text = Path(svg).read_text(encoding="utf-8")
    assert "<text" in text
    assert "feature_a" in text
