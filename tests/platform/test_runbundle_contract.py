from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from biostat_tool.bundle import RunBundleError, verify_run_bundle, write_run_bundle, zip_run_bundle
from biostat_tool.runner import execute_prepared, prepare_analysis
from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec
from correlation_tool import sha256_file

FIX = Path(__file__).resolve().parents[1] / "oracle" / "fixtures"


def _completed():
    spec = AnalysisSpec(
        schema_version="1.0",
        method="spearman",
        dataset_a=DatasetSpec("a.csv", sha256_file(FIX / "a.csv"), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(FIX / "b.csv"), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    return execute_prepared(prepare_analysis(spec, base_dir=FIX), acknowledge_warnings=True)


def test_runbundle_v1_is_self_verifying_and_inventory_is_complete(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")
    verified = verify_run_bundle(run_dir)
    assert verified.valid, verified.errors
    manifest = verified.manifest
    assert manifest is not None
    assert manifest["bundle_schema_version"] == "1.0"
    assert manifest["bundle_type"] == "biostat_run"
    assert manifest["privacy"]["raw_input_data_included"] is False
    assert manifest["privacy"]["absolute_input_paths_recorded"] is False
    listed = {x["path"] for x in manifest["content"]}
    on_disk = {p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file() and p.name != "manifest.json"}
    assert listed == on_disk
    assert "provenance.json" in listed
    assert "results/schema.json" in listed



def test_bundle_self_verification_rejects_metadata_that_disagrees_with_executed_oracle(tmp_path):
    completed = _completed()
    # Even completed mappings are ordinary Python mappings.  If downstream code
    # tampers with them before publication, the writer must not publish a bundle
    # whose own file hashes are valid but whose provenance contradicts execution.
    completed.inspection_document["run_fingerprint"] = "0" * 64
    completed.alignment_document["n_common"] = 999
    destination = tmp_path / "run"
    with pytest.raises(RunBundleError, match="verification failed"):
        write_run_bundle(completed, destination)
    assert not destination.exists()



def _rehash_manifest_entry(run_dir: Path, rel: str) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = run_dir / rel
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    for entry in manifest["content"]:
        if entry["path"] == rel:
            entry["sha256"] = digest
            entry["bytes"] = target.stat().st_size
            break
    else:
        raise AssertionError(f"missing inventory entry for {rel}")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_nested_completed_alignment_mutation_cannot_publish_false_sample_provenance(tmp_path):
    completed = _completed()
    assert completed.alignment_document["common_order"][0] == "S1"
    completed.alignment_document["common_order"][0] = "NOT_ANALYZED"
    # The independent oracle-manifest copy remains authoritative.
    assert completed.module_provenance["oracle"]["manifest"]["alignment"]["common_order"][0] == "S1"

    destination = tmp_path / "run"
    with pytest.raises(RunBundleError, match="verification failed"):
        write_run_bundle(completed, destination)
    assert not destination.exists()


def test_missing_executed_oracle_metadata_invalidates_bundle_even_with_recomputed_inventory(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")

    alignment_path = run_dir / "alignment.json"
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    alignment["n_common"] = 999
    alignment_path.write_text(json.dumps(alignment, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.pop("oracle", None)
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _rehash_manifest_entry(run_dir, "alignment.json")
    _rehash_manifest_entry(run_dir, "provenance.json")

    verified = verify_run_bundle(run_dir)
    assert not verified.valid
    assert any("missing required executed frozen-oracle metadata" in error for error in verified.errors)


def test_runbundle_does_not_record_resolved_absolute_dataset_paths(tmp_path):
    completed = _completed()
    run_dir = write_run_bundle(completed, tmp_path / "run")
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in run_dir.rglob("*") if p.is_file())
    for resolved in completed.resolved_paths.values():
        assert str(resolved.resolve()) not in text
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["inputs"]["dataset_a"]["logical_path"] == "a.csv"
    assert manifest["inputs"]["dataset_b"]["logical_path"] == "b.csv"


def test_tampered_result_file_invalidates_bundle_and_report(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")
    with (run_dir / "results" / "correlations.csv").open("a", encoding="utf-8") as fh:
        fh.write("tampered\n")
    verified = verify_run_bundle(run_dir)
    assert not verified.valid
    assert any("SHA-256 mismatch" in x or "row_count" in x for x in verified.errors)
    from biostat_tool.reporting import render_html_report

    with pytest.raises(RunBundleError):
        render_html_report(run_dir)


def test_uninventoried_file_invalidates_bundle(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")
    (run_dir / "notes.txt").write_text("not inventoried\n")
    verified = verify_run_bundle(run_dir)
    assert not verified.valid
    assert any("not inventoried" in x for x in verified.errors)


def test_zip_requires_valid_bundle(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")
    archive = zip_run_bundle(run_dir, tmp_path / "run.zip")
    assert archive.is_file()
    (run_dir / "alignment.json").unlink()
    with pytest.raises(RunBundleError):
        zip_run_bundle(run_dir, tmp_path / "invalid.zip")


def test_completed_bundle_is_immutable_for_report_exports(tmp_path):
    run_dir = write_run_bundle(_completed(), tmp_path / "run")
    from biostat_tool.reporting import render_html_report

    canonical = run_dir / "report" / "report.html"
    before = canonical.read_bytes()
    assert render_html_report(run_dir) == canonical.resolve()
    assert canonical.read_bytes() == before
    external = render_html_report(run_dir, tmp_path / "report-copy.html")
    assert external.is_file()
    assert verify_run_bundle(run_dir).valid
    with pytest.raises(ValueError, match="immutable RunBundle"):
        render_html_report(run_dir, run_dir / "report" / "copy.html")


def test_report_preserves_literal_feature_identifiers(tmp_path):
    from biostat_tool.specs import AnalysisSpec, CorrelationSpec, DatasetSpec, StudyDesignSpec

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,001\nS1,1\nS2,2\nS3,4\nS4,8\n", encoding="utf-8")
    b.write_text("id,NA\nS1,1\nS2,3\nS3,2\nS4,9\n", encoding="utf-8")
    spec = AnalysisSpec(
        schema_version="1.0",
        method="pearson",
        dataset_a=DatasetSpec("a.csv", sha256_file(a), "samples_rows", "metabolomics", "quantitative"),
        dataset_b=DatasetSpec("b.csv", sha256_file(b), "samples_rows", "metabolomics", "quantitative"),
        study_design=StudyDesignSpec("independent"),
        correlation=CorrelationSpec(minimum_pairwise_n=3),
    )
    completed = execute_prepared(prepare_analysis(spec, base_dir=tmp_path), acknowledge_warnings=True)
    run_dir = write_run_bundle(completed, tmp_path / "literal-id-run")
    results = (run_dir / "results" / "correlations.csv").read_text(encoding="utf-8")
    report = (run_dir / "report" / "report.html").read_text(encoding="utf-8")
    assert "001,NA" in results
    assert "<td>001</td>" in report
    assert "<td>NA</td>" in report
