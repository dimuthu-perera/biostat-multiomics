from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from biostat_tool.bundle import write_run_bundle
from biostat_tool.cli import main
import biostat_tool.modules.correlation as correlation_module
from biostat_tool.modules.correlation import InputIntegrityError
from biostat_tool.runner import execute_prepared, prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec, load_analysis_spec
from correlation_tool import AcknowledgementRequired, sha256_file

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def spec_for(method="spearman") -> AnalysisSpec:
    return AnalysisSpec(
        schema_version="1.0",
        method=method,
        dataset_a=DatasetSpec("a.csv", sha256_file(FIX / "a.csv"), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(FIX / "b.csv"), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )


def test_runner_requires_exact_file_hash(tmp_path):
    spec = spec_for()
    bad = FIX / "a.csv"
    other = tmp_path / "a.csv"
    other.write_bytes(bad.read_bytes() + b"\n")
    with pytest.raises(InputIntegrityError, match="SHA-256 mismatch"):
        prepare_analysis(spec, base_dir=FIX, path_overrides={"dataset_a": other})


def test_prepare_and_execute_share_oracle_and_bind_review():
    spec = spec_for("spearman")
    prepared = prepare_analysis(spec, base_dir=FIX)
    assert not prepared.blocked
    assert "study_design:unadjusted_association" in prepared.warning_issue_ids
    with pytest.raises(AcknowledgementRequired):
        execute_prepared(prepared)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    assert completed.effective_spec.review.inspected_run_fingerprint == prepared.inspected.fingerprint
    assert set(completed.effective_spec.review.acknowledged_warning_issue_ids) == set(prepared.warning_issue_ids)
    assert len(completed.oracle_run.results) == 4


def test_effective_spec_can_be_replayed_without_ack_flag(tmp_path):
    prepared = prepare_analysis(spec_for("pearson"), base_dir=FIX)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    spec_path = tmp_path / "analysis.json"
    spec_path.write_text(completed.effective_spec.canonical_json())
    replay = prepare_analysis(load_analysis_spec(spec_path), base_dir=FIX)
    rerun = execute_prepared(replay)
    pd.testing.assert_frame_equal(completed.oracle_run.results, rerun.oracle_run.results)


def test_runbundle_contains_standard_contract(tmp_path):
    prepared = prepare_analysis(spec_for(), base_dir=FIX)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    run_dir = write_run_bundle(completed, tmp_path / "run")
    expected = {
        "analysis.json", "analysis.requested.json", "manifest.json", "inspection.json", "alignment.json",
        "results/correlations.csv", "report/report.html", "logs/run.log",
    }
    actual = {p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()}
    assert expected <= actual
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["bundle_schema_version"] == "1.0"
    assert manifest["platform"]["version"] == "1.0.0"
    assert manifest["oracle_engine"]["version"] == "0.2.4"
    assert manifest["analysis"]["effective_spec_sha256"] == completed.effective_spec.sha256()
    assert "results/correlations.csv" in {x["path"] for x in manifest["content"]}


def test_cli_validate_and_run_use_same_spec(tmp_path, capsys):
    spec = spec_for()
    spec_path = tmp_path / "analysis.json"
    # Paths are relative to spec file, so copy tiny fixture inputs beside it.
    (tmp_path / "a.csv").write_bytes((FIX / "a.csv").read_bytes())
    (tmp_path / "b.csv").write_bytes((FIX / "b.csv").read_bytes())
    spec_path.write_text(spec.canonical_json())
    assert main(["validate", str(spec_path)]) == 0
    out = tmp_path / "bundle"
    assert main(["run", str(spec_path), "--acknowledge-warnings", "--output", str(out)]) == 0
    assert (out / "manifest.json").is_file()
    assert (out / "analysis.json").is_file()


def test_cli_verify_runbundle(tmp_path, capsys):
    prepared = prepare_analysis(spec_for(), base_dir=FIX)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    run_dir = write_run_bundle(completed, tmp_path / "run")
    assert main(["verify", str(run_dir)]) == 0
    assert "RunBundle: VALID" in capsys.readouterr().out


def test_prepare_analysis_parses_exact_hash_verified_snapshot(tmp_path, monkeypatch):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,x\nS1,1\nS2,2\nS3,3\n", encoding="utf-8")
    b.write_text("id,y\nS1,3\nS2,2\nS3,1\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    expected_hash = sha256_file(a)
    expected_bytes = a.stat().st_size
    real_load = correlation_module.load_matrix
    mutated = {"done": False}

    def wrapped_load(path, *args, **kwargs):
        if not mutated["done"]:
            # Change the original file after the private snapshot has been created but
            # immediately before the parser consumes its input.
            a.write_text("id,x\nS1,99\nS2,2\nS3,3\n", encoding="utf-8")
            mutated["done"] = True
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr(correlation_module, "load_matrix", wrapped_load)
    prepared = prepare_analysis(spec, base_dir=tmp_path)
    assert prepared.inspected.a.loc["S1", "x"] == 1.0
    assert prepared.source_identity["dataset_a"]["sha256"] == expected_hash
    assert prepared.source_identity["dataset_a"]["bytes"] == expected_bytes
    assert sha256_file(a) != expected_hash


def test_runbundle_input_identity_uses_verified_snapshot_not_later_source_stat(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,x\nS1,1\nS2,2\nS3,3\n", encoding="utf-8")
    b.write_text("id,y\nS1,3\nS2,2\nS3,1\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    prepared = prepare_analysis(spec, base_dir=tmp_path)
    completed = execute_prepared(prepared, acknowledge_warnings=True)
    original_bytes = prepared.source_identity["dataset_a"]["bytes"]
    a.write_text(a.read_text() + "S4,4\n", encoding="utf-8")
    run_dir = write_run_bundle(completed, tmp_path / "snapshot-run")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["inputs"]["dataset_a"]["bytes"] == original_bytes
    assert manifest["inputs"]["dataset_a"]["sha256"] == spec.dataset_a.sha256
