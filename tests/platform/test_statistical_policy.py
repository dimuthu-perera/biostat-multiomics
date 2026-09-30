from __future__ import annotations

import json
from pathlib import Path

from biostat_tool.bundle import write_run_bundle
from biostat_tool.policy import (
    RECOMMENDED_CORRELATION_MIN_PAIRWISE_N,
    STATISTICAL_POLICY_VERSION,
    correlation_policy_advisories,
)
from biostat_tool.runner import execute_prepared, prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec
from correlation_tool import sha256_file

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def _spec(min_n: int) -> AnalysisSpec:
    return AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(FIX / "a.csv"), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(FIX / "b.csv"), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=min_n),
    )


def test_policy_keeps_hard_minimum_reproducible_but_flags_below_recommended_default():
    low = correlation_policy_advisories(_spec(3))
    assert RECOMMENDED_CORRELATION_MIN_PAIRWISE_N == 10
    assert any(x.code == "minimum_pairwise_n_below_platform_recommended_default" for x in low)
    normal = correlation_policy_advisories(_spec(10))
    assert not any(x.code == "minimum_pairwise_n_below_platform_recommended_default" for x in normal)
    assert any(x.code == "unadjusted_marginal_association" for x in normal)


def test_policy_is_recorded_in_provenance_and_report_without_changing_oracle(tmp_path):
    prepared = prepare_analysis(_spec(3), base_dir=FIX)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    run_dir = write_run_bundle(completed, tmp_path / "run")
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["statistical_policy"]["version"] == STATISTICAL_POLICY_VERSION
    codes = {x["code"] for x in provenance["statistical_policy"]["advisories"]}
    assert "unadjusted_marginal_association" in codes
    assert "minimum_pairwise_n_below_platform_recommended_default" in codes
    report = (run_dir / "report" / "report.html").read_text(encoding="utf-8")
    assert "Statistical policy" in report
    assert "Pairwise sample-size summary" in report
    assert "unadjusted_marginal_association" in report
