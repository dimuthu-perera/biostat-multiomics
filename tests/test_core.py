import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from correlation_tool import (
    AcknowledgementRequired,
    CorrelationConfig,
    DatasetDeclaration,
    MatrixFormatError,
    NoTestablePairsError,
    StudyDesignDeclaration,
    ValidationError,
    align_samples,
    analyze_validated_run,
    benjamini_hochberg,
    inspect_dataset,
    inspect_run,
    load_matrix,
    create_acknowledgement,
)
from correlation_tool.analysis import NumericalAnalysisError, _compute_cross_correlation
from correlation_tool.inspection import Severity


def independent():
    return StudyDesignDeclaration("independent", "one independent sample per subject")


def meta_decl(name="A"):
    return DatasetDeclaration("metabolomics", "normalized", name)


def test_alignment_preserves_a_order_and_reorders_b():
    a = pd.DataFrame({"m1": [1.0, 2.0, 3.0]}, index=["S1", "S2", "S3"])
    b = pd.DataFrame({"g1": [30.0, 10.0, 20.0]}, index=["S3", "S1", "S2"])
    aa, bb, report = align_samples(a, b)
    assert aa.index.tolist() == ["S1", "S2", "S3"]
    assert bb.index.tolist() == ["S1", "S2", "S3"]
    assert bb["g1"].tolist() == [10.0, 20.0, 30.0]
    assert report["n_common"] == 3


def test_csv_preserves_leading_zero_and_literal_na_ids(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Sample,g1\n001,1\nNA,2\n1e3,3\n", encoding="utf-8")
    df = load_matrix(p)
    assert df.index.tolist() == ["001", "NA", "1e3"]


def test_numeric_looking_ids_do_not_false_match(tmp_path):
    p1 = tmp_path / "a.csv"
    p2 = tmp_path / "b.csv"
    p1.write_text("Sample,x\n001,1\n002,2\n003,3\n", encoding="utf-8")
    p2.write_text("Sample,y\n1,10\n2,20\n3,30\n", encoding="utf-8")
    a = load_matrix(p1)
    b = load_matrix(p2)
    aa, bb, report = align_samples(a, b)
    assert report["n_common"] == 0
    assert aa.empty and bb.empty


def test_empty_identifier_blocks_at_import(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Sample,g1\n,1\nS2,2\n", encoding="utf-8")
    with pytest.raises(MatrixFormatError, match="empty"):
        load_matrix(p)


def test_duplicate_headers_detected_before_mangling(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Sample,x,x\nS1,1,2\nS2,3,4\n", encoding="utf-8")
    with pytest.raises(MatrixFormatError, match="Duplicate column"):
        load_matrix(p)


def test_duplicate_row_ids_detected_at_import(tmp_path):
    p = tmp_path / "x.tsv"
    p.write_text("Sample\tx\nS1\t1\nS1\t2\n", encoding="utf-8")
    with pytest.raises(MatrixFormatError, match="Duplicate row"):
        load_matrix(p)


def test_ragged_rows_rejected(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Sample,x,y\nS1,1,2\nS2,3\n", encoding="utf-8")
    with pytest.raises(MatrixFormatError, match="Ragged"):
        load_matrix(p)


def test_legacy_xls_explicitly_unsupported(tmp_path):
    p = tmp_path / "x.xls"
    p.write_bytes(b"dummy")
    with pytest.raises(MatrixFormatError, match="not supported"):
        load_matrix(p)


def test_rna_fail_open_closed_for_normalized_label():
    df = pd.DataFrame({"g1": [1, 2, 3]}, index=["S1", "S2", "S3"])
    report = inspect_dataset(df, DatasetDeclaration("rna_seq", "normalized"))
    assert report.status == Severity.BLOCKED
    assert any(i.code == "invalid_preprocessing_declaration" for i in report.issues)


def test_microbiome_normalized_counts_blocked():
    df = pd.DataFrame({"t1": [1, 2, 3]}, index=["S1", "S2", "S3"])
    report = inspect_dataset(df, DatasetDeclaration("metagenomics", "normalized_counts"))
    assert report.status == Severity.BLOCKED


def test_clr_requires_details_and_count_like_warns_with_details():
    df = pd.DataFrame({"t1": [1, 2, 3], "t2": [4, 5, 6]}, index=["S1", "S2", "S3"])
    blocked = inspect_dataset(df, DatasetDeclaration("metagenomics", "clr"))
    assert blocked.status == Severity.BLOCKED
    report = inspect_dataset(df, DatasetDeclaration("metagenomics", "clr", preprocessing_details="zeros replaced upstream; full taxa set"))
    assert report.status == Severity.WARNING
    codes = {i.code for i in report.issues}
    assert "microbiome_count_like_mismatch" in codes


def test_unknown_study_design_blocks_public_run():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=idx)
    b = pd.DataFrame({"b": [3.0, 2.0, 1.0]}, index=idx)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), StudyDesignDeclaration("unknown"), CorrelationConfig(method="pearson"))
    assert inspected.blocked
    assert any(i.code == "study_design_unknown" for i in inspected.issues)
    with pytest.raises(ValidationError):
        analyze_validated_run(inspected)


def test_dependent_design_blocks():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=idx)
    b = pd.DataFrame({"b": [3.0, 2.0, 1.0]}, index=idx)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), StudyDesignDeclaration("dependent_or_clustered"), CorrelationConfig(method="pearson"))
    assert any(i.code == "dependent_observations_unsupported" for i in inspected.issues)


def test_public_run_requires_warning_acknowledgement():
    idx = ["S1", "S2", "S3", "S4"]
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    b = pd.DataFrame({"b": [4.0, 3.0, 2.0, 1.0]}, index=idx)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), independent(), CorrelationConfig(method="pearson"))
    assert "study_design:unadjusted_association" in inspected.warning_issue_ids
    with pytest.raises(AcknowledgementRequired):
        analyze_validated_run(inspected)
    completed = analyze_validated_run(inspected, acknowledgement=create_acknowledgement(inspected))
    assert completed.family_metadata["m_tested"] == 1


def test_run_fingerprint_changes_with_config():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=idx)
    b = pd.DataFrame({"b": [3.0, 2.0, 1.0]}, index=idx)
    r1 = inspect_run(a, b, meta_decl(), meta_decl("B"), independent(), CorrelationConfig(method="pearson", min_pairwise_n=3))
    r2 = inspect_run(a, b, meta_decl(), meta_decl("B"), independent(), CorrelationConfig(method="spearman", min_pairwise_n=3))
    assert r1.fingerprint != r2.fingerprint


def test_spearman_n3_exact_two_sided_permutation_p_is_one_third():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame({"a": pd.Series([1, 2, 3], dtype="Int64", index=idx)}, index=idx)
    b = pd.DataFrame({"b": pd.Series([1, 2, 3], dtype="Int64", index=idx)}, index=idx)
    result, family = _compute_cross_correlation(a, b, CorrelationConfig(method="spearman"))
    assert result.loc[0, "estimate"] == pytest.approx(1.0)
    assert result.loc[0, "p_value"] == pytest.approx(1 / 3)
    assert result.loc[0, "p_value_method"] == "spearman_exact_pairings_abs_tail"
    assert family["m_tested"] == 1


def test_spearman_n4_tied_exact_not_zero():
    idx = [f"S{i}" for i in range(4)]
    a = pd.DataFrame({"a": [0, 0, 1, 1]}, index=idx, dtype="int64")
    b = pd.DataFrame({"b": [0, 0, 1, 1]}, index=idx, dtype="int64")
    result, _ = _compute_cross_correlation(a, b, CorrelationConfig(method="spearman"))
    assert result.loc[0, "p_value"] == pytest.approx(1 / 3)


def test_spearman_preserves_large_int_ordering():
    idx = ["S1", "S2", "S3", "S4"]
    base = 2**53
    a = pd.DataFrame({"a": pd.Series([base, base + 1, base + 2, base + 3], dtype="Int64", index=idx)}, index=idx)
    b = pd.DataFrame({"b": pd.Series([1, 2, 3, 4], dtype="Int64", index=idx)}, index=idx)
    result, _ = _compute_cross_correlation(a, b, CorrelationConfig(method="spearman"))
    assert result.loc[0, "estimate"] == pytest.approx(1.0)


def test_pearson_large_integer_precision_failure_prevents_fdr():
    idx = ["S1", "S2", "S3"]
    base = 2**53
    a = pd.DataFrame({"a": pd.Series([base, base + 1, base + 2], dtype="Int64", index=idx)}, index=idx)
    b = pd.DataFrame({"b": [1.0, 2.0, 3.0]}, index=idx)
    with pytest.raises(NumericalAnalysisError, match="precision"):
        _compute_cross_correlation(a, b, CorrelationConfig(method="pearson"))


def test_infinity_is_not_pairwise_dropped():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame({"a": [1.0, np.inf, 3.0]}, index=idx)
    b = pd.DataFrame({"b": [1.0, 2.0, 3.0]}, index=idx)
    with pytest.raises(ValueError, match="nonfinite"):
        _compute_cross_correlation(a, b, CorrelationConfig(method="pearson"))


def test_pairwise_n_uses_joint_missing_mask():
    idx = ["S1", "S2", "S3", "S4", "S5"]
    a = pd.DataFrame({"a": [1.0, 2.0, np.nan, 4.0, 5.0]}, index=idx)
    b = pd.DataFrame({"b": [2.0, np.nan, 6.0, 8.0, 10.0]}, index=idx)
    result, _ = _compute_cross_correlation(a, b, CorrelationConfig(method="pearson", min_pairwise_n=3))
    assert int(result.loc[0, "n_pairwise"]) == 3
    assert result.loc[0, "status"] in {"ok", "ok_with_warning"}


def test_all_constant_pairs_not_completed_publicly():
    idx = ["S1", "S2", "S3", "S4"]
    a = pd.DataFrame({"a": [1.0] * 4}, index=idx)
    b = pd.DataFrame({"b": [2.0] * 4}, index=idx)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), independent(), CorrelationConfig(method="pearson"))
    with pytest.raises(NoTestablePairsError):
        analyze_validated_run(inspected, acknowledgement=create_acknowledgement(inspected))


def test_bh_matches_known_example():
    p = pd.Series([0.01, 0.04, 0.03, 0.002, np.nan])
    q = benjamini_hochberg(p)
    expected = np.array([0.02, 0.04, 0.04, 0.008, np.nan])
    np.testing.assert_allclose(q.iloc[:4].to_numpy(), expected[:4], rtol=0, atol=1e-12)
    assert np.isnan(q.iloc[4])


def test_bh_rejects_infinity_and_out_of_range():
    with pytest.raises(ValueError, match="infinity"):
        benjamini_hochberg(pd.Series([0.1, np.inf]))
    with pytest.raises(ValueError, match="within"):
        benjamini_hochberg(pd.Series([0.1, 1.1]))


def test_config_validation_rejects_fractional_n_and_invalid_method():
    with pytest.raises(ValueError, match="integer"):
        CorrelationConfig(min_pairwise_n=3.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unsupported"):
        CorrelationConfig(method="kendall")  # type: ignore[arg-type]


def test_run_size_limit_blocks_at_inspection():
    idx = ["S1", "S2", "S3"]
    a = pd.DataFrame(np.arange(30).reshape(3, 10), index=idx, columns=[f"a{i}" for i in range(10)])
    b = pd.DataFrame(np.arange(30).reshape(3, 10), index=idx, columns=[f"b{i}" for i in range(10)])
    config = CorrelationConfig(method="pearson", max_planned_tests=50)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), independent(), config)
    assert inspected.blocked
    assert any(i.code == "run_size_limit" for i in inspected.issues)


def test_partial_overlap_is_warning_and_records_exact_ids():
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]}, index=["S1", "S2", "S3", "Aonly"])
    b = pd.DataFrame({"b": [1.0, 2.0, 3.0, 4.0]}, index=["S3", "S2", "S1", "Bonly"])
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), independent(), CorrelationConfig(method="pearson"))
    assert any(i.code == "partial_sample_overlap" for i in inspected.issues)
    assert inspected.alignment["canonical_order"] == ["S1", "S2", "S3"]
    assert inspected.alignment["only_a"] == ["Aonly"]
    assert inspected.alignment["only_b"] == ["Bonly"]


def test_samples_columns_orientation_preserves_sample_ids(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Feature,S001,S002,S003\nf1,1,2,3\nf2,4,5,6\n", encoding="utf-8")
    df = load_matrix(p, "samples_columns")
    assert df.index.tolist() == ["S001", "S002", "S003"]
    assert df.columns.tolist() == ["f1", "f2"]
    assert df.loc["S002", "f2"] == 5


def test_xlsx_requires_text_identifiers(tmp_path):
    from openpyxl import Workbook

    p = tmp_path / "x.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Sample", "g1"])
    ws.append([1, 2.0])
    ws.append(["S2", 3.0])
    wb.save(p)
    with pytest.raises(MatrixFormatError, match="stored as text"):
        load_matrix(p)


def test_spearman_monte_carlo_add_one_never_returns_zero():
    idx = [f"S{i}" for i in range(9)]
    a = pd.DataFrame({"a": np.arange(9)}, index=idx)
    b = pd.DataFrame({"b": np.arange(9)}, index=idx)
    result, _ = _compute_cross_correlation(a, b, CorrelationConfig(method="spearman", spearman_permutations=999))
    assert result.loc[0, "p_value"] >= 1 / 1000
    assert result.loc[0, "p_resolution"] == pytest.approx(1 / 1000)
    assert result.loc[0, "p_value_method"] == "spearman_monte_carlo_pairings_abs_tail_add_one"


def test_public_analysis_detects_data_mutation_after_inspection():
    idx = ["S1", "S2", "S3", "S4"]
    a = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    b = pd.DataFrame({"b": [4.0, 3.0, 2.0, 1.0]}, index=idx)
    inspected = inspect_run(a, b, meta_decl("A"), meta_decl("B"), independent(), CorrelationConfig(method="pearson"))
    a.loc["S1", "a"] = 99.0
    with pytest.raises(ValidationError, match="changed after inspection"):
        analyze_validated_run(inspected, acknowledgement=create_acknowledgement(inspected))
