from __future__ import annotations

from pathlib import Path

import gradio as gr
import pandas as pd
import pytest
from gradio.helpers import special_args

import biostat_tool.web as web

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def ui_args():
    return (
        str(FIX / "a.csv"), str(FIX / "b.csv"),
        "metabolomics", "quantitative", "", "samples_rows",
        "metabolomics", "quantitative", "", "samples_rows",
        "independent", "one sample per participant", "pearson", 3, 9999, 20260915,
    )


def test_registered_web_inspection_receives_real_request_and_uses_session_generation():
    web._SESSION_GENERATIONS.clear()
    indexes = {fn.fn.__name__: idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, "__name__", None)}
    assert "inspect_ui" in indexes
    request = gr.Request(session_hash="platform-session")

    import asyncio
    async def run():
        return await web.demo.call_function(indexes["inspect_ui"], list(ui_args()), requests=request)
    result = asyncio.run(run())
    assert "platform-session" in web._SESSION_GENERATIONS
    assert web._DIRECT_SESSION not in web._SESSION_GENERATIONS
    assert result["prediction"][5] is not None


def test_web_analysis_calls_central_execute_prepared(monkeypatch):
    web._SESSION_GENERATIONS.clear()
    request = gr.Request(session_hash="run-session")
    inspect_args, *_ = special_args(web.inspect_ui, list(ui_args()), request=request)
    state = web.inspect_ui(*inspect_args)[5]
    prepared = state.prepared
    called = False
    real = web.execute_prepared

    def wrapped(*args, **kwargs):
        nonlocal called
        called = True
        return real(*args, **kwargs)

    monkeypatch.setattr(web, "execute_prepared", wrapped)
    call_args, *_ = special_args(web.analyze_ui, [state, True], request=request)
    result = web.analyze_ui(*call_args)
    assert called is True
    assert "Analysis complete" in result[0]
    assert isinstance(result[1], pd.DataFrame)
    assert result[2] is not None


def test_invalidation_during_inspection_return_preparation_suppresses_state(monkeypatch):
    web._SESSION_GENERATIONS.clear()
    request = gr.Request(session_hash="inspection-race")
    indexes = {fn.fn.__name__: idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, "__name__", None)}
    real_metrics = web._metrics_df

    def invalidate_while_preparing(prepared):
        web.invalidate_ui(request)
        return real_metrics(prepared)

    monkeypatch.setattr(web, "_metrics_df", invalidate_while_preparing)
    import asyncio
    async def run():
        return await web.demo.call_function(indexes["inspect_ui"], list(ui_args()), requests=request)
    result = asyncio.run(run())
    prediction = result["prediction"]
    assert "superseded" in prediction[0].lower()
    assert prediction[5] is None
    assert prediction[8] is None


def test_obsolete_web_prepared_state_cannot_be_analyzed_after_invalidation():
    web._SESSION_GENERATIONS.clear()
    request = gr.Request(session_hash="stale-prepared")
    inspect_args, *_ = special_args(web.inspect_ui, list(ui_args()), request=request)
    state = web.inspect_ui(*inspect_args)[5]
    assert isinstance(state, web.WebPreparedState)
    web.invalidate_ui(request)
    analyze_args, *_ = special_args(web.analyze_ui, [state, True], request=request)
    result = web.analyze_ui(*analyze_args)
    assert "superseded" in result[0].lower()
    assert result[2] is None
