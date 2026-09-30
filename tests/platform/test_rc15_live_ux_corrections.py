from __future__ import annotations

import gradio as gr
import pandas as pd

import biostat_tool.web as web


def _blocks_of_type(cls):
    return [b for b in web.demo.blocks.values() if isinstance(b, cls)]


def _find_component(cls, *, label=None, value=None):
    for block in _blocks_of_type(cls):
        if label is not None and getattr(block, "label", None) != label:
            continue
        if value is not None and getattr(block, "value", None) != value:
            continue
        return block
    raise AssertionError(f"component not found: {cls.__name__} label={label!r} value={value!r}")


def _ancestor_tab(block):
    current = block
    while current is not None:
        if isinstance(current, gr.Tab):
            return current
        current = getattr(current, "parent", None)
    return None


def test_rc15_supported_matrix_scope_visual_names_all_supported_modalities():
    text = web.OMICS_SCOPE_HTML
    for label in ["Metabolomics", "Proteomics", "RNA-seq", "16S", "Microbiome", "Metagenomics", "Biomarkers"]:
        assert label in text
    assert "Same-domain and cross-domain" in text
    assert "<svg" in text


def test_rc15_dark_success_surface_overrides_inner_gradio_markdown_background():
    assert "html.biostat-dark .biostat-example-status > div" in web.APP_CSS
    assert "html.biostat-dark .biostat-example-status .prose" in web.APP_CSS
    assert "background:#153B2A !important; color:#F1FFF6 !important" in web.APP_CSS


def test_rc15_missing_token_ui_is_human_readable_but_blank_remains_canonical():
    assert web.DEFAULT_MISSING_TOKEN_TEXT == "NA,N/A,NaN,nan"
    assert not web.DEFAULT_MISSING_TOKEN_TEXT.startswith(",")
    assert web._parse_missing_tokens(web.DEFAULT_MISSING_TOKEN_TEXT) == ("", "NA", "N/A", "NaN", "nan")
    assert "Blank/empty cells are always interpreted as missing" in web.MISSING_TOKEN_HELP


def test_rc15_dataset_declarations_use_compact_two_column_rows():
    assert ".biostat-declaration-row" in web.APP_CSS
    assert ".biostat-dataset-card" in web.APP_CSS
    assert "Blank/empty cells are always treated as missing" in web.demo.get_config_file().__str__()


def test_rc15_minimum_pairwise_n_has_browser_bounds_matching_backend_contract():
    component = _find_component(gr.Number, label="Minimum pairwise N")
    assert component.minimum == 3
    assert component.maximum is None
    assert component.step == 1
    assert component.precision == 0
    assert "Minimum: 3" in str(component.info)
    assert "Recommended starting value: 10" in str(component.info)


def test_rc15_spearman_pairings_has_browser_bounds_matching_scalar_contract():
    component = _find_component(gr.Number, label="Spearman Monte Carlo pairings")
    assert component.minimum == 99
    assert component.maximum == 100000
    assert component.step == 1
    assert component.precision == 0
    assert "99–100,000" in str(component.info)
    assert "9,999" in str(component.info)


def test_rc15_inspection_primary_action_is_in_data_tab_and_reinspect_is_in_readiness():
    inspect = _find_component(gr.Button, value="Inspect & validate inputs →")
    reinspect = _find_component(gr.Button, value="Re-run inspection")
    assert _ancestor_tab(inspect).label == "Data & design"
    assert _ancestor_tab(reinspect).label == "Readiness"


def test_rc15_user_edit_invalidation_is_single_unqueued_backend_callback():
    minimum_n = _find_component(gr.Number, label="Minimum pairwise N")
    matching = []
    for dep in web.demo.config["dependencies"]:
        targets = dep.get("targets") or []
        if any(isinstance(t, (list, tuple)) and len(t) >= 2 and t[0] == minimum_n._id and t[1] == "input" for t in targets):
            matching.append(dep)
    backend_callbacks = [dep for dep in matching if dep.get("backend_fn")]
    assert len(backend_callbacks) == 1
    dep = backend_callbacks[0]
    assert dep["queue"] is False
    assert dep["show_progress"] == "hidden"
    assert dep["trigger_mode"] == "always_last"
    assert str(dep["api_name"]).startswith("invalidate_all_user_edit_ui")


def test_rc15_workspace_offset_applies_to_header_and_main_tabs_when_rail_open():
    assert ".gradio-container:has(.biostat-workstation-sidebar.open) #biostat-header" in web.APP_CSS
    assert ".gradio-container:has(.biostat-workstation-sidebar.open) #biostat-main-tabs" in web.APP_CSS
    assert "margin-left:247px !important; width:calc(100% - 247px) !important" in web.APP_CSS


def test_rc15_dark_checkbox_selected_state_uses_high_contrast_accent():
    assert "input[type='checkbox']" in web.APP_CSS
    assert "accent-color:#4ADE80 !important" in web.APP_CSS
    assert "input[type='checkbox']:focus-visible" in web.APP_CSS


def test_rc15_browser_preview_rounds_only_display_values_and_keeps_source_frame_exact():
    full = pd.DataFrame([
        {
            "feature_a": "A", "feature_b": "B", "method": "spearman",
            "estimate": 0.3583919362, "n_pairwise": 20,
            "p_value": 0.0001, "q_value": 0.1399999999, "status": "ok",
            "p_value_method": "technical_method",
        },
        {
            "feature_a": "C", "feature_b": "D", "method": "pearson",
            "estimate": -0.2511251758, "n_pairwise": 19,
            "p_value": 0.0104, "q_value": 0.6216666667, "status": "ok",
            "p_value_method": "technical_method",
        },
    ])
    exact = full.copy(deep=True)
    preview = web._result_preview_df(full)
    assert preview.iloc[0]["Correlation"] == "0.36"
    assert preview.iloc[0]["p-value"] == "<0.001"
    assert preview.iloc[0]["BH q-value"] == "0.140"
    assert preview.iloc[1]["Correlation"] == "-0.25"
    assert preview.iloc[1]["p-value"] == "0.010"
    assert preview.iloc[1]["BH q-value"] == "0.622"
    pd.testing.assert_frame_equal(full, exact, check_exact=True)


def test_rc15_nih_reproducibility_panel_uses_text_citation_without_logo_asset():
    panel = web.NIH_REPRODUCIBILITY_HTML
    assert "Two of the cornerstones of science advancement" in panel
    assert "https://grants.nih.gov/policy-and-compliance/policy-topics/reproducibility" in panel
    assert "NIH does not endorse, certify, or validate this software" in panel
    assert "<img" not in panel.lower()
    assert "nih logo" in panel.lower()  # explicit explanation that the logo is intentionally not used


def test_rc15_researcher_facing_computation_language_hides_backend_ids_from_header():
    html_values = [
        getattr(b, "value", "") for b in _blocks_of_type(gr.HTML)
        if isinstance(getattr(b, "value", ""), str)
    ]
    header = next(v for v in html_values if "id='biostat-header'" in v)
    assert "Computation: Automatic" in header
    assert "Backend: auto" not in header
    assert web._computation_engine_display("optimized_spearman_v0.4.2") == "Computation engine: Optimized."
    assert web._computation_engine_display("reference_scalar_v0.2.4") == "Computation engine: Reference."
    fallback = web._computation_engine_display("reference_scalar_v0.2.4", "missingness")
    assert "Automatic selection used the reference engine" in fallback
