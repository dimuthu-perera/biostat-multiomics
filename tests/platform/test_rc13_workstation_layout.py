from __future__ import annotations

import gradio as gr
import pandas as pd

import biostat_tool.web as web


def _blocks_of_type(cls):
    return [b for b in web.demo.blocks.values() if isinstance(b, cls)]


def test_rc13_workstation_sidebar_and_hidden_main_tabs_present():
    sidebars = _blocks_of_type(gr.Sidebar)
    assert sidebars, "expected workstation sidebar"
    assert any(getattr(s, "width", None) == 235 for s in sidebars)

    main_tabs = [b for b in _blocks_of_type(gr.Tabs) if getattr(b, "elem_id", None) == "biostat-main-tabs"]
    assert len(main_tabs) == 1
    assert main_tabs[0].selected == "data"
    assert "biostat-workstation-tabs > .tab-nav" in web.APP_CSS

    buttons = {getattr(b, "value", None): b for b in _blocks_of_type(gr.Button)}
    for label in [
        "1  Data & design", "2  Readiness", "3  Analysis", "4  Results",
        "5  Figures", "6  Provenance", "Quick start", "Video tutorials",
        "Documentation", "About",
    ]:
        assert label in buttons


def test_rc13_header_help_about_and_theme_use_workstation_targets():
    html_values = [getattr(b, "value", "") for b in _blocks_of_type(gr.HTML)]
    header = next(v for v in html_values if isinstance(v, str) and "id='biostat-header'" in v)
    assert "data-biostat-jump='biostat-nav-quickstart'" in header
    assert "data-biostat-jump='biostat-nav-about'" in header
    assert "☀ Light" in header and "☾ Dark" in header and "◐ System" in header
    assert "appRoot.classList.toggle('dark', isDark)" in web.APP_JS


def test_rc13_dark_theme_is_two_tone_and_not_white_panel_based():
    assert "--biostat-bg:#0B1220" in web.APP_CSS
    assert "--biostat-card:#121D2F" in web.APP_CSS
    assert "--biostat-panel-2:#18263A" in web.APP_CSS
    assert "background:#121D2F !important" in web.APP_CSS
    assert "background:#0F192A !important" in web.APP_CSS


def test_rc13_result_preview_is_curated_for_browser_readability():
    full = pd.DataFrame([
        {
            "feature_a": "A", "feature_b": "B", "method": "spearman",
            "estimate": 0.4, "n_pairwise": 20, "p_value": 0.01,
            "q_value": 0.02, "status": "ok", "p_value_method": "technical_method",
            "numeric_1_warning": "warning", "monte_carlo_floor": 0.0001,
        }
    ])
    preview = web._result_preview_df(full)
    assert list(preview.columns) == [
        "Feature A", "Feature B", "Method", "Correlation", "Pairwise N",
        "p-value", "BH q-value", "Status",
    ]
    assert "technical_method" not in preview.to_string()
    assert "biostat-results-preview th" in web.APP_CSS


def test_rc13_figures_use_control_sidebar_and_large_stage():
    assert "biostat-figure-workstation" in web.APP_CSS
    assert "biostat-figure-controls" in web.APP_CSS
    assert "biostat-figure-stage" in web.APP_CSS
    columns = _blocks_of_type(gr.Column)
    assert any("biostat-figure-controls" in (getattr(c, "elem_classes", None) or []) for c in columns)
    assert any("biostat-figure-stage" in (getattr(c, "elem_classes", None) or []) for c in columns)


def test_rc13_learn_about_content_and_video_slots_are_present_without_invented_links():
    markdown = "\n".join(
        str(getattr(b, "value", "")) for b in _blocks_of_type(gr.Markdown)
        if isinstance(getattr(b, "value", ""), str)
    )
    html_values = "\n".join(
        str(getattr(b, "value", "")) for b in _blocks_of_type(gr.HTML)
        if isinstance(getattr(b, "value", ""), str)
    )
    assert "About Biostat Research Tool" in markdown
    assert "Quick start" in markdown
    assert "Video tutorials" in markdown
    assert "Documentation" in markdown
    assert "Link pending" in html_values
    assert "youtube.com" not in html_values.lower()
    assert "youtu.be" not in html_values.lower()


def test_rc13_completed_analysis_browser_preview_is_curated_but_csv_is_complete():
    request = gr.Request(session_hash="rc13-preview-contract")
    ex = web.load_example_callback("metabolomics_proteomics")
    args = [
        ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4],
        ex[6], ex[7].value, ex[8], ex[9], ex[10], ex[11],
        ex[12], 10, 9999, 20260915, ",NA,N/A,NaN,nan", ",NA,N/A,NaN,nan",
    ]
    inspected = web.inspect_callback(*args, request=request)
    analyzed = web.analyze_callback(inspected[5], True, request=request)
    try:
        browser_preview = analyzed[1]
        assert list(browser_preview.columns) == [
            "Feature A", "Feature B", "Method", "Correlation", "Pairwise N",
            "p-value", "BH q-value", "Status",
        ]
        csv_path = analyzed[4]
        complete = pd.read_csv(csv_path)
        assert "p_value_method" in complete.columns
        assert "monte_carlo_floor" in complete.columns
    finally:
        web.invalidate_run_state(request=request)
