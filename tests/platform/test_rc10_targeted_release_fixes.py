from __future__ import annotations

import asyncio
import json
from pathlib import Path

import gradio as gr
from gradio.state_holder import SessionState
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import biostat_tool.web as web
from biostat_tool.visualization import make_bubble_figure, make_correlogram_figure

TOKENS = ",NA,N/A,NaN,nan"


def _fn_index(name: str, *, first: bool = True) -> int:
    matches = [idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, "__name__", None) == name]
    assert matches, name
    return min(matches) if first else max(matches)


def _write_matrix(path: Path, prefix: str, values: np.ndarray) -> None:
    frame = pd.DataFrame(values, columns=[f"{prefix}{i:02d}" for i in range(values.shape[1])])
    frame.insert(0, "id", [f"S{i:02d}" for i in range(values.shape[0])])
    frame.to_csv(path, index=False)


def test_bubble_positive_q_ordinate_is_not_capped_by_marker_size_policy():
    results = pd.DataFrame(
        [
            {"feature_a": "A1", "feature_b": "B1", "estimate": 0.2, "q_value": 1e-6, "status": "ok"},
            {"feature_a": "A2", "feature_b": "B1", "estimate": 0.9, "q_value": 1e-20, "status": "ok"},
            {"feature_a": "A3", "feature_b": "B1", "estimate": -0.5, "q_value": 0.0, "status": "ok"},
        ]
    )
    fig = make_bubble_figure(results, ["A1", "A2", "A3"], ["B1"], size_by="evidence")
    try:
        offsets = np.asarray(fig.axes[0].collections[0].get_offsets(), dtype=float)
        assert np.isclose(offsets[0, 1], 6.0)
        assert np.isclose(offsets[1, 1], 20.0)
        # q == 0 has no finite exact ordinate; it is explicitly placed above
        # the strongest positive-q point and disclosed in the subtitle.
        assert offsets[2, 1] > 20.0
        subtitle = fig.texts[1].get_text()
        assert "BH q = 0 points are displayed" in subtitle
        sizes = fig.axes[0].collections[0].get_sizes()
        assert np.isclose(sizes[1], sizes[2])  # marker sizing remains capped independently
    finally:
        plt.close(fig)


def test_cross_dataset_matching_names_never_trigger_triangle_without_verified_identity():
    results = pd.DataFrame(
        [
            {"feature_a": "x", "feature_b": "x", "estimate": 0.5, "q_value": 0.01, "status": "ok"},
            {"feature_a": "x", "feature_b": "y", "estimate": 0.2, "q_value": 0.02, "status": "ok"},
            {"feature_a": "y", "feature_b": "x", "estimate": 0.2, "q_value": 0.03, "status": "ok"},
            {"feature_a": "y", "feature_b": "y", "estimate": 0.5, "q_value": 0.04, "status": "ok"},
        ]
    )
    cross = make_correlogram_figure(results, ["x", "y"], ["x", "y"])
    same = make_correlogram_figure(
        results, ["x", "y"], ["x", "y"], same_variable_space=True
    )
    try:
        cross_array = np.ma.asarray(cross.axes[0].images[0].get_array())
        same_array = np.ma.asarray(same.axes[0].images[0].get_array())
        assert int(np.ma.count(cross_array)) == 4
        assert int(np.ma.count(same_array)) == 3
    finally:
        plt.close(cross)
        plt.close(same)


def test_two_stage_pair_selection_can_render_pair_beyond_quick_search_cap(tmp_path):
    async def run() -> None:
        rng = np.random.default_rng(74)
        a = rng.standard_normal((20, 71))
        b = rng.standard_normal((20, 71))
        upload_root = web._new_browser_artifact_root("rc10_pair_inputs_")
        a_path = upload_root / "a.csv"
        b_path = upload_root / "b.csv"
        _write_matrix(a_path, "a", a)
        _write_matrix(b_path, "b", b)
        file_a = {"path": str(a_path), "orig_name": "a.csv", "size": a_path.stat().st_size, "meta": {"_type": "gradio.FileData"}}
        file_b = {"path": str(b_path), "orig_name": "b.csv", "size": b_path.stat().st_size, "meta": {"_type": "gradio.FileData"}}

        state = SessionState(web.demo)
        request = gr.Request(session_hash="rc10-over-5000-pair")
        inspect_args = [
            file_a, file_b,
            "generic", "declared_numeric", "", "samples_rows",
            "generic", "declared_numeric", "", "samples_rows",
            "independent", "", "pearson", 10, 9999, 20260915,
            TOKENS, TOKENS,
        ]
        inspected = await web.demo.process_api(
            _fn_index("inspect_ui"), inspect_args, state=state,
            request=request, session_hash=request.session_hash,
        )
        assert "Inspection failed" not in inspected["data"][0]
        analyzed = await web.demo.process_api(
            _fn_index("analyze_ui"), [None, True], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert "Analysis complete" in analyzed["data"][0]
        assert len(analyzed["data"][6]["choices"]) == 5000

        # Exercise the registered two-stage callbacks. a70|b70 is beyond the
        # 5,000-pair quick-search population in the deterministic A-major result order.
        controls = await web.demo.process_api(
            _fn_index("pair_feature_controls_ui"), [None], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert any(choice[1] == "a70" for choice in controls["data"][0]["choices"])
        b_update = await web.demo.process_api(
            _fn_index("pair_feature_b_ui"), [None, "a70"], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert any(choice[1] == "b70" for choice in b_update["data"][0]["choices"])

        selector = await web.demo.process_api(
            _fn_index("pair_selector_from_features"), ["a70", "b70"], state=state,
            request=request, session_hash=request.session_hash,
        )
        encoded = selector["data"][0]
        assert json.loads(encoded) == ["a70", "b70"]

        rendered = await web.demo.process_api(
            _fn_index("plot_pair_ui"), [None, encoded, "raw"], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert rendered["data"][0] is not None
        assert Path(rendered["data"][2]["path"]).is_file()
        web.invalidate_run_state(request=request)

    asyncio.run(run())


def test_batch_report_outputs_clear_and_files_are_removed_after_invalidation():
    request = gr.Request(session_hash="rc10-batch-clear")
    ex = web.load_example_callback("metabolomics_proteomics")
    args = [
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4],
        ex[6], ex[7].value, ex[8], ex[9], ex[10], ex[11], ex[12],
        10, 9999, 20260915, TOKENS, TOKENS,
    ]
    prepared = web.inspect_callback(*args, request=request)[5]
    analyzed = web.analyze_callback(prepared, True, request=request)
    cstate = analyzed[7]
    meta, pdf, archive = web.association_report_callback(cstate, 10, "q_value", request=request)
    assert "Generated 10 association pages" in meta
    paths = [Path(pdf), Path(archive)]
    assert all(path.is_file() for path in paths)

    web.invalidate_run_state(request=request)
    assert all(not path.exists() for path in paths)

    cleared = web.clear_visual_ui()
    assert cleared[-3:] == ("", None, None)
