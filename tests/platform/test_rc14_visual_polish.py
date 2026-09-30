from __future__ import annotations

import gradio as gr

import biostat_tool.web as web


def _blocks_of_type(cls):
    return [b for b in web.demo.blocks.values() if isinstance(b, cls)]


def test_rc14_header_has_more_vertical_space_and_non_overlapping_theme_grid():
    assert "#biostat-header {" in web.APP_CSS
    assert "padding:22px 24px" in web.APP_CSS
    assert "display:grid; grid-template-columns:minmax(0,1fr) auto" in web.APP_CSS
    assert ".biostat-theme-switcher { grid-column:1 / -1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr))" in web.APP_CSS
    assert ".biostat-header-actions { position:static; display:grid" in web.APP_CSS


def test_rc14_dark_status_surfaces_force_readable_text():
    assert "background:#153B2A !important; color:#F1FFF6 !important" in web.APP_CSS
    assert ".biostat-example-status *" in web.APP_CSS
    assert ".legend-chip[class*='status-'] *, .readiness-banner *, .analysis-gate * { color:inherit !important; }" in web.APP_CSS
    assert "--status-bg:#17365F; --status-text:#EFF6FF" in web.APP_CSS
    assert "--status-bg:#463014; --status-text:#FFF4CC" in web.APP_CSS


def test_rc14_narrow_open_sidebar_offsets_workspace_instead_of_covering_it():
    assert "@media (max-width: 768px)" in web.APP_CSS
    assert ".gradio-container:has(.biostat-workstation-sidebar.open) #biostat-header" in web.APP_CSS
    assert ".gradio-container:has(.biostat-workstation-sidebar.open) #biostat-main-tabs" in web.APP_CSS
    assert "margin-left:247px !important; width:calc(100% - 247px) !important" in web.APP_CSS


def test_rc14_figure_controls_are_context_sensitive():
    association = web.figure_controls_visibility_ui("association")
    heatmap = web.figure_controls_visibility_ui("heatmap")
    correlogram = web.figure_controls_visibility_ui("correlogram")
    bubble = web.figure_controls_visibility_ui("bubble")
    scatter = web.figure_controls_visibility_ui("scatter")

    def vis(values):
        return tuple(v.get("visible") for v in values)

    assert vis(association) == (True, False, False, False, False)
    assert vis(heatmap) == (False, True, True, True, False)
    assert vis(correlogram) == (False, True, True, False, False)
    assert vis(bubble) == (False, True, True, False, True)
    assert vis(scatter) == (False, True, False, False, False)

    groups = _blocks_of_type(gr.Group)
    assert any(getattr(g, "visible", None) is True for g in groups)
    assert sum(getattr(g, "visible", None) is False for g in groups) >= 4


def test_rc14_readiness_table_uses_identical_fixed_column_contract_for_header_and_body():
    for index, width in [(1, 140), (2, 140), (3, 230), (4, 320), (5, 700)]:
        needle = f".biostat-issues-table th:nth-child({index}), .biostat-issues-table td:nth-child({index}) {{ width:{width}px !important; min-width:{width}px !important; max-width:{width}px !important; }}"
        assert needle in web.APP_CSS
    assert "width:1530px !important; min-width:1530px !important" in web.APP_CSS


def test_rc14_batch_report_has_unambiguous_primary_generate_button():
    buttons = [b for b in _blocks_of_type(gr.Button) if getattr(b, "value", None) == "Generate report"]
    assert len(buttons) == 1
    button = buttons[0]
    assert getattr(button, "variant", None) == "primary"
    assert "batch-report-action" in (getattr(button, "elem_classes", None) or [])
    assert ".batch-report-action button" in web.APP_CSS
