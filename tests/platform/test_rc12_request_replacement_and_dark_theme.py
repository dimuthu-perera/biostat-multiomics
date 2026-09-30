from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import gradio as gr
from gradio.state_holder import SessionState

import biostat_tool.web as web

TOKENS = ",NA,N/A,NaN,nan"


def _fn_index(name: str, *, first: bool = True) -> int:
    matches = [idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, "__name__", None) == name]
    assert matches, name
    return min(matches) if first else max(matches)


def _args_from_example(key: str):
    ex = web.load_example_callback(key)
    return [
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4],
        ex[6], ex[7].value, ex[8], ex[9], ex[10], ex[11], ex[12],
        10, 9999, 20260915, TOKENS, TOKENS,
    ]


def _complete_example(request: gr.Request, key: str = "metabolomics_proteomics"):
    args = _args_from_example(key)
    prepared = web.inspect_callback(*args, request=request)[5]
    analyzed = web.analyze_callback(prepared, True, request=request)
    assert "Analysis complete" in analyzed[0]
    return prepared, analyzed[7]


def test_example_replacement_supersedes_old_states_and_removes_artifacts():
    request = gr.Request(session_hash="rc12-example-replacement")
    prepared, completed = _complete_example(request)
    artifact_root = Path(completed.artifact_root)
    assert artifact_root.is_dir()
    old_generation = prepared.generation

    # Successful replacement is the single coordinated invalidation point.
    loaded = web.load_example_callback("rnaseq_raw_blocked", request=request)
    assert "Synthetic example loaded" in loaded[-1]
    assert web._current_generation(request) == old_generation + 1
    assert not artifact_root.exists()

    stale_analysis = web.analyze_callback(prepared, True, request=request)
    assert "superseded" in stale_analysis[0].lower()
    stale_plot = web.plot_pair_callback(completed, '["Prot_001", "Met_001"]', "raw", request=request)
    assert stale_plot[0] is None
    assert "obsolete" in stale_plot[1].lower()

    cleared = web.replacement_run_state_ui()
    assert cleared[0] is None  # prepared state
    assert cleared[1] is False  # acknowledgement
    assert cleared[7] is None  # completed state


def test_restore_replacement_supersedes_previous_request_and_sets_new_identity(tmp_path):
    request = gr.Request(session_hash="rc12-restore-replacement")
    prepared, completed = _complete_example(request)
    root = Path(completed.artifact_root)
    assert root.exists()

    # Build a different valid spec (Spearman) and restore it.
    args = _args_from_example("metabolomics_rnaseq")
    args[12] = "spearman"
    spec, _ = web._build_spec_and_overrides(*args)
    spec_path = tmp_path / "restored-analysis.json"
    spec_path.write_text(spec.canonical_json(), encoding="utf-8")

    output = web.load_spec_ui(request, str(spec_path))
    assert output[12] == "spearman"
    assert not root.exists()
    assert web._current_generation(request) == prepared.generation + 1
    restored = web._restored_identity(request)
    assert restored is not None
    assert restored.dataset_a_sha256 == spec.dataset_a.sha256.lower()

    stale = web.analyze_callback(prepared, True, request=request)
    assert "superseded" in stale[0].lower()


def test_request_replacement_invalidates_inflight_analysis(monkeypatch):
    request = gr.Request(session_hash="rc12-inflight-replacement")
    args = _args_from_example("metabolomics_proteomics")
    prepared = web.inspect_callback(*args, request=request)[5]

    entered = threading.Event()
    release = threading.Event()
    real_execute = web.execute_prepared

    def slow_execute(*a, **kw):
        entered.set()
        assert release.wait(timeout=10)
        return real_execute(*a, **kw)

    monkeypatch.setattr(web, "execute_prepared", slow_execute)
    holder: dict[str, tuple] = {}

    def worker():
        holder["result"] = web.analyze_callback(prepared, True, request=request)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=10)
    web.load_example_callback("rnaseq_raw_blocked", request=request)
    release.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert "superseded" in holder["result"][0].lower()


def test_registered_load_and_restore_have_success_cleanup_chain():
    deps = web.demo.config.get("dependencies", [])
    fns = web.demo.fns

    def deps_for(name: str):
        out = []
        for dep in deps:
            fn = fns.get(dep.get("id"))
            if getattr(getattr(fn, "fn", None), "__name__", None) == name:
                out.append(dep)
        return out

    loads = deps_for("load_example_callback")
    restores = deps_for("load_spec_ui")
    example_cleanup = deps_for("replacement_cleanup_for_example_ui")
    spec_cleanup = deps_for("replacement_cleanup_for_spec_ui")
    assert loads and restores and example_cleanup and spec_cleanup
    load_ids = {d["id"] for d in loads}
    restore_ids = {d["id"] for d in restores}
    assert any(d.get("trigger_after") in load_ids and d.get("targets") == [(None, "success")] for d in example_cleanup)
    assert any(d.get("trigger_after") in restore_ids and d.get("targets") == [(None, "success")] for d in spec_cleanup)

    # Clicking Restore without a file remains non-destructive (U12).
    skipped = web.replacement_cleanup_for_spec_ui(None)
    assert skipped and all(item == gr.skip() for item in skipped)


def test_dark_theme_uses_native_gradio_dark_class_and_full_surface_variables():
    assert "document.body.classList.toggle('dark', isDark)" in web.APP_JS
    assert "appRoot.parentElement.classList.toggle('dark', isDark)" in web.APP_JS
    for token in (
        "--block-background-fill:#111A2B",
        "--input-background-fill:#0F1A2C",
        "--accordion-text-color:#E6EDF5",
        "--button-secondary-background-fill:#172033",
        "--table-even-background-fill:#111A2B",
    ):
        assert token in web.APP_CSS
