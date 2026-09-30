from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from biostat_tool.bundle import verify_run_bundle, write_run_bundle
from biostat_tool.modules.correlation_backends import (
    BackendEquivalenceError,
    OPTIMIZED_PEARSON_BACKEND_ID,
    OPTIMIZED_SPEARMAN_BACKEND_ID,
    REFERENCE_BACKEND_ID,
    _optimized_complete_pearson_kernel,
    _optimized_pairwise_missing_pearson_kernel,
    _optimized_complete_spearman_kernel,
    compare_to_reference,
)
from biostat_tool.runner import execute_prepared, prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec
from correlation_tool import CorrelationConfig, sha256_file
from correlation_tool.analysis import _compute_cross_correlation

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def _spec(method: str = "pearson") -> AnalysisSpec:
    return AnalysisSpec(
        schema_version="1.0",
        method=method,
        dataset_a=DatasetSpec("a.csv", sha256_file(FIX / "a.csv"), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(FIX / "b.csv"), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )


def test_complete_pearson_optimized_backend_matches_frozen_reference_and_self_verifies():
    prepared = prepare_analysis(_spec("pearson"), base_dir=FIX)
    reference = execute_prepared(prepared, acknowledge_warnings=True, backend="reference")
    optimized = execute_prepared(
        prepared,
        acknowledge_warnings=True,
        backend="optimized",
        verify_against_reference=True,
    )
    assert reference.execution_metadata["actual_backend"] == REFERENCE_BACKEND_ID
    assert optimized.execution_metadata["actual_backend"] == OPTIMIZED_PEARSON_BACKEND_ID
    verification = optimized.execution_metadata["reference_verification"]
    assert verification["status"] == "passed"
    assert verification["global_bh_family_exact"] is True
    assert verification["max_abs_difference"]["estimate"] <= 5e-15
    assert verification["max_abs_difference"]["p_value"] <= 5e-15
    assert verification["max_abs_difference"]["q_value"] <= 5e-15


def test_optimized_kernel_randomized_complete_data_matches_scalar_oracle():
    rng = np.random.default_rng(20260916)
    for case in range(18):
        n = int(rng.integers(3, 90))
        p = int(rng.integers(1, 8))
        q = int(rng.integers(1, 8))
        idx = [f"S{i}" for i in range(n)]
        # Vary represented offsets/scales, but avoid values that collapse all
        # variation at binary64 representation. Constants are inserted explicitly.
        a_arr = rng.normal(size=(n, p)) * np.power(10.0, rng.uniform(-40, 40, size=p))
        b_arr = rng.normal(size=(n, q)) * np.power(10.0, rng.uniform(-40, 40, size=q))
        a = pd.DataFrame(a_arr, index=idx, columns=[f"a{i}" for i in range(p)])
        b = pd.DataFrame(b_arr, index=idx, columns=[f"b{i}" for i in range(q)])
        if case % 4 == 0:
            a.iloc[:, 0] = 7.0
        if case % 5 == 0:
            b.iloc[:, -1] = -3.0
        cfg = CorrelationConfig(method="pearson", min_pairwise_n=3, max_planned_tests=1_000_000)
        scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
        fast, fast_family = _optimized_complete_pearson_kernel(a, b, cfg)
        assert list(fast.columns) == list(scalar.columns)
        for col in ["feature_a", "feature_b", "method", "n_pairwise", "status", "p_value_method", "numerical_warning"]:
            assert fast[col].equals(scalar[col])
        for col in ["estimate", "p_value", "q_value"]:
            np.testing.assert_allclose(
                fast[col].to_numpy(float),
                scalar[col].to_numpy(float),
                atol=5e-15,
                rtol=5e-14,
                equal_nan=True,
            )
        assert fast_family == scalar_family


def test_complete_spearman_optimized_backend_matches_frozen_reference_and_self_verifies():
    prepared = prepare_analysis(_spec("spearman"), base_dir=FIX)
    reference = execute_prepared(prepared, acknowledge_warnings=True, backend="reference")
    optimized = execute_prepared(
        prepared, acknowledge_warnings=True, backend="optimized", verify_against_reference=True
    )
    assert optimized.execution_metadata["requested_backend"] == "optimized"
    assert optimized.execution_metadata["actual_backend"] == OPTIMIZED_SPEARMAN_BACKEND_ID
    assert optimized.execution_metadata["reference_verification"]["status"] == "passed"
    pd.testing.assert_frame_equal(optimized.primary_results, reference.primary_results, check_exact=True)
    assert optimized.module_result.family_metadata == reference.module_result.family_metadata

def test_missing_data_pearson_requested_optimized_uses_pairwise_mask_backend_and_matches_reference(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,x,z\nS1,1,1\nS2,2,2\nS3,3,3\nS4,4,4\n", encoding="utf-8")
    b.write_text("id,y\nS1,4\nS2,NA\nS3,2\nS4,1\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    prepared = prepare_analysis(spec, base_dir=tmp_path)
    completed = execute_prepared(
        prepared,
        acknowledge_warnings=True,
        backend="optimized",
        verify_against_reference=True,
    )
    assert completed.execution_metadata["actual_backend"] == OPTIMIZED_PEARSON_BACKEND_ID
    assert completed.execution_metadata["fallback_reason"] == ""
    assert completed.execution_metadata["reference_verification"]["status"] == "passed"
    assert completed.primary_results["n_pairwise"].tolist() == [3, 3]


def test_equivalence_harness_rejects_material_result_change():
    prepared = prepare_analysis(_spec("pearson"), base_dir=FIX)
    reference = execute_prepared(prepared, acknowledge_warnings=True, backend="reference").oracle_run
    optimized = execute_prepared(prepared, acknowledge_warnings=True, backend="optimized").oracle_run
    bad = copy.deepcopy(optimized)
    bad.results.loc[0, "estimate"] += 1e-6
    with pytest.raises(BackendEquivalenceError, match="estimate"):
        compare_to_reference(bad, reference)


def test_runbundle_records_backend_provenance_and_verifies(tmp_path):
    prepared = prepare_analysis(_spec("pearson"), base_dir=FIX)
    completed = execute_prepared(
        prepared,
        acknowledge_warnings=True,
        backend="optimized",
        verify_against_reference=True,
    )
    run_dir = write_run_bundle(completed, tmp_path / "run")
    verification = verify_run_bundle(run_dir)
    assert verification.valid, verification.errors
    manifest = json.loads((run_dir / "manifest.json").read_text())
    provenance = json.loads((run_dir / "provenance.json").read_text())
    assert manifest["execution_backend"] == provenance["execution"]["backend"]
    assert manifest["execution_backend"]["actual_backend"] == OPTIMIZED_PEARSON_BACKEND_ID
    assert manifest["execution_backend"]["reference_verification"]["status"] == "passed"

@pytest.mark.parametrize(
    "x,y",
    [
        ([1e14, 1e14 + .01, 1e14 + .02, 1e14 + .03], [1.0, 2.0, 3.0, 4.0]),
        ([1e-320, 2e-320, 3e-320, 4e-320], [4e-320, 3e-320, 2e-320, 1e-320]),
        ([1.0, 2.0, 4.0], [9.0, 3.0, 7.0]),
    ],
)
def test_optimized_complete_pearson_matches_reference_numerical_stress(x, y):
    idx = [f"S{i}" for i in range(len(x))]
    a = pd.DataFrame({"a": x}, index=idx)
    b = pd.DataFrame({"b": y}, index=idx)
    cfg = CorrelationConfig(method="pearson")
    scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
    fast, fast_family = _optimized_complete_pearson_kernel(a, b, cfg)
    np.testing.assert_allclose(fast["estimate"], scalar["estimate"], atol=5e-15, rtol=5e-14, equal_nan=True)
    np.testing.assert_allclose(fast["p_value"], scalar["p_value"], atol=5e-15, rtol=5e-14, equal_nan=True)
    np.testing.assert_allclose(fast["q_value"], scalar["q_value"], atol=5e-15, rtol=5e-14, equal_nan=True)
    assert fast_family == scalar_family

def test_default_reference_backend_preserves_accepted_static_spearman_csv_hash():
    import hashlib
    from biostat_tool.specs import load_analysis_spec

    spec = load_analysis_spec(FIX / "analysis_spearman.json")
    completed = execute_prepared(prepare_analysis(spec, base_dir=FIX), acknowledge_warnings=True)
    payload = completed.primary_results.to_csv(index=False, lineterminator="\n").encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == "3b972d8e6223464bde0ecb1c082de27f4ae969f8db15199e7eec2673feb13f9e"
    assert completed.execution_metadata["requested_backend"] == "reference"
    assert completed.execution_metadata["actual_backend"] == REFERENCE_BACKEND_ID


def test_exact_integer_above_2_53_requested_optimized_falls_back_to_reference(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    # Use CSV integer tokens so pandas imports int64 and the frozen Pearson policy
    # can detect exact integers that cannot be converted losslessly to binary64.
    a.write_text("id,x\nS1,9007199254740993\nS2,9007199254740994\nS3,9007199254740995\n", encoding="utf-8")
    b.write_text("id,y\nS1,1\nS2,2\nS3,3\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    prepared = prepare_analysis(spec, base_dir=tmp_path)
    with pytest.raises(RuntimeError, match="unresolved numerical/precision failures"):
        # The reference oracle intentionally withholds FDR finalization for this
        # precision-unsafe request; requesting optimization must not bypass that.
        execute_prepared(prepared, acknowledge_warnings=True, backend="optimized")



def _assert_pearson_tables_equivalent(fast: pd.DataFrame, scalar: pd.DataFrame) -> None:
    assert list(fast.columns) == list(scalar.columns)
    exact = ["feature_a", "feature_b", "method", "n_pairwise", "status", "p_value_method", "numerical_warning"]
    for col in exact:
        assert fast[col].equals(scalar[col]), col
    metadata = [
        "permutations", "extreme_count", "p_resolution", "exact_probability_unit",
        "exact_min_attainable_p", "monte_carlo_floor", "tied_x", "tied_y",
    ]
    for col in metadata:
        assert np.array_equal(fast[col].to_numpy(float), scalar[col].to_numpy(float), equal_nan=True), col
    for col in ["estimate", "p_value", "q_value"]:
        np.testing.assert_allclose(
            fast[col].to_numpy(float), scalar[col].to_numpy(float),
            atol=5e-15, rtol=5e-14, equal_nan=True,
        )


def test_pairwise_missing_kernel_randomized_structured_masks_matches_scalar_oracle():
    rng = np.random.default_rng(20260917)
    for case in range(20):
        n = int(rng.integers(8, 70))
        p = int(rng.integers(2, 8))
        q = int(rng.integers(2, 8))
        idx = [f"S{i}" for i in range(n)]
        a = pd.DataFrame(rng.normal(size=(n, p)), index=idx, columns=[f"a{i}" for i in range(p)])
        b = pd.DataFrame(rng.normal(size=(n, q)), index=idx, columns=[f"b{i}" for i in range(q)])

        masks_a = []
        masks_b = []
        for _ in range(3):
            m = rng.random(n) > rng.uniform(0.05, 0.30)
            if m.sum() < 3:
                m[:3] = True
            masks_a.append(m)
            m = rng.random(n) > rng.uniform(0.05, 0.30)
            if m.sum() < 3:
                m[:3] = True
            masks_b.append(m)
        for j in range(p):
            a.loc[~masks_a[j % len(masks_a)], a.columns[j]] = np.nan
        for j in range(q):
            b.loc[~masks_b[j % len(masks_b)], b.columns[j]] = np.nan

        if case % 4 == 0:
            # Constant after pairwise deletion is still a pair-level decision.
            observed = a.iloc[:, 0].notna()
            a.loc[observed, a.columns[0]] = 4.0
        if case % 5 == 0:
            observed = b.iloc[:, -1].notna()
            b.loc[observed, b.columns[-1]] = -2.0

        cfg = CorrelationConfig(method="pearson", min_pairwise_n=3, max_planned_tests=1_000_000)
        scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
        fast, fast_family = _optimized_pairwise_missing_pearson_kernel(a, b, cfg)
        _assert_pearson_tables_equivalent(fast, scalar)
        assert fast_family == scalar_family


def test_pairwise_missing_kernel_preserves_insufficient_n_and_subset_constant_semantics():
    idx = ["S1", "S2", "S3", "S4", "S5", "S6"]
    a = pd.DataFrame(
        {
            "subset_constant": [1.0, 1.0, 1.0, 2.0, 3.0, 4.0],
            "varying": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }, index=idx,
    )
    b = pd.DataFrame(
        {
            "first3": [4.0, 5.0, 6.0, np.nan, np.nan, np.nan],
            "only2": [1.0, 2.0, np.nan, np.nan, np.nan, np.nan],
            "all": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        }, index=idx,
    )
    cfg = CorrelationConfig(method="pearson", min_pairwise_n=3)
    scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
    fast, fast_family = _optimized_pairwise_missing_pearson_kernel(a, b, cfg)
    _assert_pearson_tables_equivalent(fast, scalar)
    assert fast_family == scalar_family
    lookup = fast.set_index(["feature_a", "feature_b"])
    assert lookup.loc[("subset_constant", "first3"), "status"] == "constant_pair"
    assert lookup.loc[("varying", "only2"), "status"] == "insufficient_pairwise_n"
    assert lookup.loc[("varying", "all"), "n_pairwise"] == 6


def test_pairwise_missing_kernel_calls_global_bh_once(monkeypatch):
    import biostat_tool.modules.correlation_backends as backends

    rng = np.random.default_rng(7)
    n, p, q = 30, 8, 9
    idx = [f"S{i}" for i in range(n)]
    a = pd.DataFrame(rng.normal(size=(n, p)), index=idx, columns=[f"a{i}" for i in range(p)])
    b = pd.DataFrame(rng.normal(size=(n, q)), index=idx, columns=[f"b{i}" for i in range(q)])
    a.loc[["S1", "S2"], a.columns[::2]] = np.nan
    b.loc[["S3", "S4", "S5"], b.columns[::3]] = np.nan
    calls = []
    real = backends.benjamini_hochberg

    def counted(values):
        calls.append(len(values))
        return real(values)

    monkeypatch.setattr(backends, "benjamini_hochberg", counted)
    fast, family = backends._optimized_pairwise_missing_pearson_kernel(a, b, CorrelationConfig(method="pearson"))
    assert calls == [family["m_eligible"]]
    assert fast["q_value"].notna().sum() == family["m_eligible"]


def test_highly_fragmented_pairwise_missingness_falls_back_to_reference(tmp_path):
    rng = np.random.default_rng(12345)
    n, p, q = 70, 40, 40
    ids = [f"S{i:03d}" for i in range(n)]
    a_df = pd.DataFrame(rng.normal(size=(n, p)), columns=[f"a{i}" for i in range(p)])
    b_df = pd.DataFrame(rng.normal(size=(n, q)), columns=[f"b{i}" for i in range(q)])
    # Independent cell missingness makes nearly every feature mask unique.
    a_df[rng.random((n, p)) < 0.12] = np.nan
    b_df[rng.random((n, q)) < 0.12] = np.nan
    a_df.insert(0, "id", ids)
    b_df.insert(0, "id", ids)
    a_path = tmp_path / "a.csv"
    b_path = tmp_path / "b.csv"
    a_df.to_csv(a_path, index=False)
    b_df.to_csv(b_path, index=False)
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a_path), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b_path), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    completed = execute_prepared(
        prepare_analysis(spec, base_dir=tmp_path),
        acknowledge_warnings=True,
        backend="optimized",
    )
    assert completed.execution_metadata["actual_backend"] == REFERENCE_BACKEND_ID
    assert "insufficient reuse" in completed.execution_metadata["fallback_reason"] or "fragmented" in completed.execution_metadata["fallback_reason"]


def test_runbundle_verifier_accepts_historical_v040_backend_identifier(tmp_path):
    import hashlib
    from biostat_tool.bundle import verify_run_bundle, write_run_bundle

    prepared = prepare_analysis(_spec("pearson"), base_dir=FIX)
    completed = execute_prepared(prepared, acknowledge_warnings=True, backend="optimized")
    run_dir = write_run_bundle(completed, tmp_path / "run")

    provenance_path = run_dir / "provenance.json"
    manifest_path = run_dir / "manifest.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy = copy.deepcopy(manifest["execution_backend"])
    legacy["actual_backend"] = "optimized_complete_pearson_v0.4.0"
    legacy["optimized_subset"] = "complete_data_pearson_only"
    manifest["execution_backend"] = legacy
    provenance["execution"]["backend"] = copy.deepcopy(legacy)

    provenance_bytes = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8")
    provenance_path.write_bytes(provenance_bytes)
    for entry in manifest["content"]:
        if entry["path"] == "provenance.json":
            entry["bytes"] = len(provenance_bytes)
            entry["sha256"] = hashlib.sha256(provenance_bytes).hexdigest()
            break
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_run_bundle(run_dir)
    assert verification.valid, verification.errors


def test_pairwise_missing_stabilization_failure_falls_back_to_reference(tmp_path, monkeypatch):
    import biostat_tool.modules.correlation_backends as backends

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,x,z\nS1,1,2\nS2,2,3\nS3,3,4\nS4,4,5\n", encoding="utf-8")
    b.write_text("id,y\nS1,4\nS2,NA\nS3,2\nS4,1\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    prepared = prepare_analysis(spec, base_dir=tmp_path)

    def fail_stabilization(values):
        raise FloatingPointError("injected optimized-only stabilization failure")

    monkeypatch.setattr(backends, "_stable_affine_vector", fail_stabilization)
    completed = execute_prepared(prepared, acknowledge_warnings=True, backend="optimized")
    assert completed.execution_metadata["actual_backend"] == REFERENCE_BACKEND_ID
    assert "stabilization" in completed.execution_metadata["fallback_reason"]
    assert completed.primary_results["status"].eq("ok").all()


def _spearman_frames(n: int, *, ties: bool = False, seed: int = 20260917):
    rng = np.random.default_rng(seed)
    idx = [f"S{i}" for i in range(n)]
    xa = rng.normal(size=(n, 4))
    xb = rng.normal(size=(n, 5))
    if ties:
        xa[:, 0] = np.round(xa[:, 0], 0)
        xb[:, 1] = np.round(xb[:, 1], 0)
    return (
        pd.DataFrame(xa, index=idx, columns=[f"a{i}" for i in range(4)]),
        pd.DataFrame(xb, index=idx, columns=[f"b{i}" for i in range(5)]),
    )


@pytest.mark.parametrize(
    "n,ties,expected_method",
    [
        (7, True, "spearman_exact_pairings_abs_tail"),
        (15, False, "spearman_monte_carlo_pairings_abs_tail_add_one"),
        (15, True, "spearman_monte_carlo_pairings_abs_tail_add_one"),
        (501, False, "scipy_spearmanr_asymptotic_N_ge_501_untied"),
        (501, True, "spearman_monte_carlo_pairings_abs_tail_add_one"),
    ],
)
def test_optimized_complete_spearman_matches_reference_all_inference_branches(n, ties, expected_method):
    a, b = _spearman_frames(n, ties=ties, seed=1000 + n + int(ties))
    cfg = CorrelationConfig(
        method="spearman",
        spearman_permutations=999,
        max_spearman_total_null_evaluations=2_000_000,
    )
    scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
    fast, fast_family = _optimized_complete_spearman_kernel(a, b, cfg)
    pd.testing.assert_frame_equal(fast, scalar, check_exact=True)
    assert fast_family == scalar_family
    tested = fast[fast["status"].eq("ok")]
    assert expected_method in set(tested["p_value_method"])


def test_complete_spearman_preserves_constant_pairs_exactly():
    a, b = _spearman_frames(15, ties=True)
    a["constant"] = 3.0
    b["constant"] = -2.0
    cfg = CorrelationConfig(method="spearman", spearman_permutations=999)
    scalar, scalar_family = _compute_cross_correlation(a, b, cfg)
    fast, fast_family = _optimized_complete_spearman_kernel(a, b, cfg)
    pd.testing.assert_frame_equal(fast, scalar, check_exact=True)
    assert fast_family == scalar_family


def test_spearman_with_missingness_requested_optimized_falls_back_to_reference(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,x\nS1,1\nS2,2\nS3,\nS4,4\n", encoding="utf-8")
    b.write_text("id,y\nS1,4\nS2,3\nS3,2\nS4,1\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="spearman",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3, spearman_permutations=999),
    )
    completed = execute_prepared(
        prepare_analysis(spec, base_dir=tmp_path),
        acknowledge_warnings=True,
        backend="optimized",
    )
    assert completed.execution_metadata["actual_backend"] == REFERENCE_BACKEND_ID
    assert "complete aligned data only" in completed.execution_metadata["fallback_reason"]
