from __future__ import annotations

import asyncio

from gradio.state_holder import SessionState

import biostat_tool.web as web


def _deps_for(name: str):
    deps = []
    for dep in web.demo.config.get("dependencies", []):
        fn = web.demo.fns.get(dep.get("id"))
        fn_name = getattr(getattr(fn, "fn", None), "__name__", None) if fn else None
        if fn_name == name:
            deps.append(dep)
    return deps


def test_example_population_does_not_use_change_based_invalidation_listeners():
    load_deps = _deps_for("load_example_callback")
    assert load_deps
    example_outputs = set(load_deps[0]["outputs"])

    invalidators = {
        "invalidate_ui",
        "clear_visual_ui",
        "invalidate_guidance_ui",
        "clear_pair_feature_ui",
        "invalidate_all_user_edit_ui",
    }
    bad = []
    observed_user_events = set()
    for name in invalidators:
        for dep in _deps_for(name):
            for component_id, event_name in dep.get("targets", []):
                if component_id in example_outputs:
                    observed_user_events.add(event_name)
                    if event_name == "change":
                        bad.append((name, component_id, event_name))

    assert not bad, f"programmatic example outputs still trigger change invalidation: {bad}"
    # Form fields use input; File uses upload/delete/clear in Gradio 6.5.
    assert "input" in observed_user_events
    assert "upload" in observed_user_events


def test_registered_example_load_completes_as_one_coherent_request():
    async def run() -> None:
        dep = _deps_for("load_example_callback")[0]
        session = SessionState(web.demo)
        result = await web.demo.process_api(
            dep["id"],
            ["metabolomics_rnaseq"],
            state=session,
        )
        data = result["data"]
        assert len(data) == len(dep["outputs"])
        assert "Synthetic example loaded" in data[-1]
        # The example callback itself should not return a pending/streaming response.
        assert result.get("is_generating") is False

    asyncio.run(run())
