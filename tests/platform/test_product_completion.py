from __future__ import annotations
from pathlib import Path
import asyncio
import os
import subprocess
import sys

import gradio as gr
import pytest
from gradio.state_holder import SessionState
from gradio.processing_utils import hash_file as gradio_hash_file
import biostat_tool.web as web
from biostat_tool.cli import build_parser
from biostat_tool.examples import get_example, load_example_catalog
from biostat_tool.runner import prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec
from correlation_tool import sha256_file

def _spec_from_example(key: str):
    ex=get_example(key); a,b=ex['a'],ex['b']
    spec=AnalysisSpec(schema_version='1.0',method=ex.get('method','spearman'),dataset_a=DatasetSpec(Path(a['path']).name,sha256_file(a['path']),'samples_rows',a['data_type'],a['preprocessing'],a.get('details','')),dataset_b=DatasetSpec(Path(b['path']).name,sha256_file(b['path']),'samples_rows',b['data_type'],b['preprocessing'],b.get('details','')),study_design=StudyDesignSpec(ex.get('design','independent')),correlation=CorrelationSpec(minimum_pairwise_n=10))
    return spec, {'dataset_a':a['path'],'dataset_b':b['path']}

def test_synthetic_catalog_covers_all_supported_omics_profiles_and_files_exist():
    catalog=load_example_catalog(); observed=set()
    for key in catalog['examples']:
        ex=get_example(key); assert Path(ex['a']['path']).is_file(); assert Path(ex['b']['path']).is_file(); observed|={ex['a']['data_type'],ex['b']['data_type']}
    assert {'metabolomics','rna_seq','metagenomics','16s','proteomics','generic'} <= observed
    assert 'completely synthetic' in catalog['notice'].lower()

@pytest.mark.parametrize('key',['metabolomics_rnaseq','metabolomics_proteomics','metabolomics_metagenomics','16s_generic'])
def test_valid_synthetic_examples_pass_mandatory_inspection(key):
    spec,overrides=_spec_from_example(key); prepared=prepare_analysis(spec,path_overrides=overrides)
    assert prepared.blocked is False; assert prepared.inspected.alignment['n_common']==80

@pytest.mark.parametrize('key',['rnaseq_raw_blocked','microbiome_relative_blocked'])
def test_guardrail_synthetic_examples_are_blocked(key):
    spec,overrides=_spec_from_example(key); assert prepare_analysis(spec,path_overrides=overrides).blocked is True

def test_cli_normal_user_default_backend_is_auto_but_python_api_contract_is_unchanged():
    assert build_parser().parse_args(['run','analysis.json']).backend=='auto'

def test_load_example_callback_uses_packaged_synthetic_files_and_component_updates():
    result=web.load_example_callback('metabolomics_rnaseq')
    assert Path(result[0]).is_file()
    assert result[1] == 'metabolomics'
    assert isinstance(result[2], gr.Dropdown)
    assert result[2].value == 'quantitative'
    assert [x[1] for x in result[2].choices] == web.preprocessing_choices('metabolomics')
    assert result[3] == 'Synthetic processed quantitative metabolomics values.'
    assert Path(result[5]).is_file()
    assert result[6] == 'rna_seq'
    assert isinstance(result[7], gr.Dropdown)
    assert result[7].value == 'vst'
    assert [x[1] for x in result[7].choices] == web.preprocessing_choices('rna_seq')
    assert 'completely synthetic' in result[-1].lower()


def _registered_fn_index(name: str, *, first: bool = True) -> int:
    matches = [idx for idx, fn in web.demo.fns.items() if getattr(fn.fn, '__name__', None) == name]
    assert matches, name
    return min(matches) if first else max(matches)


@pytest.mark.parametrize(
    'key, expected_a, expected_b',
    [
        ('metabolomics_rnaseq', 'quantitative', 'vst'),
        ('metabolomics_proteomics', 'quantitative', 'quantitative'),
        ('metabolomics_metagenomics', 'quantitative', 'clr'),
        ('16s_generic', 'clr', 'declared_numeric'),
        ('rnaseq_raw_blocked', 'raw_counts', 'quantitative'),
        ('microbiome_relative_blocked', 'relative_abundance', 'quantitative'),
    ],
)
def test_registered_load_example_updates_choices_and_can_reach_inspection(key, expected_a, expected_b):
    async def run():
        state = SessionState(web.demo)
        request = gr.Request(session_hash=f'load-example-{key}')
        load = await web.demo.process_api(
            _registered_fn_index('load_example_callback'),
            [key],
            state=state,
            request=request,
            session_hash=request.session_hash,
        )
        data = load['data']
        assert data[2]['value'] == expected_a
        assert data[7]['value'] == expected_b
        assert [x[1] for x in data[2]['choices']] == web.preprocessing_choices(data[1])
        assert [x[1] for x in data[7]['choices']] == web.preprocessing_choices(data[6])
        args = [
            data[0], data[5], data[1], data[2]['value'], data[3], data[4],
            data[6], data[7]['value'], data[8], data[9], data[10], data[11],
            data[12], 10, 9999, 20260915, ',NA,N/A,NaN,nan', ',NA,N/A,NaN,nan',
        ]
        inspected = await web.demo.process_api(
            _registered_fn_index('inspect_ui'),
            args,
            state=state,
            request=request,
            session_hash=request.session_hash,
        )
        assert 'Inspection failed' not in inspected['data'][0]
        if key.endswith('_blocked'):
            assert 'BLOCKED' in inspected['data'][0]
        web.invalidate_run_state(request=request)

    asyncio.run(run())


def test_gradio_postprocessed_downloads_are_session_tracked_and_removed_on_invalidation():
    async def run():
        state = SessionState(web.demo)
        request = gr.Request(session_hash='download-cache-cleanup')
        load = await web.demo.process_api(
            _registered_fn_index('load_example_callback'),
            ['metabolomics_proteomics'],
            state=state, request=request, session_hash=request.session_hash,
        )
        data = load['data']
        inspect_args = [
            data[0], data[5], data[1], data[2]['value'], data[3], data[4],
            data[6], data[7]['value'], data[8], data[9], data[10], data[11],
            data[12], 10, 9999, 20260915, ',NA,N/A,NaN,nan', ',NA,N/A,NaN,nan',
        ]
        inspected = await web.demo.process_api(
            _registered_fn_index('inspect_ui'), inspect_args, state=state,
            request=request, session_hash=request.session_hash,
        )
        analyzed = await web.demo.process_api(
            _registered_fn_index('analyze_ui'), [None, True], state=state,
            request=request, session_hash=request.session_hash,
        )
        generated = [
            Path(inspected['data'][9]['path']),
            Path(analyzed['data'][2]['path']),
            Path(analyzed['data'][3]['path']),
        ]
        cache_root = Path(os.environ['GRADIO_TEMP_DIR']).resolve()
        for path in generated:
            assert path.exists()
            assert path.resolve().is_relative_to(cache_root)
            # A path already inside GRADIO_CACHE is served in place. There must
            # not be an additional hash-cache copy like /tmp/gradio/<hash>/file.
            duplicate = cache_root / gradio_hash_file(path) / path.name
            assert duplicate.resolve() != path.resolve()
            assert not duplicate.exists()
        await web.demo.process_api(
            _registered_fn_index('invalidate_all_user_edit_ui'), [], state=state,
            request=request, session_hash=request.session_hash,
        )
        assert all(not path.exists() for path in generated)

    asyncio.run(run())


def test_default_process_owned_gradio_cache_is_removed_on_normal_process_exit(tmp_path):
    env = os.environ.copy()
    env.pop('GRADIO_TEMP_DIR', None)
    code = (
        'from pathlib import Path; import biostat_tool.web as w; '
        'r=w._new_browser_artifact_root("biostat_exit_test_"); '
        '(r/"x.txt").write_text("x"); print(w._OWNED_GRADIO_CACHE)'
    )
    completed = subprocess.run(
        [sys.executable, '-c', code],
        cwd=Path(__file__).resolve().parents[2],
        env=env, text=True, capture_output=True, check=True,
    )
    cache = Path(completed.stdout.strip().splitlines()[-1])
    assert not cache.exists()

def test_web_analysis_requests_auto_backend(monkeypatch):
    web._SESSION_GENERATIONS.clear(); request=gr.Request(session_hash='auto-backend-session'); ex=web.load_example_callback('metabolomics_proteomics')
    args=(ex[0],ex[5],ex[1],ex[2].value,ex[3],ex[4],ex[6],ex[7].value,ex[8],ex[9],ex[10],ex[11],ex[12],10,9999,20260915,',NA,N/A,NaN,nan',',NA,N/A,NaN,nan')
    state=web.inspect_callback(*args,request=request)[5]; real=web.execute_prepared; seen={}
    def wrapped(*a,**kw): seen.update(kw); return real(*a,**kw)
    monkeypatch.setattr(web,'execute_prepared',wrapped); result=web.analyze_callback(state,True,request=request)
    assert 'Analysis complete' in result[0]; assert seen['backend']=='auto'; web.invalidate_run_state(request=request)

def test_web_invalidation_removes_registered_temporary_artifacts(tmp_path):
    web._SESSION_GENERATIONS.clear(); request=gr.Request(session_hash='cleanup-session'); root=tmp_path/'artifact'; root.mkdir(); (root/'x.txt').write_text('x')
    web._register_session_artifact(request,root); assert root.exists(); web.invalidate_run_state(request=request); assert not root.exists()
