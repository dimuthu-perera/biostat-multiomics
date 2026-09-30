from __future__ import annotations

import json
from pathlib import Path

import pytest

from biostat_tool.specs import AnalysisSpec, DatasetSpec, StudyDesignSpec, CorrelationSpec, SpecError, load_analysis_spec, save_analysis_spec


def make_spec(tmp_path: Path) -> AnalysisSpec:
    return AnalysisSpec(
        schema_version="1.0",
        method="spearman",
        dataset_a=DatasetSpec("a.csv", "a" * 64, "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", "b" * 64, "samples_rows", "rna_seq", "vst"),
        study_design=StudyDesignSpec("independent", "one sample per participant"),
        correlation=CorrelationSpec(3, 9999, 123),
    )


def test_canonical_json_roundtrip_is_stable(tmp_path):
    spec = make_spec(tmp_path)
    p = tmp_path / "analysis.json"
    save_analysis_spec(spec, p)
    loaded = load_analysis_spec(p)
    assert loaded == spec
    assert loaded.canonical_json() == spec.canonical_json()
    assert loaded.sha256() == spec.sha256()


def test_unknown_fields_are_rejected():
    raw = make_spec(Path(".")).to_dict()
    raw["analysis"]["typo"] = True
    with pytest.raises(SpecError, match="unknown field"):
        AnalysisSpec.from_dict(raw)


def test_multiple_testing_policy_is_fixed():
    raw = make_spec(Path(".")).to_dict()
    raw["multiple_testing"]["method"] = "bonferroni"
    with pytest.raises(SpecError, match="supports only Benjamini-Hochberg"):
        AnalysisSpec.from_dict(raw)


def test_yaml_is_optional_not_core_dependency(tmp_path, monkeypatch):
    spec = make_spec(tmp_path)
    # JSON path always works without YAML support.
    p = tmp_path / "analysis.json"
    p.write_text(spec.canonical_json())
    assert load_analysis_spec(p) == spec


def test_dataset_paths_must_be_portable_relative():
    with pytest.raises(SpecError, match="portable relative"):
        DatasetSpec("/srv/project/a.csv", "a" * 64, "samples_rows", "metabolomics", "quantitative")
    with pytest.raises(SpecError, match="portable relative"):
        DatasetSpec("../a.csv", "a" * 64, "samples_rows", "metabolomics", "quantitative")
    with pytest.raises(SpecError, match="portable relative"):
        DatasetSpec(r"C:\\data\\a.csv", "a" * 64, "samples_rows", "metabolomics", "quantitative")


def test_output_root_must_be_portable_relative():
    from biostat_tool.specs import OutputSpec

    with pytest.raises(SpecError, match="portable relative"):
        OutputSpec("/tmp/runs")
    with pytest.raises(SpecError, match="portable relative"):
        OutputSpec("../runs")


def test_duplicate_json_keys_are_rejected_before_canonicalization(tmp_path):
    spec = make_spec(tmp_path)
    text = spec.canonical_json()
    text = text.replace('"method":"spearman"', '"method":"spearman","method":"pearson"', 1)
    path = tmp_path / "duplicate.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SpecError, match="Duplicate specification field 'method'"):
        load_analysis_spec(path)
