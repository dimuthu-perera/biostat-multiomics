from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from biostat_tool.cli import main
from biostat_tool.modules.base import AnalysisModule, CompletedAnalysis, PreparedAnalysis
from biostat_tool.modules.registry import get_analysis_module, registered_analysis_types
from biostat_tool.runner import execute_prepared, prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec
from correlation_tool import sha256_file

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def _spec(method: str = "spearman") -> AnalysisSpec:
    return AnalysisSpec(
        schema_version="1.0",
        method=method,
        dataset_a=DatasetSpec("a.csv", sha256_file(FIX / "a.csv"), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(FIX / "b.csv"), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )


def test_correlation_is_registered_through_formal_analysis_module_contract():
    assert registered_analysis_types() == ("cross_omics_correlation",)
    module = get_analysis_module("cross_omics_correlation")
    assert isinstance(module, AnalysisModule)
    assert module.module_id == "correlation"
    assert module.module_version == "1.3"


def test_shared_runner_returns_standardized_prepared_and_completed_records():
    prepared = prepare_analysis(_spec(), base_dir=FIX)
    assert isinstance(prepared, PreparedAnalysis)
    assert prepared.analysis_type == "cross_omics_correlation"
    assert prepared.module_id == "correlation"
    assert prepared.run_fingerprint == prepared.inspected.fingerprint
    assert prepared.inspection_document["run_fingerprint"] == prepared.run_fingerprint

    completed = execute_prepared(prepared, acknowledge_warnings=True)
    assert isinstance(completed, CompletedAnalysis)
    assert completed.analysis_type == prepared.analysis_type
    assert completed.module_id == prepared.module_id
    assert completed.run_fingerprint == prepared.run_fingerprint
    pd.testing.assert_frame_equal(completed.primary_results, completed.oracle_run.results)
    assert completed.summary.primary_table_path == "results/correlations.csv"
    assert completed.result_schema["row_count"] == len(completed.primary_results)



def test_completed_metadata_is_rebuilt_from_fresh_oracle_after_prepared_document_mutation():
    prepared = prepare_analysis(_spec(), base_dir=FIX)
    # Reproduce the v0.3.3 audit finding: caller-visible prepared documents
    # are mutable, but they must never become completed scientific provenance.
    prepared.inspection_document["run_fingerprint"] = "0" * 64
    prepared.alignment_document["n_common"] = 999

    completed = execute_prepared(prepared, acknowledge_warnings=True)
    fresh = completed.oracle_run.inspected
    assert completed.inspection_document["run_fingerprint"] == fresh.fingerprint
    assert completed.inspection_document["run_fingerprint"] != "0" * 64
    assert completed.alignment_document["n_common"] == fresh.alignment["n_common"] == 6



def test_completed_alignment_document_has_no_nested_alias_to_oracle_manifest():
    completed = execute_prepared(prepare_analysis(_spec(), base_dir=FIX), acknowledge_warnings=True)
    assert completed.alignment_document["common_order"][0] == "S1"
    oracle_alignment = completed.module_provenance["oracle"]["manifest"]["alignment"]
    assert oracle_alignment["common_order"][0] == "S1"

    # Reproduce the v0.3.4 focused-review finding.  Mutating a nested list in
    # caller-visible completed metadata must not mutate the executed-run
    # semantic authority retained for RunBundle verification.
    completed.alignment_document["common_order"][0] = "NOT_ANALYZED"
    assert oracle_alignment["common_order"][0] == "S1"


def test_execution_rejects_prepared_state_with_wrong_module_identity():
    prepared = prepare_analysis(_spec(), base_dir=FIX)
    tampered = replace(prepared, module_version="not-the-active-version")
    with pytest.raises(RuntimeError, match="module identity"):
        execute_prepared(tampered, acknowledge_warnings=True)


def test_cli_lists_registered_modules(capsys):
    assert main(["modules"]) == 0
    out = capsys.readouterr().out
    assert "cross_omics_correlation" in out
    assert "correlation" in out
