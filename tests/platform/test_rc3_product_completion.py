from __future__ import annotations

from pathlib import Path
import tempfile

import gradio as gr
import numpy as np
import pandas as pd

import biostat_tool.web as web
from biostat_tool.examples import get_example, load_example_catalog
from biostat_tool.resource_limits import assess_resources, RESULT_PREVIEW_ROWS
from biostat_tool.visualization import pairwise_complete_data
from correlation_tool.analysis import CorrelationConfig

TOKENS = ',NA,N/A,NaN,nan'


def _args(key: str):
    ex = web.load_example_callback(key)
    return (ex[0], ex[5], ex[1], ex[2].value, ex[3], ex[4], ex[6], ex[7].value, ex[8], ex[9],
            ex[10], ex[11], ex[12], 10, 9999, 20260915, TOKENS, TOKENS)


def test_teaching_example_is_packaged_and_declares_pedagogic_cases():
    ex = get_example('pearson_spearman_teaching')
    assert Path(ex['a']['path']).is_file() and Path(ex['b']['path']).is_file()
    truth = __import__('json').loads((Path(ex['a']['path']).parent / 'truth.json').read_text())
    t = truth['pearson_spearman_teaching']
    assert {'linear_pair','monotonic_nonlinear_pair','outlier_sensitive_pair','null_pair','missing_pair','constant_features'} <= set(t)


def test_explicit_missing_tokens_are_preserved_in_analysis_spec():
    args = list(_args('metabolomics_proteomics'))
    args[-2] = ',NA,NULL,.'
    args[-1] = ',NA,Missing'
    spec, _ = web._build_spec_and_overrides(*args)
    assert spec.dataset_a.missing_tokens == ('', 'NA', 'NULL', '.')
    assert spec.dataset_b.missing_tokens == ('', 'NA', 'Missing')


def test_resource_assessment_blocks_over_pair_limit_without_running_inference(tmp_path):
    a = tmp_path / 'a.csv'; b = tmp_path / 'b.csv'; a.write_text('x\n1\n'); b.write_text('x\n1\n')
    r = assess_resources(samples=100, features_a=501, features_b=500, file_a=a, file_b=b, config=CorrelationConfig())
    assert r.status == 'BLOCKED'
    assert r.planned_pairs == 250500
    assert any('250,000' in m for m in r.messages)


def test_resource_assessment_warns_near_pair_limit(tmp_path):
    a = tmp_path / 'a.csv'; b = tmp_path / 'b.csv'; a.write_text('x\n1\n'); b.write_text('x\n1\n')
    r = assess_resources(samples=100, features_a=450, features_b=500, file_a=a, file_b=b, config=CorrelationConfig())
    assert r.status == 'WARNING'
    assert r.planned_pairs == 225000


def test_feature_qc_reports_missingness_and_constant_features():
    df = pd.DataFrame({'a':[1.0,1.0,np.nan], 'b':[1.0,2.0,3.0]})
    qc = web._feature_qc(df, 'Dataset A').set_index('feature')
    assert bool(qc.loc['a','constant']) is True
    assert qc.loc['a','observed_n'] == 2
    assert abs(qc.loc['a','missing_pct'] - 100/3) < 1e-9
    assert bool(qc.loc['b','constant']) is False


def test_pairwise_plot_data_uses_exact_statistical_pairwise_n():
    request = gr.Request(session_hash='rc3-pair-plot')
    inspected = web.inspect_callback(*_args('pearson_spearman_teaching'), request=request)
    state = inspected[5]
    result = web.analyze_callback(state, True, request=request)
    cstate = result[7]
    rows = cstate.completed.primary_results
    row = rows.loc[(rows.feature_a=='missing_driver') & (rows.feature_b=='missing_partner')].iloc[0]
    data = pairwise_complete_data(cstate.prepared.inspected.aligned_a, cstate.prepared.inspected.aligned_b,
                                  'missing_driver','missing_partner')
    assert data.n_pairwise == int(row.n_pairwise)
    selector = __import__('json').dumps(['missing_driver','missing_partner'])
    fig, meta, png, svg, pdf = web.plot_pair_callback(cstate, selector, 'raw', request=request)
    assert fig is not None and f"N `{int(row.n_pairwise)}`" in meta
    assert Path(png).is_file() and Path(svg).is_file() and Path(pdf).is_file()
    web.invalidate_run_state(request=request)


def test_analysis_exposes_direct_csv_and_report_downloads_and_caps_preview():
    request = gr.Request(session_hash='rc3-downloads')
    state = web.inspect_callback(*_args('metabolomics_proteomics'), request=request)[5]
    out = web.analyze_callback(state, True, request=request)
    assert Path(out[4]).name == 'correlations.csv' and Path(out[4]).is_file()
    assert Path(out[5]).name == 'report.html' and Path(out[5]).is_file()
    assert len(out[1]) <= RESULT_PREVIEW_ROWS
    web.invalidate_run_state(request=request)


def test_analysis_spec_loader_restores_settings_not_dataset_paths(tmp_path):
    spec, _ = web._build_spec_and_overrides(*_args('metabolomics_proteomics'))
    p = tmp_path / 'analysis.json'; p.write_text(spec.canonical_json())
    out = web.load_spec_callback(str(p))
    assert out[0] == 'metabolomics'
    assert out[1].value == 'quantitative'
    assert out[5] == 'proteomics'
    assert out[6].value == 'quantitative'
    assert 'Select the two source datasets' in out[-1]
