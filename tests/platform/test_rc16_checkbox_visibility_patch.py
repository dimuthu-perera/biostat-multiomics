from biostat_tool import web


def test_rc16_checked_checkbox_forces_explicit_high_contrast_tick():
    css = web.APP_CSS
    assert "--biostat-checkbox-check:url(" in css
    assert "stroke%3D%22%23fff%22" in css
    assert "input[type='checkbox']:checked" in css
    assert "background-image:var(--biostat-checkbox-check) !important" in css
    assert "background-color:#238636 !important" in css
    assert "border-color:#86EFAC !important" in css


def test_rc16_dark_theme_overrides_gradio_checkbox_variables():
    css = web.APP_CSS
    assert "--checkbox-background-color-selected:#238636" in css
    assert "--checkbox-border-color-selected:#86EFAC" in css
    assert "--checkbox-check:var(--biostat-checkbox-check)" in css
    assert ".dark .gradio-container input[type='checkbox']:checked" in css


def test_rc16_keeps_visible_keyboard_focus_ring():
    css = web.APP_CSS
    assert "input[type='checkbox']:focus-visible" in css
    assert "outline:3px solid rgba(96,165,250,.48) !important" in css
