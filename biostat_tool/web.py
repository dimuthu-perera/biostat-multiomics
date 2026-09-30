from __future__ import annotations

from dataclasses import dataclass, replace
import atexit
import json
import html
from functools import lru_cache
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Optional

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

# Keep Gradio's default cache private to this Biostat process so uploaded files
# and downloadable artifacts have a defined local retention boundary. Operators
# who explicitly set GRADIO_TEMP_DIR retain responsibility for that directory.
_OWNED_GRADIO_CACHE: Path | None = None
if "GRADIO_TEMP_DIR" not in os.environ:
    _OWNED_GRADIO_CACHE = Path(tempfile.mkdtemp(prefix="biostat_gradio_"))
    os.environ["GRADIO_TEMP_DIR"] = str(_OWNED_GRADIO_CACHE)

def _cleanup_owned_gradio_cache() -> None:
    if _OWNED_GRADIO_CACHE is not None:
        shutil.rmtree(_OWNED_GRADIO_CACHE, ignore_errors=True)

atexit.register(_cleanup_owned_gradio_cache)

import gradio as gr
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from gradio.utils import get_upload_folder

from correlation_tool import sha256_file

from . import __version__
from .bundle import default_run_directory, write_run_bundle, zip_run_bundle
from .examples import example_choices, get_example, teaching_plot_presets
from .runner import PreparedAnalysis, execute_prepared, prepare_analysis
from .specs import AnalysisSpec, CorrelationSpec, DatasetSpec, OutputSpec, ReviewSpec, StudyDesignSpec, load_analysis_spec
from .resource_limits import assess_resources, resource_markdown, RESULT_PREVIEW_ROWS
from .visualization import (
    pairwise_complete_data, make_pair_figure, export_pair_figure, export_figure,
    make_heatmap_figure, make_correlogram_figure, make_bubble_figure, make_scatter_matrix_figure,
    SCATTER_MATRIX_MAX_VARIABLES, HEATMAP_MAX_PER_AXIS, CORRELOGRAM_MAX_PER_AXIS, BUBBLE_MAX_POINTS,
)

DATA_TYPES = ["metabolomics", "rna_seq", "metagenomics", "16s", "proteomics", "generic"]
DATA_TYPE_LABELS = {
    "metabolomics": "Metabolomics",
    "rna_seq": "RNA-seq",
    "metagenomics": "Metagenomics",
    "16s": "16S",
    "proteomics": "Proteomics",
    "generic": "Generic quantitative data",
}
DATA_TYPE_CHOICES = [(DATA_TYPE_LABELS[value], value) for value in DATA_TYPES]
PREPROCESSING_BY_TYPE = {
    "metabolomics": ["unknown", "quantitative", "normalized", "log_transformed", "scaled", "other_transformed"],
    "rna_seq": ["unknown", "raw_counts", "normalized_counts", "tpm", "fpkm", "cpm", "vst", "rlog", "log_cpm", "other_transformed"],
    "metagenomics": ["unknown", "raw_counts", "normalized_counts", "relative_abundance", "clr", "other_transformed"],
    "16s": ["unknown", "raw_counts", "normalized_counts", "relative_abundance", "clr", "other_transformed"],
    "proteomics": ["unknown", "quantitative", "normalized", "log_transformed", "scaled", "other_transformed"],
    "generic": ["unknown", "declared_numeric", "other_transformed"],
}
PREPROCESSING_LABELS = {
    "unknown": "Unknown / not declared",
    "quantitative": "Quantitative",
    "normalized": "Normalized",
    "log_transformed": "Log transformed",
    "scaled": "Scaled",
    "other_transformed": "Other transformed values",
    "raw_counts": "Raw counts",
    "normalized_counts": "Normalized counts",
    "tpm": "TPM",
    "fpkm": "FPKM",
    "cpm": "CPM",
    "vst": "Variance-stabilizing transformation (VST)",
    "rlog": "Regularized log (rlog)",
    "log_cpm": "Log CPM",
    "relative_abundance": "Relative abundance",
    "clr": "Centered log-ratio (CLR)",
    "declared_numeric": "Declared numeric values",
}
DEFAULT_PREPROCESSING = {
    "metabolomics": "quantitative",
    "rna_seq": "vst",
    "metagenomics": "clr",
    "16s": "clr",
    "proteomics": "quantitative",
    "generic": "declared_numeric",
}
# Gradio validates submitted dropdown values against the component's server-side
# constructor choices, while dynamic component updates primarily change the
# browser state. Keep the server acceptance domain as the union of all supported
# preprocessing states; browser updates still narrow the visible choices for the
# selected omics profile. The AnalysisSpec validator remains the scientific
# authority for whether a data-type/preprocessing combination is permitted.
ALL_PREPROCESSING = list(dict.fromkeys(
    value for data_type in DATA_TYPES for value in PREPROCESSING_BY_TYPE[data_type]
))
ALL_PREPROCESSING_CHOICES = [(PREPROCESSING_LABELS.get(value, value.replace("_", " ").title()), value) for value in ALL_PREPROCESSING]
ORIENTATIONS = ["samples_rows", "samples_columns"]
ORIENTATION_CHOICES = [("Samples in rows", "samples_rows"), ("Samples in columns", "samples_columns")]
DESIGNS = ["unknown", "independent", "dependent_or_clustered"]
DESIGN_CHOICES = [("Unknown / not declared", "unknown"), ("Independent observations", "independent"), ("Dependent or clustered observations", "dependent_or_clustered")]
METHODS = ["spearman", "pearson"]
METHOD_CHOICES = [("Spearman rank correlation", "spearman"), ("Pearson correlation", "pearson")]
DEFAULT_MISSING_TOKENS = ("", "NA", "N/A", "NaN", "nan")
DEFAULT_MISSING_TOKEN_TEXT = ",".join(token for token in DEFAULT_MISSING_TOKENS if token)
MISSING_TOKEN_HELP = "Blank/empty cells are always interpreted as missing. Add any other literal missing-value tokens here as a comma-separated list. Do not add censoring codes such as <LOD unless that is scientifically intended."

RESULT_PREVIEW_COLUMNS = [
    "feature_a", "feature_b", "method", "estimate", "n_pairwise", "p_value", "q_value", "status",
]
RESULT_PREVIEW_LABELS = {
    "feature_a": "Feature A",
    "feature_b": "Feature B",
    "method": "Method",
    "estimate": "Correlation",
    "n_pairwise": "Pairwise N",
    "p_value": "p-value",
    "q_value": "BH q-value",
    "status": "Status",
}


def _format_browser_number(value: object, decimals: int, *, small_threshold: float | None = None) -> str:
    """Format a statistic for browser display without mutating canonical results."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(numeric):
        return "—"
    if small_threshold is not None and 0 <= numeric < small_threshold:
        return f"<{small_threshold:.{decimals}f}"
    rounded = round(numeric, decimals)
    if rounded == 0:
        rounded = 0.0
    return f"{rounded:.{decimals}f}"


def _result_preview_df(results: pd.DataFrame) -> pd.DataFrame:
    """Return a researcher-facing browser preview without internal diagnostic columns.

    Display precision is intentionally concise: coefficients use two decimals and
    p/q values use three decimals (values below 0.001 display as ``<0.001``).
    The downloadable CSV and RunBundle retain the complete calculated precision.
    """
    ordered = results.sort_values(["q_value", "p_value"], na_position="last").head(RESULT_PREVIEW_ROWS).copy()
    columns = [name for name in RESULT_PREVIEW_COLUMNS if name in ordered.columns]
    preview = ordered.loc[:, columns].rename(columns=RESULT_PREVIEW_LABELS)
    if "Correlation" in preview.columns:
        preview["Correlation"] = preview["Correlation"].map(lambda value: _format_browser_number(value, 2))
    if "p-value" in preview.columns:
        preview["p-value"] = preview["p-value"].map(lambda value: _format_browser_number(value, 3, small_threshold=0.001))
    if "BH q-value" in preview.columns:
        preview["BH q-value"] = preview["BH q-value"].map(lambda value: _format_browser_number(value, 3, small_threshold=0.001))
    if "Pairwise N" in preview.columns:
        preview["Pairwise N"] = preview["Pairwise N"].map(lambda value: "—" if pd.isna(value) else str(int(value)))
    return preview


def _computation_engine_display(actual_backend: object, fallback_reason: object = "") -> str:
    """Researcher-facing execution-engine wording; technical IDs remain in provenance."""
    backend = str(actual_backend or "unknown")
    if backend.startswith("optimized_"):
        label = "Optimized"
    elif backend.startswith("reference_"):
        label = "Reference"
    else:
        label = "Unknown"
    line = f"Computation engine: {label}."
    if fallback_reason:
        line += " Automatic selection used the reference engine because the optimized path was not eligible for this run."
    return line


def _help_label(label: str, help_text: str) -> str:
    """Accessible hover/focus/tap help label for researcher-facing controls."""
    safe_label = html.escape(label)
    safe_help = html.escape(help_text)
    return f"""<div class='biostat-help-label'><span>{safe_label}</span>
    <details class='biostat-help' data-biostat-help><summary aria-label='Help for {safe_label}'>i</summary>
    <div class='biostat-tooltip' role='tooltip'>{safe_help}</div></details></div>"""


def _field_help(label: str, help_text: str) -> None:
    gr.HTML(_help_label(label, help_text))


def _choice_help(items: list[tuple[str, str]]) -> None:
    parts = ["<div class='biostat-choice-help' aria-label='Choice guidance'>"]
    for label, text in items:
        parts.append(_help_label(label, text))
    parts.append("</div>")
    gr.HTML("".join(parts))


def _workflow_guide_html(stage: int = 0, state: str = "pending") -> str:
    labels = ["Load data", "Inspect readiness", "Run analysis", "Review results", "Create figures", "Verify provenance"]
    bits = ["<div class='biostat-workflow' aria-label='Analysis workflow'>"]
    for index, label in enumerate(labels, start=1):
        classes = ["step"]
        icon = str(index)
        if index < stage or (index == stage and state == "complete"):
            classes.append("complete")
            icon = "✓"
        elif index == stage and state in {"warning", "blocked", "active"}:
            classes.append(state)
            icon = "!" if state == "warning" else ("×" if state == "blocked" else str(index))
        elif index == stage:
            classes.append("active")
        bits.append(f"<div class='{' '.join(classes)}'><b>{icon}</b><span>{index}. {html.escape(label)}</span></div>")
        if index != len(labels):
            bits.append("<span class='arrow' aria-hidden='true'>→</span>")
    bits.append("</div>")
    return "".join(bits)


WORKFLOW_GUIDE_HTML = _workflow_guide_html()


READINESS_LEGEND_HTML = """
<div class='readiness-legend' aria-label='Readiness status meanings'>
  <span class='legend-chip status-pass'><b>✓ PASS</b><small>Ready to proceed</small></span>
  <span class='legend-chip status-info'><b>i INFO</b><small>Interpretive guidance</small></span>
  <span class='legend-chip status-warning'><b>! WARNING</b><small>Review and acknowledge</small></span>
  <span class='legend-chip status-blocked'><b>× BLOCKED</b><small>Resolve before analysis</small></span>
</div>
"""

OMICS_SCOPE_HTML = """
<div class='biostat-omics-scope' aria-label='Supported quantitative data types'>
  <div class='biostat-omics-graphic' aria-hidden='true'>
    <svg viewBox='0 0 360 128' role='img'>
      <defs>
        <linearGradient id='omicsLine' x1='0' x2='1'>
          <stop offset='0%' stop-color='#60A5FA'/><stop offset='100%' stop-color='#5EEAD4'/>
        </linearGradient>
      </defs>
      <path d='M72 28 C130 18 160 58 210 44 S292 26 326 52' fill='none' stroke='url(#omicsLine)' stroke-width='2.5' opacity='.72'/>
      <path d='M55 91 C116 68 155 105 204 84 S281 72 326 92' fill='none' stroke='url(#omicsLine)' stroke-width='2.5' opacity='.55'/>
      <g fill='#E8F1F6' stroke='#5EEAD4' stroke-width='2'>
        <circle cx='58' cy='28' r='10'/><circle cx='148' cy='42' r='10'/><circle cx='236' cy='31' r='10'/><circle cx='317' cy='55' r='10'/>
        <circle cx='72' cy='94' r='10'/><circle cx='178' cy='89' r='10'/><circle cx='290' cy='94' r='10'/>
      </g>
      <g fill='#D9F5F1' font-size='10' font-family='system-ui, sans-serif' text-anchor='middle'>
        <text x='58' y='14'>Metabolomics</text><text x='148' y='27'>Proteomics</text><text x='236' y='16'>RNA-seq</text><text x='317' y='40'>16S</text>
        <text x='72' y='118'>Microbiome</text><text x='178' y='113'>Metagenomics</text><text x='290' y='118'>Biomarkers</text>
      </g>
    </svg>
  </div>
  <div class='biostat-omics-copy'>
    <b>Designed for quantitative feature matrices</b>
    <span>Metabolomics · Proteomics · RNA-seq · 16S / microbiome · Metagenomics · Generic biomarkers</span>
    <small>Same-domain and cross-domain matrix-to-matrix correlation are supported when the supplied data meet the declared preprocessing and statistical-policy requirements.</small>
  </div>
</div>
"""

NIH_REPRODUCIBILITY_HTML = """
<div class='biostat-nih-panel'>
  <div class='biostat-nih-kicker'>REPRODUCIBILITY IN BIOMEDICAL RESEARCH</div>
  <blockquote>“Two of the cornerstones of science advancement are rigor in designing and performing scientific research and the ability to reproduce biomedical research findings.”</blockquote>
  <div class='biostat-nih-source'>— National Institutes of Health, <a href='https://grants.nih.gov/policy-and-compliance/policy-topics/reproducibility' target='_blank' rel='noopener noreferrer'>Enhancing Reproducibility through Rigor and Transparency</a></div>
  <div class='biostat-nih-tool'><b>How this software supports that goal:</b> explicit analysis settings, dataset SHA-256 identity checks, saved AnalysisSpec files, deterministic seeds, provenance metadata, and verifiable RunBundles.</div>
  <small>NIH is cited as a source of research-reproducibility guidance. NIH does not endorse, certify, or validate this software. The NIH logo is intentionally not used.</small>
</div>
"""


def _readiness_banner(status: str, *, fingerprint: str = "", warning_count: int = 0, detail: str = "") -> str:
    key = str(status).strip().upper()
    cls = {"PASS": "status-pass", "WARNING": "status-warning", "BLOCKED": "status-blocked", "INFO": "status-info"}.get(key, "status-info")
    meaning = {
        "PASS": "Inspection passed. The analyzed request is eligible to proceed.",
        "WARNING": "Inspection found warnings. Review them and acknowledge the exact inspected request before inference.",
        "BLOCKED": "Analysis is blocked. Resolve the blocking readiness findings and inspect again before inference.",
        "INFO": "Review the information below before proceeding.",
    }.get(key, "Review the information below.")
    warning_line = f"<div>{warning_count} warning(s) require acknowledgement before inference.</div>" if warning_count else ""
    fp = f"<div class='fingerprint'>Run fingerprint: <code>{html.escape(fingerprint)}</code></div>" if fingerprint else ""
    extra = f"<div>{html.escape(detail)}</div>" if detail else ""
    return f"<div class='readiness-banner {cls}'><div class='readiness-title'>Data readiness: {html.escape(key)}</div><div>{meaning}</div>{warning_line}{extra}{fp}</div>"


def _analysis_gate_html(prepared: PreparedAnalysis | None, *, extra_warning_count: int = 0) -> str:
    if prepared is None:
        return "<div class='analysis-gate status-info'><b>Analysis not ready.</b> Complete Step 2: Inspect & validate inputs.</div>"
    if prepared.blocked:
        return "<div class='analysis-gate status-blocked'><b>Analysis blocked.</b> Return to Readiness, resolve the blocking findings, then inspect again. The Run button is disabled.</div>"
    if prepared.warning_issue_ids or extra_warning_count:
        return "<div class='analysis-gate status-warning'><b>Warnings require acknowledgement.</b> Review the Readiness findings, then check the acknowledgement box below to enable analysis.</div>"
    return "<div class='analysis-gate status-pass'><b>Ready to run.</b> This exact inspected request passed readiness checks.</div>"


APP_CSS = r"""
:root { color-scheme: light; }
html.biostat-dark { color-scheme: dark; }
.gradio-container {
  max-width: 1680px !important; margin: 0 auto !important; padding: 10px 12px 18px !important;
  background:#F5F7FB !important; color:#172033 !important;
  --biostat-bg:#F5F7FB; --biostat-card:#FFFFFF; --biostat-panel:#FFFFFF; --biostat-panel-2:#F7F9FC;
  --biostat-text:#172033; --biostat-muted:#667085; --biostat-border:#D8E0EA; --biostat-soft:#F1F5F9; --biostat-input:#FFFFFF;
  --biostat-accent:#2563EB; --biostat-accent-soft:#EFF6FF;
  --biostat-checkbox-check:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2016%2016%22%3E%3Cpath%20fill%3D%22none%22%20stroke%3D%22%23fff%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%20stroke-width%3D%222.5%22%20d%3D%22M3%208.5%206.5%2012%2013%204.5%22%2F%3E%3C%2Fsvg%3E");
}
html.biostat-dark .gradio-container,
.gradio-container.dark,
.dark .gradio-container {
  background:#0B1220 !important; color:#E8EEF7 !important;
  --biostat-bg:#0B1220; --biostat-card:#121D2F; --biostat-panel:#121D2F; --biostat-panel-2:#18263A;
  --biostat-text:#E8EEF7; --biostat-muted:#A9B7C8; --biostat-border:#2B3B52; --biostat-soft:#162236; --biostat-input:#0F192A;
  --biostat-accent:#60A5FA; --biostat-accent-soft:#162B49;
  --body-background-fill:#0B1220; --background-fill-primary:#121D2F; --background-fill-secondary:#18263A;
  --body-text-color:#E8EEF7; --body-text-color-subdued:#A9B7C8; --border-color-primary:#2B3B52;
  --block-background-fill:#111A2B; --block-border-color:#2B3B52; --block-info-text-color:#A9B7C8;
  --block-label-background-fill:#18263A; --block-label-text-color:#E8EEF7;
  --block-title-background-fill:#18263A; --block-title-text-color:#E8EEF7;
  --panel-background-fill:#121D2F; --panel-border-color:#2B3B52;
  --input-background-fill:#0F1A2C; --input-border-color:#33465F; --input-placeholder-color:#8EA0B5;
  --accordion-text-color:#E6EDF5; --button-secondary-background-fill:#172033; --button-secondary-text-color:#E8EEF7;
  --button-secondary-border-color:#33465F; --checkbox-label-background-fill:#18263A; --checkbox-label-text-color:#E8EEF7;
  --checkbox-background-color:#0F192A; --checkbox-background-color-selected:#238636;
  --checkbox-border-color:#86EFAC; --checkbox-border-color-selected:#86EFAC; --checkbox-border-color-focus:#86EFAC;
  --checkbox-check:var(--biostat-checkbox-check);
  --table-even-background-fill:#111A2B; --table-odd-background-fill:#0F192A; --table-text-color:#E8EEF7;
  --code-background-fill:#0F192A; --error-background-fill:#3A171A; --error-text-color:#FECACA;
}

/* Compact application header */
#biostat-header { background:linear-gradient(120deg,#0B1F33 0%,#153B55 62%,#1C6467 100%); color:#FFFFFF !important; border-radius:14px; padding:22px 24px; margin-bottom:12px; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:start; }
.biostat-header-copy { min-width:0; }
#biostat-header h1, #biostat-header h1 *, #biostat-header .badge { color:#FFFFFF !important; }
#biostat-header h1 { margin:0; font-size:24px; letter-spacing:-0.02em; }
#biostat-header p { margin:6px 0 0; color:#E8F1F6 !important; max-width:980px; font-size:13px; line-height:1.4; }
#biostat-header .badges { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
#biostat-header .badge { border:1px solid rgba(255,255,255,.38); background:rgba(255,255,255,.12); border-radius:999px; padding:3px 8px; font-size:11px; }
.biostat-header-actions { position:static; display:grid; grid-template-columns:repeat(2,minmax(82px,1fr)); gap:6px; align-self:start; min-width:244px; max-width:280px; }
.biostat-theme-switcher { grid-column:1 / -1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:4px; padding:4px; border:1px solid rgba(255,255,255,.26); border-radius:9px; background:rgba(0,0,0,.15); min-width:0; }
.biostat-theme-switcher button, .biostat-header-link { min-height:34px; color:#FFF; background:transparent; border:1px solid transparent; border-radius:7px; padding:6px 8px; cursor:pointer; font-size:11px; white-space:nowrap; }
.biostat-theme-switcher button[aria-pressed='true'] { background:#FFFFFF; color:#0B1F33; font-weight:700; }
.biostat-header-link { border-color:rgba(255,255,255,.28); background:rgba(255,255,255,.08); }

/* Research workstation shell */
.biostat-workstation-sidebar { background:var(--biostat-card) !important; border-right:1px solid var(--biostat-border) !important; }
.gradio-container:has(.biostat-workstation-sidebar.open) #biostat-header,
.gradio-container:has(.biostat-workstation-sidebar.open) #biostat-main-tabs { margin-left:247px !important; width:calc(100% - 247px) !important; box-sizing:border-box !important; }
#biostat-main-tabs { min-width:0 !important; transition:margin-left .16s ease,width .16s ease; }
.biostat-side-heading { margin:4px 0 5px; color:var(--biostat-muted); font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.biostat-side-note { color:var(--biostat-muted); font-size:11.5px; line-height:1.35; margin-bottom:6px; }
.biostat-nav-button button { justify-content:flex-start !important; text-align:left !important; font-weight:650 !important; min-height:38px !important; }
.biostat-workstation-tabs > .tab-nav { display:none !important; }
.biostat-workstation-tabs { min-width:0 !important; }
.biostat-section-head { margin:0 0 8px !important; }

.biostat-workflow { display:flex; flex-direction:column; align-items:stretch; gap:5px; background:transparent; border:0; border-radius:0; padding:0; margin:4px 0 10px; }
.biostat-workflow .step { display:flex; align-items:center; gap:7px; min-width:0; color:var(--biostat-text); font-size:12px; font-weight:650; opacity:.6; padding:3px 2px; }
.biostat-workflow .step b { display:inline-grid; place-items:center; width:23px; height:23px; border-radius:50%; color:white; background:#64748B; flex:0 0 auto; }
.biostat-workflow .step.active { opacity:1; } .biostat-workflow .step.active b { background:#2A7F85; }
.biostat-workflow .step.complete { opacity:1; } .biostat-workflow .step.complete b { background:#238636; }
.biostat-workflow .step.warning { opacity:1; } .biostat-workflow .step.warning b { background:#C56A00; }
.biostat-workflow .step.blocked { opacity:1; } .biostat-workflow .step.blocked b { background:#B42318; }
.biostat-workflow .arrow { display:none; }
.biostat-workstation-sidebar .biostat-workflow { flex-direction:row; flex-wrap:wrap; gap:5px; margin-bottom:8px; }
.biostat-workstation-sidebar .biostat-workflow .step { padding:0; flex:0 0 auto; }
.biostat-workstation-sidebar .biostat-workflow .step span { display:none; }

/* Dense but comfortable content */
.biostat-panel { border:1px solid var(--biostat-border) !important; border-radius:10px !important; background:var(--biostat-panel) !important; padding:9px 11px !important; min-width:0; }
.biostat-panel h4, .biostat-panel h3 { margin-top:0 !important; margin-bottom:6px !important; }
.biostat-subtle { color:var(--biostat-muted); }
.biostat-callout { border-left:4px solid #2A7F85; background:#F0F8F8; padding:9px 11px; border-radius:0 9px 9px 0; }
html.biostat-dark .biostat-callout { background:#11303A; }
.biostat-compact-accordion { border-color:var(--biostat-border) !important; background:var(--biostat-card) !important; }
.biostat-compact-accordion > div { padding-top:4px !important; padding-bottom:4px !important; }
.biostat-datasets { gap:10px !important; align-items:start !important; }
.biostat-datasets .gap, .biostat-datasets .form { gap:5px !important; }
.biostat-datasets .block { margin-top:0 !important; margin-bottom:0 !important; }
.biostat-dataset-card { padding:8px 10px !important; }
.biostat-dataset-card h4 { margin:0 0 5px !important; }
.biostat-declaration-row { gap:8px !important; align-items:start !important; }
.biostat-declaration-row > div { min-width:190px !important; }
.biostat-dataset-card .biostat-help-label { margin-bottom:1px !important; font-size:11.5px !important; }
.biostat-declaration-note { color:var(--biostat-muted); font-size:11.5px; margin:0 0 7px; }
.biostat-inspect-cta { margin-top:10px !important; border:1px solid var(--biostat-border) !important; border-radius:10px !important; background:var(--biostat-panel-2) !important; padding:10px 12px !important; }
.biostat-inspect-cta button { min-height:46px !important; font-weight:800 !important; }
.biostat-stat-grid { gap:8px !important; align-items:start !important; }
.biostat-stat-grid > div { min-width:170px !important; }
.biostat-no-collision { overflow:visible !important; padding-top:2px; }

/* Dark two-tone overrides for native Gradio surfaces */
html.biostat-dark .gradio-container .biostat-compact-accordion,
.gradio-container.dark .biostat-compact-accordion,
.dark .gradio-container .biostat-compact-accordion { background:#121D2F !important; color:#E8EEF7 !important; border-color:#2B3B52 !important; }
html.biostat-dark .gradio-container input, html.biostat-dark .gradio-container textarea, html.biostat-dark .gradio-container select,
.gradio-container.dark input, .gradio-container.dark textarea, .gradio-container.dark select,
.dark .gradio-container input, .dark .gradio-container textarea, .dark .gradio-container select { background:#0F192A !important; color:#E8EEF7 !important; border-color:#33465F !important; }
html.biostat-dark .gradio-container [role='listbox'], html.biostat-dark .gradio-container .options,
.gradio-container.dark [role='listbox'], .gradio-container.dark .options { background:#121D2F !important; color:#E8EEF7 !important; }
html.biostat-dark .gradio-container table, html.biostat-dark .gradio-container th, html.biostat-dark .gradio-container td,
.gradio-container.dark table, .gradio-container.dark th, .gradio-container.dark td { background:#121D2F !important; color:#E8EEF7 !important; border-color:#2B3B52 !important; }
html.biostat-dark .gradio-container code, .gradio-container.dark code { background:#0F192A !important; color:#E8EEF7 !important; }
html.biostat-dark .gradio-container button.secondary, .gradio-container.dark button.secondary { background:#18263A !important; color:#E8EEF7 !important; border-color:#33465F !important; }
html.biostat-dark .gradio-container .wrap, .gradio-container.dark .wrap { color:#E8EEF7; }

/* Accessible contextual help */
.biostat-help-label { display:flex; align-items:center; gap:6px; margin:0 0 2px 1px; font-size:12.5px; font-weight:650; color:var(--biostat-text); min-width:0; }
.biostat-help { position:relative; display:inline-block; margin:0; flex:0 0 auto; }
.biostat-help summary { list-style:none; display:inline-grid; place-items:center; width:19px; height:19px; border-radius:50%; border:1px solid #98A2B3; color:var(--biostat-text); background:var(--biostat-input); font-size:11px; font-weight:700; cursor:help; user-select:none; }
.biostat-help summary::-webkit-details-marker { display:none; }
.biostat-help summary:focus-visible { outline:3px solid rgba(42,127,133,.35); outline-offset:2px; }
.biostat-tooltip { display:none; position:fixed; z-index:10000; width:min(330px,calc(100vw - 24px)); max-height:min(320px,calc(100vh - 24px)); overflow:auto; padding:10px 12px; border-radius:9px; border:1px solid #475467; background:#101828; color:#FFFFFF; font-size:12px; line-height:1.42; font-weight:400; box-shadow:0 8px 24px rgba(16,24,40,.28); white-space:normal; overflow-wrap:anywhere; }
.biostat-help:hover .biostat-tooltip, .biostat-help:focus-within .biostat-tooltip, .biostat-help[open] .biostat-tooltip { display:block; }
.biostat-choice-help { display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:3px; }
.biostat-choice-help .biostat-help-label { font-weight:500; font-size:11.5px; }

/* Status, readiness, result, and download surfaces */
.biostat-example-status { border:1px solid #A7D7B7 !important; background:#EFFAF3 !important; border-radius:9px !important; padding:7px 9px !important; color:#14532D !important; }
html.biostat-dark .biostat-example-status, .gradio-container.dark .biostat-example-status,
html.biostat-dark .biostat-example-status > div, .gradio-container.dark .biostat-example-status > div,
html.biostat-dark .biostat-example-status .prose, .gradio-container.dark .biostat-example-status .prose { background:#153B2A !important; color:#F1FFF6 !important; border-color:#3A8F62 !important; }
html.biostat-dark .biostat-example-status *, .gradio-container.dark .biostat-example-status * { color:#F1FFF6 !important; }
.biostat-empty-state { border:1px dashed #98A2B3; background:var(--biostat-soft); border-radius:10px; padding:9px 11px; margin:6px 0 10px; }
.biostat-download-label { font-size:12.5px; font-weight:700; color:var(--biostat-text); margin:6px 0 3px; }
.biostat-download-toolbar { gap:8px !important; }
.biostat-download-toolbar > div { min-width:180px !important; }
.readiness-legend { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0 9px; }
.legend-chip { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:5px 8px; border:1px solid var(--biostat-border); font-size:11.5px; }
.legend-chip small { color:var(--biostat-muted); }
.status-pass { --status:#238636; --status-bg:#EAF7ED; --status-text:#14532D; }
.status-info { --status:#2563EB; --status-bg:#EFF6FF; --status-text:#1E3A8A; }
.status-warning { --status:#C56A00; --status-bg:#FFF7E8; --status-text:#7C3E00; }
.status-blocked { --status:#B42318; --status-bg:#FFF0EF; --status-text:#7A271A; }
html.biostat-dark .status-pass { --status-bg:#153B2A; --status-text:#F1FFF6; }
html.biostat-dark .status-info { --status-bg:#17365F; --status-text:#EFF6FF; }
html.biostat-dark .status-warning { --status-bg:#463014; --status-text:#FFF4CC; }
html.biostat-dark .status-blocked { --status-bg:#481D22; --status-text:#FFE7E9; }
.legend-chip[class*='status-'] { border-color:var(--status); background:var(--status-bg); color:var(--status-text); }
.legend-chip[class*='status-'] *, .readiness-banner *, .analysis-gate * { color:inherit !important; }
html.biostat-dark .legend-chip[class*='status-'] small, .gradio-container.dark .legend-chip[class*='status-'] small { color:inherit !important; opacity:.88; }
.readiness-banner, .analysis-gate { border:1px solid var(--status); border-left-width:5px; background:var(--status-bg); color:var(--status-text); border-radius:9px; padding:8px 10px; margin:6px 0 9px; overflow-wrap:anywhere; }
.readiness-title { font-size:17px; font-weight:800; margin-bottom:2px; }
.fingerprint { margin-top:5px; font-size:11.5px; overflow-wrap:anywhere; }
.fingerprint code { white-space:normal; overflow-wrap:anywhere; }
.biostat-issues-table { overflow-x:auto !important; }
.biostat-issues-table table { table-layout:fixed !important; width:1530px !important; min-width:1530px !important; border-collapse:collapse !important; }
.biostat-issues-table td, .biostat-issues-table th { white-space:normal !important; overflow-wrap:anywhere !important; vertical-align:top !important; line-height:1.32 !important; box-sizing:border-box !important; }
.biostat-issues-table th:nth-child(1), .biostat-issues-table td:nth-child(1) { width:140px !important; min-width:140px !important; max-width:140px !important; }
.biostat-issues-table th:nth-child(2), .biostat-issues-table td:nth-child(2) { width:140px !important; min-width:140px !important; max-width:140px !important; }
.biostat-issues-table th:nth-child(3), .biostat-issues-table td:nth-child(3) { width:230px !important; min-width:230px !important; max-width:230px !important; }
.biostat-issues-table th:nth-child(4), .biostat-issues-table td:nth-child(4) { width:320px !important; min-width:320px !important; max-width:320px !important; }
.biostat-issues-table th:nth-child(5), .biostat-issues-table td:nth-child(5) { width:700px !important; min-width:700px !important; max-width:700px !important; }
.biostat-results-preview table { table-layout:auto !important; min-width:900px !important; }
.biostat-results-preview th { white-space:normal !important; overflow-wrap:normal !important; word-break:normal !important; min-width:105px !important; line-height:1.2 !important; }
.biostat-results-preview th:nth-child(1), .biostat-results-preview th:nth-child(2) { min-width:180px !important; }
.biostat-results-preview td { white-space:normal !important; word-break:normal !important; }
.biostat-selection-counter { margin:4px 0 8px; font-size:12px; }
.biostat-selection-counter.ok { color:#166534; } .biostat-selection-counter.bad { color:#B42318; font-weight:650; }
.batch-report-box { border:1px solid var(--biostat-border); background:var(--biostat-soft); border-radius:10px; padding:9px; margin-top:10px; }
.batch-report-action button { width:100% !important; min-height:44px !important; font-weight:800 !important; background:var(--biostat-accent) !important; color:#FFFFFF !important; border-color:var(--biostat-accent) !important; }

/* Figure workstation */
.biostat-figure-workstation { align-items:flex-start !important; gap:12px !important; }
.biostat-figure-controls { min-width:270px !important; max-width:360px !important; background:var(--biostat-card) !important; border:1px solid var(--biostat-border) !important; border-radius:10px; padding:9px !important; }
.biostat-figure-stage { min-width:0 !important; }
.biostat-figure-stage .tab-nav { margin-bottom:4px !important; }

/* High-contrast selection controls. Gradio renders checkboxes with a themed background image,
   so accent-color alone is insufficient. Force an explicit white tick on the selected state. */
.gradio-container input[type='checkbox'] { accent-color:#238636 !important; }
.gradio-container input[type='checkbox']:checked,
.gradio-container input[type='checkbox']:checked:hover,
.gradio-container input[type='checkbox']:checked:focus {
  background-image:var(--biostat-checkbox-check) !important;
  background-repeat:no-repeat !important;
  background-position:center !important;
  background-size:12px 12px !important;
  background-color:#238636 !important;
  border-color:#86EFAC !important;
}
html.biostat-dark .gradio-container input[type='checkbox'],
.gradio-container.dark input[type='checkbox'],
.dark .gradio-container input[type='checkbox'] { accent-color:#4ADE80 !important; border-color:#86EFAC !important; }
html.biostat-dark .gradio-container input[type='checkbox']:checked,
html.biostat-dark .gradio-container input[type='checkbox']:checked:hover,
html.biostat-dark .gradio-container input[type='checkbox']:checked:focus,
.gradio-container.dark input[type='checkbox']:checked,
.gradio-container.dark input[type='checkbox']:checked:hover,
.gradio-container.dark input[type='checkbox']:checked:focus,
.dark .gradio-container input[type='checkbox']:checked,
.dark .gradio-container input[type='checkbox']:checked:hover,
.dark .gradio-container input[type='checkbox']:checked:focus {
  background-image:var(--biostat-checkbox-check) !important;
  background-color:#238636 !important;
  border-color:#86EFAC !important;
}
.gradio-container input[type='checkbox']:focus-visible { outline:3px solid rgba(96,165,250,.48) !important; outline-offset:2px !important; }

/* Supported-data scope graphic */
.biostat-omics-scope { display:grid; grid-template-columns:minmax(270px,.8fr) minmax(320px,1.2fr); gap:14px; align-items:center; border:1px solid var(--biostat-border); border-radius:12px; background:linear-gradient(120deg,#10263B,#123946); color:#F2F8FC; padding:8px 14px; margin:2px 0 10px; overflow:hidden; }
.biostat-omics-graphic svg { display:block; width:100%; max-width:390px; height:112px; }
.biostat-omics-copy { display:flex; flex-direction:column; gap:5px; }
.biostat-omics-copy b { font-size:14px; color:#FFFFFF; }
.biostat-omics-copy span { color:#D8F3F0; font-size:12.5px; font-weight:650; line-height:1.45; }
.biostat-omics-copy small { color:#C1D6E3; line-height:1.42; }

/* NIH reproducibility citation panel: text attribution only; no agency logo. */
.biostat-nih-panel { border:1px solid var(--biostat-border); border-left:4px solid #2563EB; border-radius:10px; background:var(--biostat-panel-2); padding:12px 14px; margin:14px 0 6px; color:var(--biostat-text); }
.biostat-nih-kicker { color:var(--biostat-accent); font-size:10.5px; font-weight:850; letter-spacing:.08em; margin-bottom:6px; }
.biostat-nih-panel blockquote { margin:4px 0 7px; padding:0; border:0; font-size:14px; line-height:1.5; font-weight:650; color:var(--biostat-text); }
.biostat-nih-source { font-size:12px; margin-bottom:9px; color:var(--biostat-muted); }
.biostat-nih-source a { color:var(--biostat-accent); text-decoration:underline; }
.biostat-nih-tool { font-size:12.5px; line-height:1.45; margin-bottom:7px; }
.biostat-nih-panel small { color:var(--biostat-muted); line-height:1.4; }

/* Learn/About */
.biostat-learn-card { border:1px solid var(--biostat-border); border-radius:10px; background:var(--biostat-card); padding:10px 12px; margin:7px 0; }
.biostat-video-card { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:10px; border-bottom:1px solid var(--biostat-border); padding:9px 0; }
.biostat-video-card:last-child { border-bottom:0; }
.biostat-video-meta { color:var(--biostat-muted); font-size:12px; }
.biostat-coming-soon { display:inline-block; border:1px solid var(--biostat-border); border-radius:999px; padding:3px 7px; color:var(--biostat-muted); font-size:11px; }

@media (max-width: 980px) {
  #biostat-header { grid-template-columns:1fr; }
  .biostat-header-actions { grid-template-columns:repeat(2,minmax(96px,1fr)); width:min(100%,360px); max-width:360px; }
  .biostat-figure-workstation { flex-direction:column !important; }
  .biostat-omics-scope { grid-template-columns:1fr; }
  .biostat-omics-graphic { display:none; }
  .biostat-figure-controls { max-width:none !important; width:100% !important; }
}
/* At narrow widths the persistent rail remains explicit; the main tabs/header use
   the same rail offset instead of rendering underneath the overlay. */
@media (max-width: 768px) {
  .gradio-container:has(.biostat-workstation-sidebar.open) #biostat-header,
  .gradio-container:has(.biostat-workstation-sidebar.open) #biostat-main-tabs { margin-left:247px !important; width:calc(100% - 247px) !important; }
}
@media (max-width: 700px) {
  .gradio-container { padding:6px 6px 14px !important; }
  #biostat-header { padding:18px 16px; border-radius:11px; }
  #biostat-header h1 { font-size:21px; }
  .biostat-stat-grid > div { min-width:100% !important; }
  .biostat-datasets { flex-direction:column !important; }
  .biostat-declaration-row { flex-direction:column !important; }
  .biostat-declaration-row > div { min-width:100% !important; }
  .biostat-results-preview table { min-width:760px !important; }
}
footer { display:none !important; }
"""


APP_JS = r"""() => {
  if (window.__biostatUiInitialized) return;
  window.__biostatUiInitialized = true;

  const resolveTheme = (choice) => choice === 'system'
    ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : choice;
  const applyTheme = (choice) => {
    const resolved = resolveTheme(choice);
    const isDark = resolved === 'dark';
    document.documentElement.classList.toggle('biostat-dark', isDark);
    // Gradio's component theme switches on the native `.dark` class. The prior custom-only theme
    // only changed custom CSS variables, leaving accordions/inputs in their
    // light palette. Toggle the native class as well so every Gradio surface
    // and our custom surfaces use the same resolved theme.
    if (document.body) document.body.classList.toggle('dark', isDark);
    const appRoot = document.querySelector('.gradio-container');
    if (appRoot) appRoot.classList.toggle('dark', isDark);
    if (appRoot && appRoot.parentElement) appRoot.parentElement.classList.toggle('dark', isDark);
    document.documentElement.dataset.biostatTheme = choice;
    try { localStorage.setItem('biostat-theme', choice); } catch (_) {}
    document.querySelectorAll('[data-biostat-theme-choice]').forEach((button) => {
      button.setAttribute('aria-pressed', button.dataset.biostatThemeChoice === choice ? 'true' : 'false');
    });
  };
  let choice = 'system';
  try { choice = localStorage.getItem('biostat-theme') || 'system'; } catch (_) {}
  if (!['light','dark','system'].includes(choice)) choice = 'system';
  applyTheme(choice);

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-biostat-theme-choice]');
    if (button) applyTheme(button.dataset.biostatThemeChoice);
    const jump = event.target.closest('[data-biostat-jump]');
    if (jump) {
      const wrapper = document.getElementById(jump.dataset.biostatJump);
      const target = wrapper ? (wrapper.querySelector('button') || wrapper) : null;
      if (target) target.click();
    }
  });
  if (window.matchMedia) {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = () => { if (document.documentElement.dataset.biostatTheme === 'system') applyTheme('system'); };
    if (media.addEventListener) media.addEventListener('change', listener);
  }

  const placeTooltip = (details) => {
    if (!details) return;
    const summary = details.querySelector('summary');
    const tooltip = details.querySelector('.biostat-tooltip');
    if (!summary || !tooltip) return;
    tooltip.style.visibility = 'hidden';
    tooltip.style.display = 'block';
    tooltip.style.left = '12px';
    tooltip.style.top = '12px';
    const sr = summary.getBoundingClientRect();
    const tr = tooltip.getBoundingClientRect();
    const pad = 12;
    let left = sr.right + 8;
    if (left + tr.width > window.innerWidth - pad) left = sr.left - tr.width - 8;
    left = Math.max(pad, Math.min(left, window.innerWidth - tr.width - pad));
    let top = sr.top - 8;
    if (top + tr.height > window.innerHeight - pad) top = window.innerHeight - tr.height - pad;
    top = Math.max(pad, top);
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
    tooltip.style.visibility = 'visible';
  };
  const scheduleTooltip = (target) => {
    const details = target && target.closest ? target.closest('details.biostat-help') : null;
    if (details) requestAnimationFrame(() => placeTooltip(details));
  };
  document.addEventListener('mouseover', (event) => scheduleTooltip(event.target), true);
  document.addEventListener('focusin', (event) => scheduleTooltip(event.target), true);
  document.addEventListener('click', (event) => scheduleTooltip(event.target), true);
  window.addEventListener('resize', () => document.querySelectorAll('details.biostat-help[open]').forEach(placeTooltip));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') document.querySelectorAll('details.biostat-help[open]').forEach((d) => d.removeAttribute('open'));
  });
}"""


@dataclass(frozen=True)
class WebPreparedState:
    prepared: PreparedAnalysis
    session_key: str
    generation: int
    platform_warning_issue_ids: tuple[str, ...] = ()
    platform_issues: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class WebCompletedState:
    completed: object
    prepared: PreparedAnalysis
    session_key: str
    generation: int
    artifact_root: str


@dataclass(frozen=True)
class RestoredDatasetIdentity:
    dataset_a_sha256: str
    dataset_b_sha256: str
    dataset_a_path: str
    dataset_b_path: str


class _VisualizationSuperseded(RuntimeError):
    pass


_SESSION_LOCK = threading.Lock()
_SESSION_GENERATIONS: dict[str, int] = {}
_SESSION_ARTIFACTS: dict[str, set[Path]] = {}
_SESSION_RESTORED_IDENTITIES: dict[str, RestoredDatasetIdentity] = {}
_DIRECT_SESSION = "__direct_callback_session__"
_MAX_TRACKED = 10_000


def _session_key(request: Optional[gr.Request]) -> str:
    value = getattr(request, "session_hash", None) if request is not None else None
    return str(value) if value else _DIRECT_SESSION


def _current_generation(request: Optional[gr.Request]) -> int:
    with _SESSION_LOCK:
        return int(_SESSION_GENERATIONS.get(_session_key(request), 0))


def _bump_generation(request: Optional[gr.Request]) -> int:
    key = _session_key(request)
    with _SESSION_LOCK:
        value = int(_SESSION_GENERATIONS.get(key, 0)) + 1
        _SESSION_GENERATIONS[key] = value
        if len(_SESSION_GENERATIONS) > _MAX_TRACKED:
            for old in list(_SESSION_GENERATIONS):
                if old != key:
                    _SESSION_GENERATIONS.pop(old, None)
                    stale = _SESSION_ARTIFACTS.pop(old, set())
                    _SESSION_RESTORED_IDENTITIES.pop(old, None)
                    for path in stale:
                        shutil.rmtree(path, ignore_errors=True)
                    break
        return value


def _current(request: Optional[gr.Request], generation: int) -> bool:
    return _current_generation(request) == generation


def _register_session_artifact(request: Optional[gr.Request], root: Path) -> None:
    key = _session_key(request)
    with _SESSION_LOCK:
        _SESSION_ARTIFACTS.setdefault(key, set()).add(root)


def _cleanup_session_artifacts(request: Optional[gr.Request]) -> None:
    key = _session_key(request)
    with _SESSION_LOCK:
        roots = _SESSION_ARTIFACTS.pop(key, set())
    for root in roots:
        shutil.rmtree(root, ignore_errors=True)




def _set_restored_identity(request: Optional[gr.Request], spec: AnalysisSpec) -> None:
    identity = RestoredDatasetIdentity(
        dataset_a_sha256=spec.dataset_a.sha256.lower(),
        dataset_b_sha256=spec.dataset_b.sha256.lower(),
        dataset_a_path=spec.dataset_a.path,
        dataset_b_path=spec.dataset_b.path,
    )
    with _SESSION_LOCK:
        _SESSION_RESTORED_IDENTITIES[_session_key(request)] = identity


def _restored_identity(request: Optional[gr.Request]) -> RestoredDatasetIdentity | None:
    with _SESSION_LOCK:
        return _SESSION_RESTORED_IDENTITIES.get(_session_key(request))


def _clear_restored_identity(request: Optional[gr.Request]) -> None:
    with _SESSION_LOCK:
        _SESSION_RESTORED_IDENTITIES.pop(_session_key(request), None)


def preprocessing_choices(data_type: str) -> list[str]:
    return list(PREPROCESSING_BY_TYPE.get(data_type, ["unknown"]))


def preprocessing_display_choices(data_type: str) -> list[tuple[str, str]]:
    return [(PREPROCESSING_LABELS.get(value, value.replace("_", " ").title()), value) for value in preprocessing_choices(data_type)]


def preprocessing_update(data_type: str):
    raw_choices = preprocessing_choices(data_type)
    value = DEFAULT_PREPROCESSING.get(data_type, raw_choices[0])
    return gr.Dropdown(choices=preprocessing_display_choices(data_type), value=value)


def _replace_request_session(request: Optional[gr.Request]) -> int:
    """Invalidate the current inspected/completed request exactly once.

    Programmatic request replacement (Load Example / Restore AnalysisSpec) must
    not fan out through per-field user-edit listeners, but it still has to
    supersede every prior prepared/completed state and artifact.
    """
    generation = _bump_generation(request)
    _cleanup_session_artifacts(request)
    return generation


def load_example_callback(key: str, request: Optional[gr.Request] = None):
    ex = get_example(key)
    _replace_request_session(request)
    _clear_restored_identity(request)
    a = ex["a"]
    b = ex["b"]
    note = f"✅ **Synthetic example loaded:** {ex['label']}  \n{ex['description']}  \n{ex['notice']}"
    # Return component updates for preprocessing fields, not bare values. Gradio
    # does not fire `.input` handlers for programmatic data-type changes, so the
    # choices and selected value must be updated atomically by Load Example.
    a_preprocessing = gr.Dropdown(
        choices=preprocessing_display_choices(a["data_type"]),
        value=a["preprocessing"],
    )
    b_preprocessing = gr.Dropdown(
        choices=preprocessing_display_choices(b["data_type"]),
        value=b["preprocessing"],
    )
    return (
        a["path"], a["data_type"], a_preprocessing, a.get("details", ""), "samples_rows",
        b["path"], b["data_type"], b_preprocessing, b.get("details", ""), "samples_rows",
        ex.get("design", "independent"), "Synthetic independent observations for software demonstration.",
        ex.get("method", "spearman"), note,
    )


def _orig_name(upload: object, fallback: str) -> str:
    name = getattr(upload, "orig_name", None)
    if name:
        return Path(str(name)).name
    suffix = Path(str(upload)).suffix.lower()
    return f"{fallback}{suffix}" if suffix else fallback


def _parse_missing_tokens(value: object) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_MISSING_TOKENS
    text = str(value)
    tokens = [x.strip() for x in text.split(",")]
    # Preserve an explicit blank token when the field starts with a comma or contains an empty item.
    if "" not in tokens:
        tokens.insert(0, "")
    out = tuple(dict.fromkeys(tokens))
    if len(out) > 100:
        raise ValueError("At most 100 explicit missing-value tokens are allowed.")
    return out


def _coerce_int(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    fv = float(value)
    if not fv.is_integer():
        raise ValueError(f"{name} must be an integer.")
    iv = int(fv)
    if iv < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")
    return iv


def _build_spec_and_overrides(
    file_a, file_b,
    data_type_a, preprocessing_a, details_a, orientation_a,
    data_type_b, preprocessing_b, details_b, orientation_b,
    observation_structure, design_notes, method, min_pairwise_n,
    spearman_permutations, random_seed, missing_tokens_a=None, missing_tokens_b=None,
    *, expected_identity: RestoredDatasetIdentity | None = None,
) -> tuple[AnalysisSpec, dict[str, str]]:
    if file_a is None or file_b is None:
        raise ValueError("Select both datasets before inspection.")
    path_a = str(file_a)
    path_b = str(file_b)
    hash_a = sha256_file(path_a).lower()
    hash_b = sha256_file(path_b).lower()
    if expected_identity is not None:
        mismatches: list[str] = []
        if hash_a != expected_identity.dataset_a_sha256:
            mismatches.append(
                f"Dataset A expected {expected_identity.dataset_a_sha256} "
                f"({expected_identity.dataset_a_path}) but selected bytes hash to {hash_a}"
            )
        if hash_b != expected_identity.dataset_b_sha256:
            mismatches.append(
                f"Dataset B expected {expected_identity.dataset_b_sha256} "
                f"({expected_identity.dataset_b_path}) but selected bytes hash to {hash_b}"
            )
        if mismatches:
            raise ValueError(
                "Restored AnalysisSpec dataset identity mismatch. "
                + " ".join(mismatches)
                + ". Use 'Start new request' only if different input bytes are intentional."
            )
    spec = AnalysisSpec(
        schema_version="1.0",
        method=method,
        dataset_a=DatasetSpec(
            path=_orig_name(file_a, "dataset_a"),
            sha256=hash_a,
            orientation=orientation_a,
            data_type=data_type_a,
            preprocessing=preprocessing_a,
            preprocessing_details=details_a or "",
            missing_tokens=_parse_missing_tokens(missing_tokens_a),
        ),
        dataset_b=DatasetSpec(
            path=_orig_name(file_b, "dataset_b"),
            sha256=hash_b,
            orientation=orientation_b,
            data_type=data_type_b,
            preprocessing=preprocessing_b,
            preprocessing_details=details_b or "",
            missing_tokens=_parse_missing_tokens(missing_tokens_b),
        ),
        study_design=StudyDesignSpec(observation_structure, design_notes or ""),
        correlation=CorrelationSpec(
            minimum_pairwise_n=_coerce_int(min_pairwise_n, "Minimum pairwise N", 3),
            spearman_permutations=_coerce_int(spearman_permutations, "Spearman permutations", 99),
            random_seed=_coerce_int(random_seed, "Random seed", 0),
        ),
        review=ReviewSpec(),
        outputs=OutputSpec("runs"),
    )
    return spec, {"dataset_a": path_a, "dataset_b": path_b}


@lru_cache(maxsize=1)
def _bundled_example_signatures() -> tuple[dict[str, str], ...]:
    """Return immutable identities and declared metadata for bundled examples.

    The lookup is deliberately byte-identity based. Merely choosing the same
    data type or filenames as an example is not enough to trigger teaching
    guidance for a user dataset.
    """
    signatures: list[dict[str, str]] = []
    for _label, key in example_choices():
        example = get_example(key)
        signatures.append({
            "key": key,
            "label": str(example["label"]),
            "dataset_a_sha256": sha256_file(example["a"]["path"]).lower(),
            "dataset_b_sha256": sha256_file(example["b"]["path"]).lower(),
            "dataset_a_data_type": str(example["a"]["data_type"]),
            "dataset_b_data_type": str(example["b"]["data_type"]),
            "dataset_a_preprocessing": str(example["a"]["preprocessing"]),
            "dataset_b_preprocessing": str(example["b"]["preprocessing"]),
        })
    return tuple(signatures)


def _synthetic_example_metadata_issues(spec: AnalysisSpec) -> tuple[dict[str, str], ...]:
    """Flag declaration drift only when both inputs exactly match a bundled example.

    This is a teaching/product guardrail, not an attempt to infer preprocessing
    from arbitrary numeric matrices. User datasets never receive this warning
    unless their bytes exactly match one of the packaged synthetic examples.
    """
    match = next((
        item for item in _bundled_example_signatures()
        if item["dataset_a_sha256"] == spec.dataset_a.sha256.lower()
        and item["dataset_b_sha256"] == spec.dataset_b.sha256.lower()
    ), None)
    if match is None:
        return ()

    issues: list[dict[str, str]] = []
    for side, dataset in (("a", spec.dataset_a), ("b", spec.dataset_b)):
        expected_type = match[f"dataset_{side}_data_type"]
        expected_preprocessing = match[f"dataset_{side}_preprocessing"]
        mismatches: list[str] = []
        if dataset.data_type != expected_type:
            mismatches.append(
                f"data type {DATA_TYPE_LABELS.get(expected_type, expected_type)!r} "
                f"was changed to {DATA_TYPE_LABELS.get(dataset.data_type, dataset.data_type)!r}"
            )
        if dataset.preprocessing != expected_preprocessing:
            expected_label = PREPROCESSING_LABELS.get(expected_preprocessing, expected_preprocessing)
            current_label = PREPROCESSING_LABELS.get(dataset.preprocessing, dataset.preprocessing)
            mismatches.append(
                f"preprocessing {expected_label!r} was changed to {current_label!r}"
            )
        if not mismatches:
            continue
        dataset_label = "Dataset A" if side == "a" else "Dataset B"
        code = f"bundled_example_{side}_declaration_mismatch"
        issues.append({
            "source": "synthetic_example",
            "severity": "WARNING",
            "code": code,
            "issue_id": f"synthetic_example:{code}",
            "message": (
                f"{dataset_label} exactly matches the bundled synthetic example {match['label']!r}, but its current "
                f"declaration differs from the example catalog: {'; '.join(mismatches)}. "
                "The tool will not silently replace your declaration. Restore the example setting, or acknowledge "
                "this warning only if the change is intentional for teaching/testing."
            ),
        })
    return tuple(issues)


def _web_warning_issue_ids(state: WebPreparedState) -> tuple[str, ...]:
    return tuple(state.prepared.warning_issue_ids) + tuple(state.platform_warning_issue_ids)


def _issues_df(prepared: PreparedAnalysis, extra_issues: tuple[dict[str, str], ...] = ()) -> pd.DataFrame:
    frame = prepared.inspected.issues_frame().copy()
    advisories = pd.DataFrame([
        {
            "source": "statistical_policy",
            "severity": advisory["level"],
            "code": advisory["code"],
            "issue_id": f"policy:{advisory['code']}",
            "message": advisory["message"],
        }
        for advisory in prepared.policy_advisories
    ])
    out = frame if advisories.empty else pd.concat([frame, advisories], ignore_index=True)
    if extra_issues:
        out = pd.concat([out, pd.DataFrame(list(extra_issues))], ignore_index=True)
    if out.empty:
        return out
    out = out.copy()
    severity_display = {
        "INFO": "🟡 INFO", "WARNING": "🟠 WARNING", "ERROR": "🔴 BLOCKED", "BLOCKED": "🔴 BLOCKED", "PASS": "🟢 PASS"
    }
    out["severity"] = out["severity"].astype(str).str.upper().map(lambda value: severity_display.get(value, value))
    return out


def _metrics_df(prepared: PreparedAnalysis) -> pd.DataFrame:
    rows = []
    for label, metrics in (("Dataset A", prepared.inspected.report_a.metrics), ("Dataset B", prepared.inspected.report_b.metrics)):
        rows.extend({"dataset": label, "metric": k, "value": v} for k, v in metrics.items())
    return pd.DataFrame(rows)


def _alignment_df(prepared: PreparedAnalysis) -> pd.DataFrame:
    a = prepared.inspected.alignment
    if not a:
        return pd.DataFrame()
    return pd.DataFrame([
        {"metric": "samples_dataset_a", "value": a["n_samples_a"]},
        {"metric": "samples_dataset_b", "value": a["n_samples_b"]},
        {"metric": "matched_samples", "value": a["n_common"]},
        {"metric": "only_dataset_a", "value": len(a["only_a"])},
        {"metric": "only_dataset_b", "value": len(a["only_b"])},
        {"metric": "feature_pairs_planned", "value": prepared.inspected.aligned_a.shape[1] * prepared.inspected.aligned_b.shape[1] if prepared.inspected.aligned_a is not None else None},
    ])


def _alignment_detail_df(prepared: PreparedAnalysis) -> pd.DataFrame:
    a = prepared.inspected.alignment
    if not a:
        return pd.DataFrame(columns=["sample_id", "status"])
    rows = []
    rows.extend({"sample_id": str(x), "status": "matched"} for x in a.get("common_order", []))
    rows.extend({"sample_id": str(x), "status": "only_dataset_a"} for x in a.get("only_a", []))
    rows.extend({"sample_id": str(x), "status": "only_dataset_b"} for x in a.get("only_b", []))
    return pd.DataFrame(rows)


def _feature_qc(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    rows = []
    n = len(df)
    for name in df.columns:
        ser = pd.to_numeric(df[name], errors="coerce")
        finite = ser.dropna()
        rows.append({
            "dataset": dataset, "feature": str(name), "observed_n": int(finite.size),
            "missing_pct": (100.0 * (n - finite.size) / n) if n else 0.0,
            "unique_observed": int(finite.nunique(dropna=True)),
            "min": float(finite.min()) if len(finite) else None,
            "max": float(finite.max()) if len(finite) else None,
            "constant": bool(finite.nunique(dropna=True) <= 1) if len(finite) else True,
        })
    return pd.DataFrame(rows)


def _resource_assessment(prepared: PreparedAnalysis) -> tuple[object, str]:
    ia = prepared.inspected.aligned_a
    ib = prepared.inspected.aligned_b
    if ia is None or ib is None:
        return None, "### Compute readiness: unavailable until sample alignment succeeds."
    a = assess_resources(
        samples=len(ia), features_a=ia.shape[1], features_b=ib.shape[1],
        file_a=prepared.resolved_paths["dataset_a"], file_b=prepared.resolved_paths["dataset_b"],
        config=prepared.inspected.config,
    )
    return a, resource_markdown(a, method=prepared.spec.method, permutations=prepared.spec.correlation.spearman_permutations)


def _new_browser_artifact_root(prefix: str) -> Path:
    # Put generated downloads directly under Gradio's cache. Because the returned
    # paths are already within GRADIO_CACHE, Gradio serves them in place instead
    # of making an additional hash-cache copy that would escape session cleanup.
    cache_root = Path(get_upload_folder())
    cache_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=cache_root))


def _temp_spec_file(spec: AnalysisSpec) -> tuple[str, Path]:
    root = _new_browser_artifact_root("biostat_spec_")
    path = root / "analysis.json"
    path.write_text(spec.canonical_json(), encoding="utf-8")
    return str(path), root


def _discard_bundle(path: str | None) -> None:
    if not path:
        return
    try:
        p = Path(path)
        root = p.parent if p.suffix == ".zip" else p
        if root.name.startswith("biostat_web_") or root.parent.name.startswith("biostat_web_"):
            shutil.rmtree(root if root.name.startswith("biostat_web_") else root.parent, ignore_errors=True)
    except Exception:
        pass


def inspect_callback(*args, request: Optional[gr.Request] = None):
    generation = _bump_generation(request)
    _cleanup_session_artifacts(request)
    session_key = _session_key(request)
    empty = pd.DataFrame()
    spec_path: str | None = None
    spec_root: Path | None = None
    try:
        spec, overrides = _build_spec_and_overrides(*args, expected_identity=_restored_identity(request))
        prepared = prepare_analysis(spec, path_overrides=overrides)
        example_issues = _synthetic_example_metadata_issues(spec)
        platform_warning_ids = tuple(issue["issue_id"] for issue in example_issues if issue["severity"] == "WARNING")
        # Render the browser issue table before adding the same teaching warnings
        # to provenance advisories, avoiding duplicate rows in Readiness.
        issues_df = _issues_df(prepared, example_issues)
        if example_issues:
            example_advisories = tuple({
                "code": issue["code"],
                "level": issue["severity"],
                "message": issue["message"],
            } for issue in example_issues)
            prepared = replace(prepared, policy_advisories=tuple(prepared.policy_advisories) + example_advisories)
        all_warning_ids = tuple(prepared.warning_issue_ids) + platform_warning_ids
        spec_path, spec_root = _temp_spec_file(spec)
        status = "BLOCKED" if prepared.blocked else ("WARNING" if all_warning_ids else "PASS")
        detail = "" if prepared.blocked else "Correlation results are unadjusted marginal associations; covariates and batch effects are not adjusted here."
        msg = _readiness_banner(
            status, fingerprint=prepared.inspected.fingerprint,
            warning_count=len(all_warning_ids), detail=detail,
        )
        metrics_df = _metrics_df(prepared)
        alignment_df = _alignment_df(prepared)
        alignment_detail = _alignment_detail_df(prepared)
        qc = pd.concat([_feature_qc(prepared.inspected.a, "Dataset A"), _feature_qc(prepared.inspected.b, "Dataset B")], ignore_index=True)
        _, limits_md = _resource_assessment(prepared)
        canonical_json = spec.canonical_json()
    except Exception as exc:
        if spec_root:
            shutil.rmtree(spec_root, ignore_errors=True)
        return (
            f"<div class='readiness-banner status-blocked'><div class='readiness-title'>Inspection failed</div><div>{html.escape(type(exc).__name__ + ': ' + str(exc))}</div></div>",
            empty, empty, empty, "", None, False, empty, None, None, None,
            "### Compute readiness: unavailable", empty, empty,
        )
    if not _current(request, generation):
        if spec_root:
            shutil.rmtree(spec_root, ignore_errors=True)
        return ("<div class='readiness-banner status-info'><b>Inspection superseded.</b> Inspect the current inputs again.</div>", empty, empty, empty, "", None, False, empty, None, None, None, "", empty, empty)
    if spec_root:
        _register_session_artifact(request, spec_root)
    state = WebPreparedState(
        prepared=prepared, session_key=session_key, generation=generation,
        platform_warning_issue_ids=platform_warning_ids, platform_issues=example_issues,
    )
    return (
        msg, issues_df, metrics_df, alignment_df, canonical_json, state, False, empty, None, spec_path, None,
        limits_md, qc, alignment_detail,
    )

def analyze_callback(state: WebPreparedState | None, acknowledge: bool, *, request: Optional[gr.Request] = None):
    empty = pd.DataFrame()
    blank_selector = gr.Dropdown(choices=[], value=None, allow_custom_value=True)
    blank_features = gr.Dropdown(choices=[], value=[], multiselect=True)
    if state is None:
        return "<div class='analysis-gate status-info'><b>No inspected run.</b> Complete Step 2 first.</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
    if not isinstance(state, WebPreparedState):
        return "<div class='analysis-gate status-warning'><b>Inspection state is obsolete.</b> Inspect the current inputs again.</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
    generation = _current_generation(request)
    if state.session_key != _session_key(request) or state.generation != generation:
        return "<div class='analysis-gate status-warning'><b>Inspection superseded.</b> Inspect the current inputs again.</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
    prepared = state.prepared
    all_warning_ids = _web_warning_issue_ids(state)
    if prepared.blocked:
        return "<div class='analysis-gate status-blocked'><b>Analysis blocked.</b> Resolve the blocking Readiness findings and inspect again before inference.</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
    if all_warning_ids and not acknowledge:
        return "<div class='analysis-gate status-warning'><b>Warning acknowledgement required.</b> Review Readiness findings and acknowledge this exact inspected request.</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
    try:
        completed = execute_prepared(
            prepared, acknowledge_warnings=bool(acknowledge and prepared.warning_issue_ids), backend="auto"
        )
        if state.platform_warning_issue_ids:
            execution_metadata = dict(completed.execution_metadata)
            execution_metadata["browser_acknowledged_platform_warning_issue_ids"] = (
                list(state.platform_warning_issue_ids) if acknowledge else []
            )
            completed = replace(completed, execution_metadata=execution_metadata)
        if not _current(request, generation):
            return "## Analysis superseded", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
        temp_root = _new_browser_artifact_root("biostat_web_")
        _register_session_artifact(request, temp_root)
        run_dir = default_run_directory(temp_root, prepared.inspected.fingerprint)
        run_dir = write_run_bundle(completed, run_dir)
        zip_path = zip_run_bundle(run_dir)
        effective_spec_path = run_dir / "analysis.json"
        csv_path = run_dir / "results" / "correlations.csv"
        report_path = run_dir / "report" / "report.html"
        if not _current(request, generation):
            shutil.rmtree(temp_root, ignore_errors=True)
            return "## Analysis superseded", empty, None, None, None, None, blank_selector, None, blank_features, blank_features
        preview = _result_preview_df(completed.primary_results)
        actual_backend = completed.execution_metadata.get("actual_backend", "unknown")
        fallback = completed.execution_metadata.get("fallback_reason", "")
        backend_line = _computation_engine_display(actual_backend, fallback)
        valid = completed.primary_results.loc[completed.primary_results["status"].eq("ok")].copy()
        teaching = teaching_plot_presets()
        curated: list[tuple[str, str]] = []
        ordinary: list[tuple[str, str]] = []
        for r in valid.head(5000).itertuples():
            a, b = str(r.feature_a), str(r.feature_b)
            encoded = json.dumps([a, b], ensure_ascii=False)
            preset = teaching.get((a, b))
            if preset:
                curated.append((f"Teaching - {preset['label']}: {a} | {b}", encoded))
            else:
                ordinary.append((f"{a} | {b}", encoded))
        selector_choices = curated + ordinary
        selector = gr.Dropdown(
            choices=selector_choices,
            value=(selector_choices[0][1] if selector_choices else None),
            allow_custom_value=True,
        )
        cstate = WebCompletedState(completed=completed, prepared=prepared, session_key=state.session_key, generation=generation, artifact_root=str(temp_root))
        ranked = valid.sort_values(["q_value", "p_value"], na_position="last")
        default_a = list(dict.fromkeys(ranked["feature_a"].astype(str).tolist()))[:4]
        default_b = list(dict.fromkeys(ranked["feature_b"].astype(str).tolist()))[:4]
        feature_a_update = gr.Dropdown(choices=[str(x) for x in prepared.inspected.aligned_a.columns], value=default_a, multiselect=True, max_choices=HEATMAP_MAX_PER_AXIS)
        feature_b_update = gr.Dropdown(choices=[str(x) for x in prepared.inspected.aligned_b.columns], value=default_b, multiselect=True, max_choices=HEATMAP_MAX_PER_AXIS)
        return (
            f"<div class='analysis-gate status-pass'><b>Analysis complete.</b> RunBundle schema 1.0; {len(completed.primary_results):,} result rows. Browser preview capped at {RESULT_PREVIEW_ROWS:,} rows.<br>{html.escape(backend_line)}</div>",
            preview, str(zip_path), str(effective_spec_path), str(csv_path), str(report_path), selector, cstate, feature_a_update, feature_b_update,
        )
    except Exception as exc:
        return f"<div class='analysis-gate status-blocked'><b>Analysis failed.</b> {html.escape(type(exc).__name__ + ': ' + str(exc))}</div>", empty, None, None, None, None, blank_selector, None, blank_features, blank_features


def plot_pair_callback(cstate: WebCompletedState | None, selector: str | None, view: str, *, request: Optional[gr.Request] = None):
    if cstate is None or not selector:
        return None, "Select an analyzed feature pair.", None, None, None
    if cstate.session_key != _session_key(request) or cstate.generation != _current_generation(request):
        return None, "Analysis state is obsolete; inspect and run again.", None, None, None
    try:
        decoded = json.loads(selector)
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(x, str) for x in decoded):
            raise ValueError("Malformed feature-pair selector value.")
        feature_a, feature_b = decoded
        results = cstate.completed.primary_results
        row = results.loc[(results["feature_a"].astype(str) == feature_a) & (results["feature_b"].astype(str) == feature_b)]
        if len(row) != 1:
            raise ValueError("Selected feature pair is not uniquely present in results.")
        r = row.iloc[0]
        data = pairwise_complete_data(cstate.prepared.inspected.aligned_a, cstate.prepared.inspected.aligned_b, feature_a, feature_b)
        if int(r["n_pairwise"]) != data.n_pairwise:
            raise RuntimeError("Plot pairwise sample mask does not match the statistical result N.")
        fig = make_pair_figure(data, method=str(r["method"]), estimate=float(r["estimate"]), p_value=float(r["p_value"]), q_value=float(r["q_value"]), view=view)
        png, svg, pdf = _figure_export_paths(cstate, fig, f"{feature_a}_vs_{feature_b}_{view}", request=request)
        meta = (f"**{feature_a} × {feature_b}** — {str(r['method']).title()} estimate `{float(r['estimate']):.6g}`, "
                f"N `{data.n_pairwise}`, missing/excluded `{data.missing_or_excluded}`, p `{float(r['p_value']):.6g}`, BH q `{float(r['q_value']):.6g}`.")
        if str(r["method"]) == "spearman":
            p_method = str(r.get("p_value_method", ""))
            permutations = r.get("permutations", "")
            if pd.notna(permutations) and str(permutations) != "":
                permutations_text = str(int(float(permutations)))
            else:
                permutations_text = ""
            meta += f" Inference: `{p_method}`"
            if permutations_text:
                meta += f"; permutations `{permutations_text}`"
            meta += "."
        preset = teaching_plot_presets().get((feature_a, feature_b))
        if preset and preset.get("description"):
            meta += f" Teaching pattern: {preset['description']}"
        meta += " Figure export contains sample-level coordinates and should be treated according to data sensitivity."
        return _publish_visualization_result(cstate, request, fig, meta, (png, svg, pdf))
    except _VisualizationSuperseded:
        return _visualization_superseded_result()
    except Exception as exc:
        return None, f"Plot failed: `{type(exc).__name__}: {exc}`", None, None, None



def _require_completed_state(cstate: WebCompletedState | None, request: Optional[gr.Request]) -> WebCompletedState:
    if cstate is None:
        raise ValueError("Run an analysis before building result figures.")
    if cstate.session_key != _session_key(request) or cstate.generation != _current_generation(request):
        raise ValueError("Analysis state is obsolete; inspect and run again.")
    return cstate


def _completed_state_is_current(cstate: WebCompletedState, request: Optional[gr.Request]) -> bool:
    return cstate.session_key == _session_key(request) and cstate.generation == _current_generation(request)


def _discard_completed_artifact_root(cstate: WebCompletedState) -> None:
    shutil.rmtree(Path(cstate.artifact_root), ignore_errors=True)


def _ensure_visualization_current(cstate: WebCompletedState, request: Optional[gr.Request]) -> None:
    if not _completed_state_is_current(cstate, request):
        _discard_completed_artifact_root(cstate)
        raise _VisualizationSuperseded("Visualization was superseded by newer session state.")


def _figure_export_paths(
    cstate: WebCompletedState, fig, stem: str, *, request: Optional[gr.Request] = None
) -> tuple[str, str, str]:
    # Rendering can be expensive. Recheck generation immediately before export so
    # invalidation cannot be followed by recreating a deleted artifact directory.
    _ensure_visualization_current(cstate, request)
    root = Path(cstate.artifact_root) / "figures"
    paths = export_figure(fig, root, stem)
    # Invalidation can also occur inside savefig(). If so, remove any files or
    # directories recreated by the stale export before control returns to Gradio.
    _ensure_visualization_current(cstate, request)
    return paths


def _publish_visualization_result(
    cstate: WebCompletedState, request: Optional[gr.Request], fig, meta: str, paths: tuple[str, str, str]
):
    _ensure_visualization_current(cstate, request)
    return fig, meta, *paths


def _visualization_superseded_result():
    return None, "Visualization superseded by newer session state; render again.", None, None, None


def heatmap_callback(cstate: WebCompletedState | None, features_a, features_b, q_threshold: float, emphasize_q: bool,
                     *, request: Optional[gr.Request] = None):
    try:
        state = _require_completed_state(cstate, request)
        q = float(q_threshold)
        if not (0 < q <= 1):
            raise ValueError("q threshold must be > 0 and ≤ 1.")
        fig = make_heatmap_figure(state.completed.primary_results, features_a or [], features_b or [], q_threshold=q, emphasize_q=bool(emphasize_q))
        png, svg, pdf = _figure_export_paths(state, fig, "association_heatmap", request=request)
        meta = (f"**Heatmap** — {len(features_a or [])} Dataset A × {len(features_b or [])} Dataset B features. "
                f"Color is the validated {state.prepared.spec.method} coefficient. "
                + (f"Associations with BH q > {q:g} are visually de-emphasized. " if emphasize_q else "")
                + "No new inferential family is computed by this figure.")
        return _publish_visualization_result(state, request, fig, meta, (png, svg, pdf))
    except _VisualizationSuperseded:
        return _visualization_superseded_result()
    except Exception as exc:
        return None, f"Heatmap unavailable: `{type(exc).__name__}: {exc}`", None, None, None


def correlogram_callback(cstate: WebCompletedState | None, features_a, features_b, q_threshold: float,
                         *, request: Optional[gr.Request] = None):
    try:
        state = _require_completed_state(cstate, request)
        q = float(q_threshold)
        if not (0 < q <= 1):
            raise ValueError("q threshold must be > 0 and ≤ 1.")
        same_variable_space = (
            state.prepared.spec.dataset_a.sha256.lower()
            == state.prepared.spec.dataset_b.sha256.lower()
        )
        fig = make_correlogram_figure(
            state.completed.primary_results,
            features_a or [],
            features_b or [],
            q_threshold=q,
            same_variable_space=same_variable_space,
        )
        png, svg, pdf = _figure_export_paths(state, fig, "correlation_correlogram", request=request)
        n_cells = len(features_a or []) * len(features_b or [])
        values_note = "Cell values are printed." if n_cells <= 144 else "Cell values are hidden for readability."
        meta = (f"**Correlogram** — cell color encodes the validated {state.prepared.spec.method} coefficient; "
                f"`*` marks BH q ≤ {q:g}. {values_note} Up to {CORRELOGRAM_MAX_PER_AXIS} features per axis may be selected; "
                "a lower-triangle view is used only when the two inputs have verified identical source bytes, matching selected feature names, and a symmetric coefficient matrix.")
        return _publish_visualization_result(state, request, fig, meta, (png, svg, pdf))
    except _VisualizationSuperseded:
        return _visualization_superseded_result()
    except Exception as exc:
        return None, f"Correlogram unavailable: `{type(exc).__name__}: {exc}`", None, None, None


def bubble_callback(cstate: WebCompletedState | None, features_a, features_b, q_threshold: float, size_by: str,
                    *, request: Optional[gr.Request] = None):
    try:
        state = _require_completed_state(cstate, request)
        q = float(q_threshold)
        if not (0 < q <= 1):
            raise ValueError("q threshold must be > 0 and ≤ 1.")
        fig = make_bubble_figure(state.completed.primary_results, features_a or [], features_b or [], q_threshold=q, size_by=str(size_by))
        png, svg, pdf = _figure_export_paths(state, fig, "association_bubble", request=request)
        size_text = (
            f"bubble area emphasizes `|{state.prepared.spec.method} coefficient|`"
            if str(size_by) == "effect"
            else "bubble area emphasizes `-log10(BH q)` (capped for display)"
        )
        meta = (f"**Bubble plot** — each point is one validated A×B association. X = signed {state.prepared.spec.method} coefficient; "
                f"Y = `-log10(BH q)`; {size_text}; color also encodes coefficient sign/magnitude. "
                f"The dashed line marks BH q = {q:g}. At most {BUBBLE_MAX_POINTS} selected associations are rendered.")
        return _publish_visualization_result(state, request, fig, meta, (png, svg, pdf))
    except _VisualizationSuperseded:
        return _visualization_superseded_result()
    except Exception as exc:
        return None, f"Bubble plot unavailable: `{type(exc).__name__}: {exc}`", None, None, None


def scatter_matrix_callback(cstate: WebCompletedState | None, features_a, features_b, *, request: Optional[gr.Request] = None):
    try:
        state = _require_completed_state(cstate, request)
        total = len(features_a or []) + len(features_b or [])
        if total > SCATTER_MATRIX_MAX_VARIABLES:
            raise ValueError(f"Select at most {SCATTER_MATRIX_MAX_VARIABLES} variables total for the scatter matrix.")
        fig = make_scatter_matrix_figure(
            state.prepared.inspected.aligned_a, state.prepared.inspected.aligned_b,
            state.completed.primary_results, features_a or [], features_b or [],
        )
        png, svg, pdf = _figure_export_paths(state, fig, "selected_feature_scatter_matrix", request=request)
        meta = (f"**Scatter matrix** — {total} selected variables. Lower panels show raw sample-level relationships. "
                "Upper panels display inferential coefficients only when that A×B pair already exists in the validated result family; "
                "within-dataset panels add no new correlation tests.")
        return _publish_visualization_result(state, request, fig, meta, (png, svg, pdf))
    except _VisualizationSuperseded:
        return _visualization_superseded_result()
    except Exception as exc:
        return None, f"Scatter matrix unavailable: `{type(exc).__name__}: {exc}`", None, None, None


def scatter_matrix_selection_ui(features_a, features_b):
    total = len(features_a or []) + len(features_b or [])
    remaining = SCATTER_MATRIX_MAX_VARIABLES - total
    if total < 2:
        text = f"<div class='biostat-selection-counter'>Selected: <b>{total} / {SCATTER_MATRIX_MAX_VARIABLES}</b>. Select at least 2 variables. A scatter matrix grows as an N×N panel grid.</div>"
        return text, gr.Button(value="Render scatter matrix", variant="primary", interactive=False)
    if remaining < 0:
        text = f"<div class='biostat-selection-counter bad'>Selected: <b>{total} / {SCATTER_MATRIX_MAX_VARIABLES}</b> — remove {-remaining} variable(s). Larger scatter matrices become unreadable and expensive; use Heatmap or Correlogram for larger feature sets.</div>"
        return text, gr.Button(value="Remove variables before rendering", variant="stop", interactive=False)
    text = f"<div class='biostat-selection-counter ok'>Selected: <b>{total} / {SCATTER_MATRIX_MAX_VARIABLES}</b>. The matrix will contain {total * total} panels. {remaining} additional variable(s) can be selected.</div>"
    return text, gr.Button(value="Render scatter matrix", variant="primary", interactive=True)


def pair_feature_controls_ui(cstate: WebCompletedState | None):
    if not isinstance(cstate, WebCompletedState):
        return gr.Dropdown(choices=[], value=None), gr.Dropdown(choices=[], value=None)
    valid = cstate.completed.primary_results.loc[cstate.completed.primary_results["status"].eq("ok")].copy()
    if valid.empty:
        return gr.Dropdown(choices=[], value=None), gr.Dropdown(choices=[], value=None)
    ranked = valid.sort_values(["q_value", "p_value"], na_position="last")
    a_choices = list(dict.fromkeys(ranked["feature_a"].astype(str).tolist()))
    first_a = a_choices[0] if a_choices else None
    b_choices = list(dict.fromkeys(ranked.loc[ranked["feature_a"].astype(str).eq(first_a), "feature_b"].astype(str).tolist())) if first_a else []
    first_b = b_choices[0] if b_choices else None
    return gr.Dropdown(choices=a_choices, value=first_a, filterable=True), gr.Dropdown(choices=b_choices, value=first_b, filterable=True)


def pair_feature_b_ui(cstate: WebCompletedState | None, feature_a: str | None):
    if not isinstance(cstate, WebCompletedState) or not feature_a:
        return gr.Dropdown(choices=[], value=None)
    valid = cstate.completed.primary_results
    mask = valid["status"].eq("ok") & valid["feature_a"].astype(str).eq(str(feature_a))
    subset = valid.loc[mask].sort_values(["q_value", "p_value"], na_position="last")
    choices = list(dict.fromkeys(subset["feature_b"].astype(str).tolist()))
    return gr.Dropdown(choices=choices, value=(choices[0] if choices else None), filterable=True)


def pair_selector_from_features(feature_a: str | None, feature_b: str | None):
    if not feature_a or not feature_b:
        return None
    return json.dumps([str(feature_a), str(feature_b)], ensure_ascii=False)


def _rank_associations(results: pd.DataFrame, ranking: str, n: int) -> pd.DataFrame:
    valid = results.loc[results["status"].eq("ok")].copy()
    valid["estimate"] = pd.to_numeric(valid["estimate"], errors="coerce")
    valid["q_value"] = pd.to_numeric(valid["q_value"], errors="coerce")
    valid["p_value"] = pd.to_numeric(valid["p_value"], errors="coerce")
    valid = valid.loc[np.isfinite(valid["estimate"]) & np.isfinite(valid["q_value"])].copy()
    valid["abs_estimate"] = valid["estimate"].abs()
    if ranking == "q_value":
        ordered = valid.sort_values(["q_value", "abs_estimate", "p_value"], ascending=[True, False, True], na_position="last")
    elif ranking == "abs_effect":
        ordered = valid.sort_values(["abs_estimate", "q_value", "p_value"], ascending=[False, True, True], na_position="last")
    elif ranking == "positive":
        ordered = valid.sort_values(["estimate", "q_value"], ascending=[False, True], na_position="last")
    elif ranking == "negative":
        ordered = valid.sort_values(["estimate", "q_value"], ascending=[True, True], na_position="last")
    elif ranking == "significant":
        ordered = valid.loc[valid["q_value"] <= 0.05].sort_values(["q_value", "abs_estimate"], ascending=[True, False], na_position="last")
    else:
        raise ValueError("Unknown association ranking rule.")
    return ordered.head(int(n)).drop(columns=["abs_estimate"], errors="ignore")


def association_report_callback(cstate: WebCompletedState | None, top_n: int, ranking: str, *, request: Optional[gr.Request] = None):
    try:
        state = _require_completed_state(cstate, request)
        n = _coerce_int(top_n, "Top associations", 1)
        if n not in {10, 25, 50}:
            raise ValueError("Top associations must be 10, 25, or 50.")
        ranked = _rank_associations(state.completed.primary_results, str(ranking), n)
        if ranked.empty:
            raise ValueError("No eligible associations match the selected ranking rule.")
        _ensure_visualization_current(state, request)
        root = Path(state.artifact_root) / "association_reports"
        root.mkdir(parents=True, exist_ok=True)
        pdf_path = root / f"top_{len(ranked)}_associations_{ranking}.pdf"
        zip_path = root / f"top_{len(ranked)}_association_pngs_{ranking}.zip"
        summary_path = root / f"top_{len(ranked)}_associations_{ranking}.csv"
        ranked.to_csv(summary_path, index=False)
        png_paths: list[Path] = []
        with PdfPages(pdf_path) as pdf:
            cover = plt.figure(figsize=(8.5, 11))
            cover_ax = cover.add_axes([0, 0, 1, 1])
            cover_ax.axis("off")
            cover.text(0.08, 0.92, "Biostat Research Tool — top association report", fontsize=18, fontweight="bold")
            cover.text(0.08, 0.87, f"Ranking: {ranking}   ·   Associations: {len(ranked)}", fontsize=11)
            cover.text(0.08, 0.83, f"Method: {state.prepared.spec.method}   ·   Run fingerprint: {state.prepared.inspected.fingerprint}", fontsize=9, wrap=True)
            cover.text(0.08, 0.77, "Each following page is generated from the exact pairwise-complete samples underlying the validated result. Statistical results are unadjusted marginal associations.", fontsize=10, wrap=True)
            cover.text(0.08, 0.70, "Ranking definitions: q_value = lowest BH q; abs_effect = largest |correlation|; positive/negative = signed effect; significant = BH q ≤ 0.05.", fontsize=9, wrap=True)
            pdf.savefig(cover, bbox_inches="tight")
            plt.close(cover)
            for idx, row in enumerate(ranked.itertuples(index=False), start=1):
                _ensure_visualization_current(state, request)
                feature_a = str(row.feature_a)
                feature_b = str(row.feature_b)
                data = pairwise_complete_data(state.prepared.inspected.aligned_a, state.prepared.inspected.aligned_b, feature_a, feature_b)
                view = "raw"
                try:
                    fig = make_pair_figure(data, method=str(row.method), estimate=float(row.estimate), p_value=float(row.p_value), q_value=float(row.q_value), view=view)
                except ValueError as exc:
                    if str(row.method) == "spearman" and "collapse distinct integer coordinates" in str(exc):
                        view = "ranks"
                        fig = make_pair_figure(data, method=str(row.method), estimate=float(row.estimate), p_value=float(row.p_value), q_value=float(row.q_value), view=view)
                    else:
                        raise
                pdf.savefig(fig, bbox_inches="tight")
                safe_a = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in feature_a)[:50]
                safe_b = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in feature_b)[:50]
                png = root / f"{idx:03d}_{safe_a}_vs_{safe_b}_{view}.png"
                fig.savefig(png, dpi=300, bbox_inches="tight")
                png_paths.append(png)
                plt.close(fig)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(summary_path, arcname=summary_path.name)
            for png in png_paths:
                zf.write(png, arcname=png.name)
        _ensure_visualization_current(state, request)
        return f"Generated {len(ranked)} association pages using ranking rule `{ranking}`.", str(pdf_path), str(zip_path)
    except _VisualizationSuperseded:
        return "Association report superseded by newer session state; generate again.", None, None
    except Exception as exc:
        return f"Association report unavailable: `{type(exc).__name__}: {exc}`", None, None


def association_report_ui(request: gr.Request, cstate, top_n, ranking):
    result = association_report_callback(cstate, top_n, ranking, request=request)
    if isinstance(cstate, WebCompletedState) and not _completed_state_is_current(cstate, request):
        _discard_completed_artifact_root(cstate)
        return "Association report superseded by newer session state; generate again.", None, None
    return result

def _invalidated_run_values(message: str):
    return None, False, pd.DataFrame(), None, None, None, message, None, None, None, None, None, None


def invalidate_run_state(*, request: Optional[gr.Request] = None):
    _replace_request_session(request)
    return _invalidated_run_values("## Inputs changed\nInspect the current inputs before analysis.")


def replacement_run_state_ui():
    """Clear browser-held run state after a successful request replacement.

    Session generation/artifact invalidation already occurs inside the
    successful Load Example / Restore callback. This function only clears the
    corresponding Gradio component values without bumping generation again.
    """
    return _invalidated_run_values("## New request loaded\nInspect and validate the current inputs before analysis.")


def clear_readiness_outputs_ui():
    empty = pd.DataFrame()
    return empty, empty, empty, "", "", empty, empty


def inspect_ui(request: gr.Request, *args):
    result = inspect_callback(*args, request=request)
    state = result[5] if len(result) > 5 else None
    if isinstance(state, WebPreparedState):
        if state.session_key != _session_key(request) or not _current(request, state.generation):
            return ("## Inspection superseded", pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "", None, False, pd.DataFrame(), None, None, None, "", pd.DataFrame(), pd.DataFrame())
    return result


def analyze_ui(request: gr.Request, state, acknowledge):
    generation = _current_generation(request)
    result = analyze_callback(state, acknowledge, request=request)
    if not _current(request, generation):
        _discard_bundle(result[2] if len(result) > 2 else None)
        blank = gr.Dropdown(choices=[], value=[], multiselect=True)
        return "## Analysis superseded", pd.DataFrame(), None, None, None, None, gr.Dropdown(choices=[], value=None), None, blank, blank
    return result


def invalidate_ui(request: gr.Request):
    return invalidate_run_state(request=request)


def _visualization_ui_guard(request: gr.Request, cstate, result):
    # Final publication guard: a callback can finish just as another input event
    # invalidates the run. Never publish that stale figure or its download paths.
    if isinstance(cstate, WebCompletedState) and not _completed_state_is_current(cstate, request):
        _discard_completed_artifact_root(cstate)
        return _visualization_superseded_result()
    return result


def plot_pair_ui(request: gr.Request, cstate, selector, view):
    return _visualization_ui_guard(request, cstate, plot_pair_callback(cstate, selector, view, request=request))


def heatmap_ui(request: gr.Request, cstate, features_a, features_b, q_threshold, emphasize_q):
    return _visualization_ui_guard(request, cstate, heatmap_callback(cstate, features_a, features_b, q_threshold, emphasize_q, request=request))


def correlogram_ui(request: gr.Request, cstate, features_a, features_b, q_threshold):
    return _visualization_ui_guard(request, cstate, correlogram_callback(cstate, features_a, features_b, q_threshold, request=request))


def bubble_ui(request: gr.Request, cstate, features_a, features_b, q_threshold, size_by):
    return _visualization_ui_guard(request, cstate, bubble_callback(cstate, features_a, features_b, q_threshold, size_by, request=request))


def scatter_matrix_ui(request: gr.Request, cstate, features_a, features_b):
    return _visualization_ui_guard(request, cstate, scatter_matrix_callback(cstate, features_a, features_b, request=request))


def figure_controls_visibility_ui(view: str):
    """Show only controls relevant to the active figure type.

    Association uses a single analyzed pair; summary views use multi-feature
    selectors. The q threshold, heatmap emphasis, and bubble sizing controls
    appear only where they are meaningful.
    """
    key = str(view or "association").lower()
    association = key == "association"
    summary = key in {"heatmap", "correlogram", "bubble", "scatter"}
    q_control = key in {"heatmap", "correlogram", "bubble"}
    heatmap = key == "heatmap"
    bubble = key == "bubble"
    return (
        gr.update(visible=association),
        gr.update(visible=summary),
        gr.update(visible=q_control),
        gr.update(visible=heatmap),
        gr.update(visible=bubble),
    )


def clear_visual_ui():
    blank_pair = gr.Dropdown(choices=[], value=None, allow_custom_value=True)
    blank_features = gr.Dropdown(choices=[], value=[], multiselect=True)
    return (
        blank_pair, blank_features, blank_features,
        None, "Select a result pair after analysis.", None, None, None,
        None, "Choose a feature subset after analysis.", None, None, None,
        None, "Choose a feature subset after analysis.", None, None, None,
        None, "Choose a feature subset after analysis.", None, None, None,
        None, "Choose at most nine total variables after analysis.", None, None, None,
        "", None, None,
    )


def _loaded_spec_outputs(spec: AnalysisSpec):
    return (
        spec.dataset_a.data_type,
        gr.Dropdown(choices=preprocessing_display_choices(spec.dataset_a.data_type), value=spec.dataset_a.preprocessing),
        spec.dataset_a.preprocessing_details,
        spec.dataset_a.orientation,
        ",".join(token for token in spec.dataset_a.missing_tokens if token),
        spec.dataset_b.data_type,
        gr.Dropdown(choices=preprocessing_display_choices(spec.dataset_b.data_type), value=spec.dataset_b.preprocessing),
        spec.dataset_b.preprocessing_details,
        spec.dataset_b.orientation,
        ",".join(token for token in spec.dataset_b.missing_tokens if token),
        spec.study_design.observation_structure,
        spec.study_design.notes,
        spec.method,
        spec.correlation.minimum_pairwise_n,
        spec.correlation.spearman_permutations,
        spec.correlation.random_seed,
        "AnalysisSpec settings loaded. Select the two source datasets; restored SHA-256 identities will be enforced during inspection.",
    )


def load_spec_callback(spec_file):
    if spec_file is None:
        raise gr.Error("Choose an AnalysisSpec JSON file first.")
    return _loaded_spec_outputs(load_analysis_spec(str(spec_file)))


def load_spec_ui(request: gr.Request, spec_file):
    if spec_file is None:
        return (*([gr.skip()] * 16), "⚠️ Choose a saved analysis setup (AnalysisSpec JSON) before restoring settings.")
    # Parse successfully before invalidating the current request. A malformed
    # file must not destroy a still-valid inspected/completed analysis.
    spec = load_analysis_spec(str(spec_file))
    _replace_request_session(request)
    _clear_restored_identity(request)
    _set_restored_identity(request, spec)
    return _loaded_spec_outputs(spec)


def clear_restored_identity_ui(request: gr.Request):
    _clear_restored_identity(request)
    return "Restored dataset identity cleared. Current inputs will define a new AnalysisSpec on inspection."


def clear_restored_identity_for_example_ui(request: gr.Request):
    _clear_restored_identity(request)
    return ""


def inspection_controls_ui(state: WebPreparedState | None):
    if not isinstance(state, WebPreparedState):
        return (
            gr.Button(value="Inspect & validate inputs →", variant="primary"),
            gr.Button(value="3. Run inspected analysis", variant="primary", interactive=False),
            _analysis_gate_html(None),
            _workflow_guide_html(stage=2, state="active"),
        )
    prepared = state.prepared
    extra_warning_count = len(state.platform_warning_issue_ids)
    if prepared.blocked:
        return (
            gr.Button(value="× Inspection blocked — review Readiness", variant="stop"),
            gr.Button(value="Resolve blocked issues before analysis", variant="stop", interactive=False),
            _analysis_gate_html(prepared, extra_warning_count=extra_warning_count),
            _workflow_guide_html(stage=2, state="blocked"),
        )
    if prepared.warning_issue_ids or extra_warning_count:
        return (
            gr.Button(value="! Inspected — warnings found", variant="secondary"),
            gr.Button(value="3. Acknowledge warnings to enable analysis", variant="primary", interactive=False),
            _analysis_gate_html(prepared, extra_warning_count=extra_warning_count),
            _workflow_guide_html(stage=2, state="warning"),
        )
    return (
        gr.Button(value="✓ Inspected — PASS", variant="secondary"),
        gr.Button(value="3. Run inspected analysis", variant="primary", interactive=True),
        _analysis_gate_html(prepared, extra_warning_count=extra_warning_count),
        _workflow_guide_html(stage=2, state="complete"),
    )


def acknowledgement_gate_ui(state: WebPreparedState | None, acknowledge: bool):
    if not isinstance(state, WebPreparedState):
        return gr.Button(value="3. Run inspected analysis", variant="primary", interactive=False), _analysis_gate_html(None)
    prepared = state.prepared
    extra_warning_count = len(state.platform_warning_issue_ids)
    has_warnings = bool(prepared.warning_issue_ids or extra_warning_count)
    if prepared.blocked:
        return gr.Button(value="Resolve blocked issues before analysis", variant="stop", interactive=False), _analysis_gate_html(prepared, extra_warning_count=extra_warning_count)
    if has_warnings and not acknowledge:
        return gr.Button(value="3. Acknowledge warnings to enable analysis", variant="primary", interactive=False), _analysis_gate_html(prepared, extra_warning_count=extra_warning_count)
    label = "3. Run inspected analysis" if not has_warnings else "3. Run inspected analysis — warnings acknowledged"
    return gr.Button(value=label, variant="primary", interactive=True), _analysis_gate_html(prepared, extra_warning_count=extra_warning_count)


def workflow_loaded_ui():
    return _workflow_guide_html(stage=1, state="complete")


def workflow_analyzed_ui(cstate: WebCompletedState | None):
    return _workflow_guide_html(stage=4, state="active") if isinstance(cstate, WebCompletedState) else _workflow_guide_html(stage=3, state="active")



def analysis_completion_ui(cstate: WebCompletedState | None):
    if isinstance(cstate, WebCompletedState):
        return (
            "<div class='analysis-gate status-pass'><b>Analysis complete.</b> Continue to Step 4: Review results, then create figures.</div>",
            _workflow_guide_html(stage=4, state="active"),
        )
    return _analysis_gate_html(None), _workflow_guide_html(stage=3, state="active")


def invalidate_guidance_ui():
    return (
        gr.Button(value="Inspect & validate inputs →", variant="primary"),
        gr.Button(value="3. Run inspected analysis", variant="primary", interactive=False),
        _analysis_gate_html(None),
        _workflow_guide_html(stage=2, state="active"),
    )


def clear_pair_feature_ui():
    return gr.Dropdown(choices=[], value=None), gr.Dropdown(choices=[], value=None)


def invalidate_all_user_edit_ui(request: gr.Request):
    """Atomically invalidate one user edit with one generation bump/update event.

    RC15 replaces the RC14 four-callback pattern for every analysis-defining input.
    Rapid numeric edits could therefore enqueue several cancellation/cleanup jobs
    before a fresh inspection. This combined callback performs the same state and
    artifact clearing in a single lightweight event.
    """
    run_values = invalidate_run_state(request=request)
    return (
        *run_values[:10],  # association downloads are cleared by clear_visual_ui below
        *clear_visual_ui(),
        *clear_pair_feature_ui(),
        *invalidate_guidance_ui(),
    )


def replacement_cleanup_ui():
    """Clear all browser-held outputs after a successful request replacement."""
    return (
        *replacement_run_state_ui(),
        *clear_readiness_outputs_ui(),
        *clear_visual_ui(),
        *clear_pair_feature_ui(),
        *invalidate_guidance_ui(),
    )


def replacement_cleanup_for_example_ui():
    # Also clear any restored-spec note when an example becomes the active request.
    return (*replacement_cleanup_ui(), "")


def replacement_cleanup_for_spec_ui(spec_file):
    # U12: clicking Restore with no file is guidance only; it must not destroy a
    # valid current analysis. load_spec_ui also avoids session invalidation in
    # this case, so preserve every browser output with gr.skip().
    if spec_file is None:
        return tuple(gr.skip() for _ in range(57))
    return replacement_cleanup_ui()


APP_THEME = gr.themes.Soft(primary_hue="blue", secondary_hue="cyan", neutral_hue="slate", radius_size="md")

def build_demo() -> gr.Blocks:
    with gr.Blocks(title=f"Biostat Research Tool — {__version__}", fill_width=True) as demo:
        gr.HTML(
            f"""<div id='biostat-header'>
            <div class='biostat-header-copy'>
              <h1>Biostat Research Tool <span style='font-weight:400'>v{__version__}</span></h1>
              <p>Reproducible matrix-to-matrix correlation analysis for same-domain or cross-omics data, with explicit readiness checks, validated inference, and verifiable provenance.</p>
              <div class='badges'><span class='badge'>Local-first</span><span class='badge'>Saved analysis setup</span><span class='badge'>Verified RunBundle</span><span class='badge' title='Automatically uses an optimized validated computation engine when eligible and the reference engine otherwise. Statistical settings do not change.'>Computation: Automatic</span></div>
            </div>
            <div class='biostat-header-actions'>
              <button type='button' class='biostat-header-link' data-biostat-jump='biostat-nav-quickstart'>? Help</button>
              <button type='button' class='biostat-header-link' data-biostat-jump='biostat-nav-about'>ⓘ About</button>
              <div class='biostat-theme-switcher' role='group' aria-label='Display theme'>
                <button type='button' data-biostat-theme-choice='light' aria-pressed='false'>☀ Light</button>
                <button type='button' data-biostat-theme-choice='dark' aria-pressed='false'>☾ Dark</button>
                <button type='button' data-biostat-theme-choice='system' aria-pressed='true'>◐ System</button>
              </div>
            </div>
            </div>"""
        )

        prepared_state = gr.State()
        completed_state = gr.State()

        with gr.Sidebar(open=True, width=235, elem_classes='biostat-workstation-sidebar'):
            gr.HTML("<div class='biostat-side-heading'>Workflow</div>")
            workflow_guide = gr.HTML(WORKFLOW_GUIDE_HTML)
            nav_data = gr.Button("1  Data & design", elem_classes='biostat-nav-button')
            nav_readiness = gr.Button("2  Readiness", elem_classes='biostat-nav-button')
            nav_analysis = gr.Button("3  Analysis", elem_classes='biostat-nav-button')
            nav_results = gr.Button("4  Results", elem_classes='biostat-nav-button')
            nav_figures = gr.Button("5  Figures", elem_classes='biostat-nav-button')
            nav_provenance = gr.Button("6  Provenance", elem_classes='biostat-nav-button')
            gr.HTML("<div class='biostat-side-heading' style='margin-top:12px'>Learn</div>")
            nav_quickstart = gr.Button("Quick start", elem_id='biostat-nav-quickstart', elem_classes='biostat-nav-button')
            nav_videos = gr.Button("Video tutorials", elem_classes='biostat-nav-button')
            nav_docs = gr.Button("Documentation", elem_classes='biostat-nav-button')
            gr.HTML("<div class='biostat-side-heading' style='margin-top:12px'>Project</div>")
            nav_about = gr.Button("About", elem_id='biostat-nav-about', elem_classes='biostat-nav-button')
            gr.HTML("<div class='biostat-side-note'>Local analysis by default. Public Gradio sharing is disabled.</div>")

        with gr.Tabs(selected='data', elem_classes=['biostat-tabs','biostat-workstation-tabs'], elem_id='biostat-main-tabs') as main_tabs:
            with gr.Tab("Data & design", id='data'):
                gr.Markdown("### 1. Load data & define the analysis\nChoose one starting path below. The underlying analysis settings remain visible so you can review exactly what will be inspected.")
                gr.HTML(OMICS_SCOPE_HTML)

                with gr.Accordion("Synthetic example — learn the workflow with bundled data", open=True, elem_classes="biostat-compact-accordion"):
                    with gr.Row():
                        with gr.Column(scale=3):
                            _field_help("Synthetic example", "Loads a complete, fully synthetic demonstration dataset and recommended settings. The library includes both cross-omics and same-domain examples.")
                            example_key = gr.Dropdown(example_choices(), value="metabolomics_rnaseq", label="Synthetic example", show_label=False, filterable=True)
                        load_example = gr.Button("1. Load selected example", variant="secondary", scale=1)
                    example_note = gr.Markdown("No synthetic example has been loaded yet. Choose one above and click **1. Load selected example**.", elem_classes="biostat-example-status")

                with gr.Accordion("Restore a saved analysis setup (AnalysisSpec)", open=False, elem_classes="biostat-compact-accordion"):
                    gr.Markdown("Use this when reproducing or continuing a previous analysis. **AnalysisSpec** is the JSON file that records the expected dataset identities and analysis-defining settings.")
                    with gr.Row():
                        with gr.Column(scale=3):
                            _field_help("Saved analysis setup (AnalysisSpec JSON)", "A machine-readable JSON record of the expected datasets, correlation method, thresholds, and other settings. Restored dataset SHA-256 identities are enforced during inspection.")
                            spec_upload = gr.File(label="Saved analysis setup (AnalysisSpec JSON)", show_label=False, type="filepath")
                        load_spec_btn = gr.Button("Restore saved settings", scale=1)
                        new_request_btn = gr.Button("Start new request", scale=1)
                    spec_load_note = gr.Markdown()

                with gr.Accordion("Use two local matrices — start a new analysis", open=False, elem_classes="biostat-compact-accordion"):
                    gr.Markdown("Choose Dataset A and Dataset B. Samples are aligned by identifier before A×B correlations are calculated.")
                    with gr.Row():
                        with gr.Column():
                            _field_help("Matrix A", "The first numeric feature matrix. Samples may be rows or columns; sample identifiers are used for alignment with Dataset B.")
                            file_a = gr.File(label="Matrix A", show_label=False, type="filepath")
                        with gr.Column():
                            _field_help("Matrix B", "The second numeric feature matrix. Samples are aligned to Dataset A before any A×B correlation is computed.")
                            file_b = gr.File(label="Matrix B", show_label=False, type="filepath")

                with gr.Accordion("Current dataset declarations", open=True, elem_classes="biostat-compact-accordion"):
                    gr.HTML("<div class='biostat-declaration-note'>Review the scientific declarations that will be stored with the analysis. Blank/empty cells are always treated as missing.</div>")
                    with gr.Row(elem_classes="biostat-datasets"):
                        with gr.Column(elem_classes=["biostat-panel", "biostat-dataset-card"]):
                            gr.Markdown("#### Dataset A")
                            with gr.Row(elem_classes="biostat-declaration-row"):
                                with gr.Column():
                                    _field_help("Data type", "Declares the scientific data modality so preprocessing choices and policy checks can be interpreted correctly.")
                                    data_type_a = gr.Dropdown(DATA_TYPE_CHOICES, value="metabolomics", label="Data type", show_label=False)
                                with gr.Column():
                                    _field_help("Preprocessing state", "Describes the transformation already applied before this tool receives the matrix. The tool does not silently normalize your data.")
                                    preprocessing_a = gr.Dropdown(ALL_PREPROCESSING_CHOICES, value="quantitative", label="Preprocessing state", show_label=False)
                            with gr.Row(elem_classes="biostat-declaration-row"):
                                with gr.Column():
                                    _field_help("Orientation", "Choose whether samples are stored in rows or columns. The opposite dimension is interpreted as features.")
                                    orientation_a = gr.Dropdown(ORIENTATION_CHOICES, value="samples_rows", label="Orientation", show_label=False)
                                with gr.Column():
                                    _field_help("Missing-value tokens", MISSING_TOKEN_HELP)
                                    missing_a = gr.Textbox(value=DEFAULT_MISSING_TOKEN_TEXT, label="Missing-value tokens", show_label=False, lines=1, placeholder="NA,N/A,NaN,nan")
                            _field_help("Preprocessing details", "Optional documentation such as normalization software, filtering rule, or transformation details.")
                            details_a = gr.Textbox(label="Preprocessing details", show_label=False, lines=1, placeholder="Optional")
                        with gr.Column(elem_classes=["biostat-panel", "biostat-dataset-card"]):
                            gr.Markdown("#### Dataset B")
                            with gr.Row(elem_classes="biostat-declaration-row"):
                                with gr.Column():
                                    _field_help("Data type", "Declares the scientific data modality so preprocessing choices and policy checks can be interpreted correctly.")
                                    data_type_b = gr.Dropdown(DATA_TYPE_CHOICES, value="rna_seq", label="Data type", show_label=False)
                                with gr.Column():
                                    _field_help("Preprocessing state", "Describes the transformation already applied before this tool receives the matrix. The tool does not silently normalize your data.")
                                    preprocessing_b = gr.Dropdown(ALL_PREPROCESSING_CHOICES, value="vst", label="Preprocessing state", show_label=False)
                            with gr.Row(elem_classes="biostat-declaration-row"):
                                with gr.Column():
                                    _field_help("Orientation", "Choose whether samples are stored in rows or columns. The opposite dimension is interpreted as features.")
                                    orientation_b = gr.Dropdown(ORIENTATION_CHOICES, value="samples_rows", label="Orientation", show_label=False)
                                with gr.Column():
                                    _field_help("Missing-value tokens", MISSING_TOKEN_HELP)
                                    missing_b = gr.Textbox(value=DEFAULT_MISSING_TOKEN_TEXT, label="Missing-value tokens", show_label=False, lines=1, placeholder="NA,N/A,NaN,nan")
                            _field_help("Preprocessing details", "Optional documentation such as normalization software, filtering rule, or transformation details.")
                            details_b = gr.Textbox(label="Preprocessing details", show_label=False, lines=1, placeholder="Optional")

                gr.Markdown("#### Statistical declaration")
                with gr.Row(elem_classes="biostat-stat-grid"):
                    with gr.Column():
                        _field_help("Observation structure", "Independent means each sample contributes one independent observation. Dependent or clustered designs require specialized inference and may be blocked or flagged if unsupported.")
                        observation_structure = gr.Dropdown(DESIGN_CHOICES, value="unknown", label="Observation structure", show_label=False)
                        _choice_help([
                            ("Independent", "Use when each sample is unrelated to the others for the purpose of this analysis."),
                            ("Dependent or clustered", "Use for paired, repeated, family, site, or cluster structures. The tool will not silently analyze these as independent."),
                        ])
                    with gr.Column():
                        _field_help("Correlation method", "Spearman measures monotonic rank association and is robust to nonlinear monotonic scaling. Pearson measures linear association on the supplied quantitative values.")
                        method = gr.Dropdown(METHOD_CHOICES, value="spearman", label="Correlation method", show_label=False)
                        _choice_help([
                            ("Spearman", "Use for monotonic associations, ranks, skewed quantitative values, or when linearity is not a good assumption."),
                            ("Pearson", "Use when the scientific target is linear association on the supplied quantitative scale."),
                        ])
                    with gr.Column():
                        _field_help("Minimum pairwise N", "The smallest number of matched samples that must have non-missing values for both features before a correlation is calculated. Example: if set to 10, a feature pair with only 9 usable samples is excluded.")
                        min_n = gr.Number(value=10, precision=0, minimum=3, step=1, label="Minimum pairwise N", show_label=False, info="Minimum: 3 · Recommended starting value: 10")
                with gr.Row(elem_classes="biostat-stat-grid"):
                    with gr.Column():
                        _field_help("Spearman Monte Carlo pairings", "Number of Monte Carlo permutations used by the configured Spearman inference path when applicable. More pairings improve p-value resolution but require more computation.")
                        permutations = gr.Number(value=9999, precision=0, minimum=99, maximum=100000, step=1, label="Spearman Monte Carlo pairings", show_label=False, info="Allowed range: 99–100,000 · Default: 9,999")
                    with gr.Column():
                        _field_help("Random seed", "Makes Monte Carlo procedures reproducible. Reusing the same data, settings, software, and seed reproduces the same randomized sequence.")
                        seed = gr.Number(value=20260915, precision=0, label="Random seed", show_label=False)
                    with gr.Column():
                        _field_help("Study-design notes", "Optional documentation carried with the saved analysis setup to record assumptions or context that should accompany the analysis.")
                        design_notes = gr.Textbox(label="Study-design notes", show_label=False, lines=1)

                with gr.Group(elem_classes="biostat-inspect-cta"):
                    gr.Markdown("#### Ready for the pre-analysis check?\nInspect validates the current data/design declaration before any correlation is calculated. You will be taken directly to **Readiness** to review the findings.")
                    inspect_btn = gr.Button("Inspect & validate inputs →", variant="primary")

            with gr.Tab("Readiness", id="readiness"):
                gr.Markdown("### 2. Analysis readiness\nConfirm sample alignment, feature quality, declared preprocessing, statistical policy, and compute feasibility before inference.")
                gr.HTML(READINESS_LEGEND_HTML)
                gr.HTML(_help_label("Why inspect first?", "Inspection validates input structure, sample alignment, declared preprocessing, statistical-policy constraints, and resource limits before inference is allowed."))
                reinspect_btn = gr.Button("Re-run inspection", variant="secondary")
                status = gr.HTML(_readiness_banner("INFO", detail="Configure the analysis in Data & design, then run readiness checks."))
                with gr.Accordion("Supported analysis limits", open=False):
                    gr.Markdown(
                        "Analyses are blocked before inference when they exceed the validated software safeguards: **250,000 A×B correlations**, **10,000 matched samples**, **5,000,000 aligned cells per dataset**, or **100 MiB per source file**. These are engineering/validation limits, not biological sample-size recommendations."
                    )
                    limits = gr.Markdown("Run inspection to calculate this analysis workload.")
                with gr.Row():
                    metrics = gr.Dataframe(label="Dataset metrics", interactive=False, wrap=True)
                    alignment = gr.Dataframe(label="Alignment summary", interactive=False, wrap=True)
                issues = gr.Dataframe(
                    label="Readiness findings and statistical-policy advisories", interactive=False, wrap=True,
                    column_widths=[120, 110, 190, 260, 620], max_height=520, elem_classes="biostat-issues-table",
                )
                with gr.Accordion("Feature-level QC / data dictionary", open=False):
                    feature_qc = gr.Dataframe(label="Feature QC", interactive=False, wrap=True)
                with gr.Accordion("Sample alignment details", open=False):
                    alignment_detail = gr.Dataframe(label="Matched / unmatched sample IDs", interactive=False, wrap=True)

            with gr.Tab("Analysis", id="analysis"):
                gr.Markdown("### 3. Run analysis\nThe browser and CLI use the same validated runner. A blocked request cannot run; warnings must be acknowledged for the exact inspected fingerprint.")
                analysis_gate = gr.HTML(_analysis_gate_html(None))
                _field_help("Warning acknowledgement", "Acknowledgement is tied to the exact inspected request. If data or analysis-defining settings change, readiness must be checked again.")
                acknowledge = gr.Checkbox(label="I acknowledge all warnings for this exact inspected run", show_label=False, value=False)
                analyze_btn = gr.Button("3. Run inspected analysis", variant="primary", interactive=False)
                gr.Markdown("Results are reported as **unadjusted marginal associations** and do not establish causation or direct molecular regulation.")

            with gr.Tab("Results", id="results"):
                gr.Markdown("### 4. Review results\nThe browser table shows the key scientific columns for review. Download the full CSV for the complete technical record; use **Figures** for plots and batch reports.", elem_classes="biostat-section-head")
                preview = gr.Dataframe(label=f"Result preview — up to {RESULT_PREVIEW_ROWS:,} rows", interactive=False, wrap=True, show_search="filter", column_widths=[190,190,120,120,110,120,120,100], max_height=560, elem_classes="biostat-results-preview")
                with gr.Row(elem_classes="biostat-download-toolbar"):
                    results_download = gr.File(label="Full results CSV")
                    report_download = gr.File(label="HTML report")
                    bundle_download = gr.File(label="Verified RunBundle ZIP")
                    executed_spec_download = gr.File(label="Executed saved analysis setup (AnalysisSpec)")

            with gr.Tab("Figures", id="figures"):
                gr.Markdown("### 5. Figures — Scientific visualization workspace\nCreate publication-quality summaries and pair-level diagnostics from the completed analysis.", elem_classes="biostat-section-head")
                with gr.Row(elem_classes="biostat-figure-workstation"):
                    with gr.Column(scale=1, min_width=270, elem_classes="biostat-figure-controls"):
                        gr.Markdown("#### Figure controls")
                        gr.HTML("<div class='biostat-empty-state'><b>No figure yet?</b> Complete Steps 1–3, choose the relevant features or pair, then render a figure. Downloads appear with each figure.</div>")
                        with gr.Group(visible=True) as association_controls:
                            _field_help("Dataset A feature", "First choose a Dataset A feature. The Dataset B selector then shows only analyzed partners for that feature.")
                            pair_feature_a = gr.Dropdown(choices=[], label="Dataset A feature", show_label=False, filterable=True)
                            _field_help("Dataset B feature", "Choose one analyzed Dataset B partner for the selected Dataset A feature.")
                            pair_feature_b = gr.Dropdown(choices=[], label="Dataset B feature", show_label=False, filterable=True)
                            _field_help("Quick search — first 5,000 ranked pairs", "Searchable shortcut containing the first 5,000 validated A×B result pairs ordered primarily by BH q value. Use the Dataset A / Dataset B selectors above to access any eligible pair beyond this quick-search list.")
                            pair_selector = gr.Dropdown(
                                choices=[],
                                label="Quick search — first 5,000 ranked pairs",
                                show_label=False,
                                filterable=True,
                                allow_custom_value=True,
                            )
                            _field_help("View", "Raw values show the supplied quantitative scale. Average-rank view is available for Spearman results and displays the exact ranks used to represent the monotonic association.")
                            plot_view = gr.Radio([("Raw values", "raw"), ("Average ranks (Spearman)", "ranks")], value="raw", label="View", show_label=False)
                        with gr.Group(visible=False) as summary_feature_controls:
                            _field_help("Dataset A features", f"Choose the Dataset A feature subset used by the active summary figure. Up to {HEATMAP_MAX_PER_AXIS} may be selected for a heatmap; the correlogram is limited to {CORRELOGRAM_MAX_PER_AXIS} per axis for readability.")
                            visual_features_a = gr.Dropdown([], value=[], multiselect=True, max_choices=HEATMAP_MAX_PER_AXIS, label="Dataset A features", show_label=False, filterable=True)
                            _field_help("Dataset B features", f"Choose the Dataset B feature subset used by the active summary figure. Up to {HEATMAP_MAX_PER_AXIS} may be selected for a heatmap; the correlogram is limited to {CORRELOGRAM_MAX_PER_AXIS} per axis for readability.")
                            visual_features_b = gr.Dropdown([], value=[], multiselect=True, max_choices=HEATMAP_MAX_PER_AXIS, label="Dataset B features", show_label=False, filterable=True)
                        with gr.Group(visible=False) as visual_q_controls:
                            _field_help("Visual q threshold", "Controls figure emphasis only. Changing this display threshold does not recompute correlations or change the analyzed Benjamini-Hochberg family.")
                            q_threshold = gr.Number(value=0.05, label="Visual q threshold", show_label=False)
                        with gr.Group(visible=False) as heatmap_controls:
                            _field_help("Heatmap q emphasis", "When enabled, cells above the display q threshold are visually de-emphasized while their stored statistics remain unchanged.")
                            emphasize_q = gr.Checkbox(value=True, label="De-emphasize heatmap cells above q threshold", show_label=False)
                        with gr.Group(visible=False) as bubble_controls:
                            _field_help("Bubble size", "Controls the point-area encoding in the bubble plot. This changes only the graphic, not the statistical analysis.")
                            bubble_size = gr.Radio([("Effect magnitude", "effect"), ("Statistical evidence", "evidence")], value="effect", label="Bubble size", show_label=False)
                            _choice_help([
                                ("Effect magnitude", "Larger bubbles mean larger absolute correlation. Use this when association strength is the main visual emphasis."),
                                ("Statistical evidence", "Larger bubbles mean smaller BH q values through -log10(q). Use this when statistical evidence is the main visual emphasis."),
                            ])
                    with gr.Column(scale=3, min_width=520, elem_classes="biostat-figure-stage"):
                        with gr.Tabs() as figure_tabs:
                            with gr.Tab("Association") as association_tab:
                                gr.Markdown("Choose a pair using the context-sensitive Figure controls at left. The two-stage selectors can access every eligible analyzed pair, including pairs beyond the 5,000-pair quick-search cap.")
                                plot_btn = gr.Button("Render selected association", variant="primary")
                                pair_meta = gr.Markdown("Select a result pair after analysis. This is a **sample-level data view**.")
                                pair_plot = gr.Plot(label="Association plot")
                                gr.HTML("<div class='biostat-download-label'>Download this figure</div>")
                                with gr.Row():
                                    png_download = gr.File(label="PNG · 300 dpi")
                                    svg_download = gr.File(label="SVG · vector")
                                    pdf_download = gr.File(label="PDF · vector")

                                with gr.Group(elem_classes="batch-report-box"):
                                    gr.Markdown("#### Batch association report\nCreate one combined PDF for the top associations and an optional ZIP of the same individual PNG figures.")
                                    with gr.Row():
                                        top_n = gr.Dropdown([10, 25, 50], value=50, label="Number of associations")
                                        ranking_rule = gr.Dropdown([
                                            ("Lowest BH q-value", "q_value"),
                                            ("Largest absolute correlation", "abs_effect"),
                                            ("Strongest positive correlations", "positive"),
                                            ("Strongest negative correlations", "negative"),
                                            ("BH q ≤ 0.05 only", "significant"),
                                        ], value="q_value", label="Ranking rule")
                                    _choice_help([
                                        ("Lowest BH q-value", "Prioritizes statistical evidence; ties are broken by larger absolute correlation."),
                                        ("Largest absolute correlation", "Prioritizes effect magnitude, then smaller BH q values."),
                                    ])
                                    batch_report_btn = gr.Button("Generate report", variant="primary", elem_classes="batch-report-action")
                                    batch_report_meta = gr.Markdown()
                                    with gr.Row():
                                        batch_report_pdf = gr.File(label="Combined PDF")
                                        batch_report_zip = gr.File(label="ZIP of individual PNGs + CSV index")

                            with gr.Tab("Heatmap") as heatmap_tab:
                                gr.Markdown("Color shows the correlation coefficient. When q-emphasis is enabled, associations above the display q threshold are faded. Small matrices also print values.")
                                heatmap_btn = gr.Button("Render heatmap", variant="primary")
                                heatmap_meta = gr.Markdown("Choose a feature subset after analysis. This is a **summary result view**.")
                                heatmap_plot = gr.Plot(label="A×B correlation heatmap")
                                gr.HTML("<div class='biostat-download-label'>Download this figure</div>")
                                with gr.Row():
                                    heatmap_png = gr.File(label="PNG · 300 dpi")
                                    heatmap_svg = gr.File(label="SVG · vector")
                                    heatmap_pdf = gr.File(label="PDF · vector")

                            with gr.Tab("Correlogram") as correlogram_tab:
                                gr.Markdown(f"A cell-based correlogram: color encodes correlation and `*` marks BH q at or below the visual threshold. Values are printed for small matrices; larger selections use color only. Up to **{CORRELOGRAM_MAX_PER_AXIS} features per axis** are supported. A half-triangle is used only when the selected matrix is genuinely symmetric.")
                                correlogram_btn = gr.Button("Render correlogram", variant="primary")
                                correlogram_meta = gr.Markdown("Choose a feature subset after analysis. **Summary result view.**")
                                correlogram_plot = gr.Plot(label="Correlation correlogram")
                                gr.HTML("<div class='biostat-download-label'>Download this figure</div>")
                                with gr.Row():
                                    correlogram_png = gr.File(label="PNG · 300 dpi")
                                    correlogram_svg = gr.File(label="SVG · vector")
                                    correlogram_pdf = gr.File(label="PDF · vector")

                            with gr.Tab("Bubble") as bubble_tab:
                                gr.Markdown("A scatter-style association map. Each dot is one validated A×B association: X is the signed correlation coefficient, Y is -log10(BH q), and dot size follows the Bubble size choice above.")
                                bubble_btn = gr.Button("Render bubble plot", variant="primary")
                                bubble_meta = gr.Markdown(f"Limited to {BUBBLE_MAX_POINTS} selected eligible A×B associations. **Summary result view.**")
                                bubble_plot = gr.Plot(label="Association bubble plot")
                                gr.HTML("<div class='biostat-download-label'>Download this figure</div>")
                                with gr.Row():
                                    bubble_png = gr.File(label="PNG · 300 dpi")
                                    bubble_svg = gr.File(label="SVG · vector")
                                    bubble_pdf = gr.File(label="PDF · vector")

                            with gr.Tab("Scatter matrix") as scatter_tab:
                                gr.Markdown(f"Select **2–{SCATTER_MATRIX_MAX_VARIABLES} total variables** across Dataset A and B. A scatter matrix grows as an N×N panel grid; larger matrices become hard to read and expensive to render. For larger feature sets, use Heatmap or Correlogram.")
                                matrix_selection_status = gr.HTML(f"<div class='biostat-selection-counter'>Selected: <b>0 / {SCATTER_MATRIX_MAX_VARIABLES}</b>. Select at least 2 variables.</div>")
                                matrix_btn = gr.Button("Render scatter matrix", variant="primary", interactive=False)
                                matrix_meta = gr.Markdown("This is a **sample-level data view** and may expose substantially more of the underlying measurements than a summary figure.")
                                matrix_plot = gr.Plot(label="Selected-feature scatter matrix")
                                gr.HTML("<div class='biostat-download-label'>Download this figure</div>")
                                with gr.Row():
                                    matrix_png = gr.File(label="PNG · 300 dpi")
                                    matrix_svg = gr.File(label="SVG · vector")
                                    matrix_pdf = gr.File(label="PDF · vector")

                        gr.Markdown("Figure exports are generated on demand and are not automatically inserted into the canonical RunBundle.")

            # Preserve the established researcher-facing section label: gr.Tab("Provenance")
            with gr.Tab("Provenance", id="provenance"):
                gr.Markdown("### 6. Verify provenance")
                gr.HTML(_help_label("Saved analysis setup (AnalysisSpec)", "The machine-readable record of analysis-defining inputs, expected dataset SHA-256 identities, and settings. It lets a collaborator reproduce the same requested analysis instead of silently substituting different data."))
                spec_json = gr.Code(label="Saved analysis setup (AnalysisSpec JSON)", language="json")
                spec_download = gr.File(label="Download inspected AnalysisSpec")
                gr.HTML(_help_label("Verified RunBundle", "The completed analysis package containing results, provenance, manifest hashes, and verification metadata. `biostat verify` checks its structure and recorded content identities."))
                gr.Markdown(
                    "Biostat-generated artifacts live in this local process cache and are removed when inputs change or a new inspection begins. With the default cache configuration, the private cache is also removed at normal process exit."
                )

            with gr.Tab("Quick start", id="quickstart"):
                gr.Markdown("""### Quick start
A short orientation for first-time users. The six workflow steps at left remain available throughout the analysis.""")
                gr.HTML("""
                <div class='biostat-learn-card'><b>1. Choose how to start</b><br><span class='biostat-subtle'>Use a bundled synthetic example, restore a saved analysis setup, or choose two local matrices.</span></div>
                <div class='biostat-learn-card'><b>2. Inspect readiness</b><br><span class='biostat-subtle'>Confirm alignment, preprocessing declarations, missingness, statistical policy, and validated resource limits before inference.</span></div>
                <div class='biostat-learn-card'><b>3. Run the inspected request</b><br><span class='biostat-subtle'>Blocked requests cannot run. Warnings must be acknowledged for the exact inspected fingerprint.</span></div>
                <div class='biostat-learn-card'><b>4. Review results</b><br><span class='biostat-subtle'>The browser shows the key scientific columns; the downloadable CSV retains the complete technical result record.</span></div>
                <div class='biostat-learn-card'><b>5. Create figures</b><br><span class='biostat-subtle'>Render association plots, heatmaps, correlograms, bubble plots, scatter matrices, or a combined top-association report.</span></div>
                <div class='biostat-learn-card'><b>6. Verify provenance</b><br><span class='biostat-subtle'>Save the AnalysisSpec and completed RunBundle so the analysis request and generated outputs can be verified later.</span></div>
                """)

            with gr.Tab("Video tutorials", id="videos"):
                gr.Markdown("""### Video tutorials
Tutorial slots are built into the application. Project-specific YouTube links will be added when the videos are published; no external video URLs are invented in this release.""")
                gr.HTML("""
                <div class='biostat-learn-card'>
                  <div class='biostat-video-card'><div><b>5-minute quick start</b><div class='biostat-video-meta'>Load example → Inspect → Analyze → Review → Figure</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                  <div class='biostat-video-card'><div><b>Using your own matrices</b><div class='biostat-video-meta'>Orientation, identifiers, preprocessing declarations, and missing values</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                  <div class='biostat-video-card'><div><b>Understanding readiness</b><div class='biostat-video-meta'>PASS, INFO, WARNING, and BLOCKED</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                  <div class='biostat-video-card'><div><b>Interpreting correlation results</b><div class='biostat-video-meta'>Correlation, p-value, BH q-value, and pairwise N</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                  <div class='biostat-video-card'><div><b>Publication figures</b><div class='biostat-video-meta'>Association, heatmap, correlogram, bubble plot, and batch PDF</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                  <div class='biostat-video-card'><div><b>Reproducing an analysis</b><div class='biostat-video-meta'>Saved analysis setup (AnalysisSpec) and verified RunBundle</div></div><span class='biostat-coming-soon'>Link pending</span></div>
                </div>
                """)

            with gr.Tab("Documentation", id="docs"):
                gr.Markdown("""### Documentation

**Bundled project documents**

- **README** — installation, browser/CLI workflow, examples, and release guidance.
- **VALIDATION** — validated scope, statistical policies, known boundaries, and test evidence.
- **CHANGELOG** — release-candidate history and product changes.
- **CITATION.cff** — research-software citation metadata.
- **LICENSE** — MIT License.

**Key terminology**

- **Saved analysis setup (AnalysisSpec):** JSON record of analysis-defining settings and expected dataset identities.
- **Verified RunBundle:** completed package containing results, provenance, manifest hashes, and verification metadata.
- **Pairwise N:** matched samples with non-missing values for both features in a particular correlation.

The source/review package contains the complete documents. A public documentation URL can be added here once the project repository/site is finalized.
""")
                gr.HTML(NIH_REPRODUCIBILITY_HTML)

            with gr.Tab("About", id="about"):
                gr.Markdown(f"""### About Biostat Research Tool

**Version:** `{__version__}`  
**License:** MIT

Biostat Research Tool is local-first research software for reproducible, verifiable matrix-to-matrix correlation analysis in biomedical and quantitative research. It supports same-domain and cross-omics workflows.

**Current statistical scope**

- Pearson and Spearman correlation
- pairwise-complete observations with explicit minimum pairwise N
- Benjamini-Hochberg multiple-testing correction
- readiness/QC and scientific preprocessing guardrails
- summary and sample-level visualization workflows
- saved analysis setup (AnalysisSpec) and verified RunBundle provenance
- automatic computation-engine selection; exact technical engine identifiers remain recorded in provenance

**Interpretation boundary**

Current correlation results are unadjusted marginal associations. They do not establish causation or direct molecular regulation, and this release does not perform covariate-adjusted correlation.

**Privacy**

The application binds locally by default and public Gradio sharing is disabled. Source matrices remain in the local server process. Sample-level plots may contain individual coordinate information and should be handled according to data sensitivity.

**Validation language**

The project maintains statistical oracles, regression tests, packaging checks, and independent release-candidate reviews. This should be described as **verifiable/reproducible research software**, not as FDA/GxP validated software.

**Citation**

If used in research, cite the specific software release used for the analysis. `CITATION.cff` is included in the source package.
""")

        example_outputs = [
            file_a, data_type_a, preprocessing_a, details_a, orientation_a,
            file_b, data_type_b, preprocessing_b, details_b, orientation_b,
            observation_structure, design_notes, method, example_note,
        ]
        # Successful request replacement invalidates the previous generation inside
        # the primary callback. Publish one atomic cleanup update after success so
        # the browser cannot retain old prepared/completed state or artifacts.
        replacement_run_outputs = [
            prepared_state, acknowledge, preview, bundle_download, executed_spec_download,
            spec_download, status, completed_state, results_download, report_download,
            png_download, svg_download, pdf_download,
        ]
        replacement_readiness_outputs = [issues, metrics, alignment, spec_json, limits, feature_qc, alignment_detail]
        replacement_visual_outputs = [
            pair_selector, visual_features_a, visual_features_b,
            pair_plot, pair_meta, png_download, svg_download, pdf_download,
            heatmap_plot, heatmap_meta, heatmap_png, heatmap_svg, heatmap_pdf,
            correlogram_plot, correlogram_meta, correlogram_png, correlogram_svg, correlogram_pdf,
            bubble_plot, bubble_meta, bubble_png, bubble_svg, bubble_pdf,
            matrix_plot, matrix_meta, matrix_png, matrix_svg, matrix_pdf,
            batch_report_meta, batch_report_pdf, batch_report_zip,
        ]
        replacement_cleanup_outputs = [
            *replacement_run_outputs, *replacement_readiness_outputs, *replacement_visual_outputs,
            pair_feature_a, pair_feature_b, inspect_btn, analyze_btn, analysis_gate, workflow_guide,
        ]

        # Sidebar navigation drives the hidden main Tabs container. Keeping the
        # workflow rail separate from the analytical controls reduces duplicate
        # navigation chrome while preserving all six workflow sections.
        for button, tab_id in [
            (nav_data, "data"), (nav_readiness, "readiness"), (nav_analysis, "analysis"),
            (nav_results, "results"), (nav_figures, "figures"), (nav_provenance, "provenance"),
            (nav_quickstart, "quickstart"), (nav_videos, "videos"), (nav_docs, "docs"), (nav_about, "about"),
        ]:
            button.click(lambda target=tab_id: gr.Tabs(selected=target), inputs=[], outputs=[main_tabs], queue=False, show_progress="hidden")

        load_event = load_example.click(load_example_callback, inputs=[example_key], outputs=example_outputs)
        load_event.success(
            replacement_cleanup_for_example_ui, inputs=[],
            outputs=[*replacement_cleanup_outputs, spec_load_note], show_progress="hidden",
        )
        data_type_a.input(preprocessing_update, inputs=[data_type_a], outputs=[preprocessing_a])
        data_type_b.input(preprocessing_update, inputs=[data_type_b], outputs=[preprocessing_b])

        spec_outputs = [
            data_type_a, preprocessing_a, details_a, orientation_a, missing_a,
            data_type_b, preprocessing_b, details_b, orientation_b, missing_b,
            observation_structure, design_notes, method, min_n, permutations, seed, spec_load_note,
        ]
        spec_event = load_spec_btn.click(load_spec_ui, inputs=[spec_upload], outputs=spec_outputs)
        spec_event.success(
            replacement_cleanup_for_spec_ui, inputs=[spec_upload],
            outputs=replacement_cleanup_outputs, show_progress="hidden",
        )
        new_request_btn.click(clear_restored_identity_ui, inputs=[], outputs=[spec_load_note])

        inspect_inputs = [
            file_a, file_b,
            data_type_a, preprocessing_a, details_a, orientation_a,
            data_type_b, preprocessing_b, details_b, orientation_b,
            observation_structure, design_notes, method, min_n, permutations, seed, missing_a, missing_b,
        ]
        inspect_outputs = [
            status, issues, metrics, alignment, spec_json, prepared_state, acknowledge, preview,
            bundle_download, spec_download, executed_spec_download, limits, feature_qc, alignment_detail,
        ]
        inspect_event = inspect_btn.click(inspect_ui, inputs=inspect_inputs, outputs=inspect_outputs, trigger_mode="once")
        reinspect_event = reinspect_btn.click(inspect_ui, inputs=inspect_inputs, outputs=inspect_outputs, trigger_mode="once")
        for readiness_event in (inspect_event, reinspect_event):
            readiness_event.then(inspection_controls_ui, inputs=[prepared_state], outputs=[inspect_btn, analyze_btn, analysis_gate, workflow_guide])
            readiness_event.then(lambda: gr.Tabs(selected="readiness"), inputs=[], outputs=[main_tabs], queue=False, show_progress="hidden")
        acknowledge.change(acknowledgement_gate_ui, inputs=[prepared_state, acknowledge], outputs=[analyze_btn, analysis_gate], trigger_mode="always_last")

        analyze_outputs = [status, preview, bundle_download, executed_spec_download, results_download, report_download, pair_selector, completed_state, visual_features_a, visual_features_b]
        analyze_event = analyze_btn.click(analyze_ui, inputs=[prepared_state, acknowledge], outputs=analyze_outputs)
        analyze_event.then(analysis_completion_ui, inputs=[completed_state], outputs=[analysis_gate, workflow_guide])
        analyze_event.then(pair_feature_controls_ui, inputs=[completed_state], outputs=[pair_feature_a, pair_feature_b])

        figure_control_outputs = [association_controls, summary_feature_controls, visual_q_controls, heatmap_controls, bubble_controls]
        for tab, view in [
            (association_tab, "association"),
            (heatmap_tab, "heatmap"),
            (correlogram_tab, "correlogram"),
            (bubble_tab, "bubble"),
            (scatter_tab, "scatter"),
        ]:
            tab.select(
                lambda selected=view: figure_controls_visibility_ui(selected),
                inputs=[], outputs=figure_control_outputs, queue=False, show_progress="hidden",
            )

        pair_feature_a.change(pair_feature_b_ui, inputs=[completed_state, pair_feature_a], outputs=[pair_feature_b], trigger_mode="always_last")
        pair_feature_a.change(pair_selector_from_features, inputs=[pair_feature_a, pair_feature_b], outputs=[pair_selector], trigger_mode="always_last")
        pair_feature_b.change(pair_selector_from_features, inputs=[pair_feature_a, pair_feature_b], outputs=[pair_selector], trigger_mode="always_last")

        pair_event = plot_btn.click(plot_pair_ui, inputs=[completed_state, pair_selector, plot_view], outputs=[pair_plot, pair_meta, png_download, svg_download, pdf_download])
        heatmap_event = heatmap_btn.click(heatmap_ui, inputs=[completed_state, visual_features_a, visual_features_b, q_threshold, emphasize_q], outputs=[heatmap_plot, heatmap_meta, heatmap_png, heatmap_svg, heatmap_pdf])
        corr_event = correlogram_btn.click(correlogram_ui, inputs=[completed_state, visual_features_a, visual_features_b, q_threshold], outputs=[correlogram_plot, correlogram_meta, correlogram_png, correlogram_svg, correlogram_pdf])
        bubble_event = bubble_btn.click(bubble_ui, inputs=[completed_state, visual_features_a, visual_features_b, q_threshold, bubble_size], outputs=[bubble_plot, bubble_meta, bubble_png, bubble_svg, bubble_pdf])
        matrix_event = matrix_btn.click(scatter_matrix_ui, inputs=[completed_state, visual_features_a, visual_features_b], outputs=[matrix_plot, matrix_meta, matrix_png, matrix_svg, matrix_pdf])
        batch_event = batch_report_btn.click(association_report_ui, inputs=[completed_state, top_n, ranking_rule], outputs=[batch_report_meta, batch_report_pdf, batch_report_zip])

        visual_features_a.change(scatter_matrix_selection_ui, inputs=[visual_features_a, visual_features_b], outputs=[matrix_selection_status, matrix_btn], trigger_mode="always_last")
        visual_features_b.change(scatter_matrix_selection_ui, inputs=[visual_features_a, visual_features_b], outputs=[matrix_selection_status, matrix_btn], trigger_mode="always_last")

        clear_outputs = replacement_visual_outputs
        # A fresh inspection invalidates every completed-analysis visualization
        # artifact, even when the analysis-defining inputs have not changed.
        # Clear the browser outputs as part of the inspection lifecycle so stale
        # download paths never survive after their files are removed.
        for readiness_event in (inspect_event, reinspect_event):
            readiness_event.then(clear_visual_ui, inputs=[], outputs=clear_outputs, trigger_mode="always_last")
            readiness_event.then(clear_pair_feature_ui, inputs=[], outputs=[pair_feature_a, pair_feature_b], trigger_mode="always_last")
        cancellable = [inspect_event, reinspect_event, analyze_event, pair_event, heatmap_event, corr_event, bubble_event, matrix_event, batch_event]

        # Direct user edits use one coalesced invalidation callback. Programmatic
        # example/spec population does not fire ``input`` handlers, preserving the
        # atomic replacement behavior added in RC12. File controls use only their
        # user-originated upload/delete/clear events. The callback is unqueued and
        # hidden because it is a lightweight state reset, not an analysis job.
        user_edit_outputs = [
            *replacement_run_outputs[:10], *replacement_visual_outputs,
            pair_feature_a, pair_feature_b, inspect_btn, analyze_btn, analysis_gate, workflow_guide,
        ]

        def register_user_edit(component):
            kwargs = {
                "inputs": [], "outputs": user_edit_outputs, "trigger_mode": "always_last",
                "cancels": cancellable, "queue": False, "show_progress": "hidden",
            }
            if isinstance(component, gr.File):
                component.upload(invalidate_all_user_edit_ui, **kwargs)
                component.delete(invalidate_all_user_edit_ui, **kwargs)
                component.clear(invalidate_all_user_edit_ui, **kwargs)
            else:
                component.input(invalidate_all_user_edit_ui, **kwargs)

        for component in inspect_inputs:
            register_user_edit(component)
    return demo


demo = build_demo()


def launch(*, server_name: str = "127.0.0.1", server_port: int = 7860, inbrowser: bool = True):
    return demo.launch(server_name=server_name, server_port=server_port, inbrowser=inbrowser, share=False, theme=APP_THEME, css=APP_CSS, js=APP_JS)
