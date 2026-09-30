from __future__ import annotations

import html as _html

import gradio as gr

import biostat_tool.web as web


def _blocks_of_type(cls):
    return [b for b in web.demo.blocks.values() if isinstance(b, cls)]


def test_help_label_is_accessible_hover_focus_tap_markup_and_escapes_copy():
    markup = web._help_label('Correlation <method>', 'Use A&B < carefully')
    assert '<details' in markup
    assert '<summary' in markup
    assert "aria-label='Help for Correlation &lt;method&gt;'" in markup
    assert "role='tooltip'" in markup
    assert _html.escape('Use A&B < carefully') in markup
    assert 'biostat-help:hover .biostat-tooltip' in web.APP_CSS
    assert 'biostat-help:focus-within .biostat-tooltip' in web.APP_CSS
    assert 'biostat-help[open] .biostat-tooltip' in web.APP_CSS


def test_guided_workflow_and_key_action_labels_are_present():
    for step, text in [
        ('1', 'Load data'),
        ('2', 'Inspect readiness'),
        ('3', 'Run analysis'),
        ('4', 'Review results'),
        ('5', 'Create figures'),
        ('6', 'Verify provenance'),
    ]:
        assert f'<b>{step}</b><span>{step}. {text}</span>' in web.WORKFLOW_GUIDE_HTML

    button_values = {getattr(b, 'value', None) for b in _blocks_of_type(gr.Button)}
    assert '1. Load selected example' in button_values
    assert 'Inspect & validate inputs →' in button_values
    assert '3. Run inspected analysis' in button_values


def test_help_enabled_controls_keep_semantic_labels_but_hide_duplicate_visual_label():
    expected = {
        'Matrix A', 'Matrix B', 'Data type', 'Preprocessing state', 'Orientation',
        'Observation structure', 'Correlation method', 'Minimum pairwise N',
        'Spearman Monte Carlo pairings', 'Random seed', 'Visual q threshold', 'Bubble size',
    }
    found = set()
    for block in web.demo.blocks.values():
        label = getattr(block, 'label', None)
        if label in expected:
            found.add(label)
            assert getattr(block, 'show_label', None) is False
    assert expected <= found


def test_example_loaded_state_is_unmistakable_without_changing_callback_contract():
    result = web.load_example_callback('metabolomics_rnaseq')
    assert len(result) == 14
    assert result[-1].startswith('✅ **Synthetic example loaded:**')
    assert 'completely synthetic' in result[-1].lower()


def test_visual_workspace_explains_render_flow_and_labels_every_figure_download_group():
    html_values = [
        getattr(b, 'value', '') for b in _blocks_of_type(gr.HTML)
        if isinstance(getattr(b, 'value', ''), str)
    ]
    assert any('No figure yet?' in value for value in html_values)
    assert sum('Download this figure' in value for value in html_values) == 5

    help_markup = '\n'.join(v for v in html_values if 'biostat-help-label' in v)
    for phrase in [
        'Correlation method', 'Minimum pairwise N', 'Spearman Monte Carlo pairings',
        'Visual q threshold', 'Bubble size', 'Verified RunBundle',
    ]:
        assert phrase in help_markup
