from __future__ import annotations

from correlation_tool import sha256_file

from biostat_tool import web
from biostat_tool.examples import get_example
from biostat_tool.specs import (
    AnalysisSpec,
    CorrelationSpec,
    DatasetSpec,
    OutputSpec,
    ReviewSpec,
    StudyDesignSpec,
)


def _spec_for_example(key: str, *, preprocessing_a: str | None = None, data_type_a: str | None = None) -> AnalysisSpec:
    ex = get_example(key)
    a = ex["a"]
    b = ex["b"]
    return AnalysisSpec(
        schema_version="1.0",
        method=ex.get("method", "spearman"),
        dataset_a=DatasetSpec(
            path="dataset_a.csv",
            sha256=sha256_file(a["path"]),
            orientation="samples_rows",
            data_type=data_type_a or a["data_type"],
            preprocessing=preprocessing_a or a["preprocessing"],
            preprocessing_details=a.get("details", ""),
        ),
        dataset_b=DatasetSpec(
            path="dataset_b.csv",
            sha256=sha256_file(b["path"]),
            orientation="samples_rows",
            data_type=b["data_type"],
            preprocessing=b["preprocessing"],
            preprocessing_details=b.get("details", ""),
        ),
        study_design=StudyDesignSpec(ex.get("design", "independent"), "Synthetic example test."),
        correlation=CorrelationSpec(),
        review=ReviewSpec(),
        outputs=OutputSpec("runs"),
    )


def test_rc17_matching_bundled_example_metadata_has_no_teaching_mismatch():
    spec = _spec_for_example("16s_generic")
    assert web._synthetic_example_metadata_issues(spec) == ()


def test_rc17_exact_bundled_bytes_with_changed_preprocessing_are_flagged():
    spec = _spec_for_example("16s_generic", preprocessing_a="other_transformed")
    issues = web._synthetic_example_metadata_issues(spec)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["source"] == "synthetic_example"
    assert issue["severity"] == "WARNING"
    assert issue["issue_id"] == "synthetic_example:bundled_example_a_declaration_mismatch"
    assert "Centered log-ratio (CLR)" in issue["message"]
    assert "Other transformed values" in issue["message"]
    assert "will not silently replace" in issue["message"]


def test_rc17_guardrail_is_byte_identity_scoped_not_generic_user_data():
    spec = _spec_for_example("16s_generic", preprocessing_a="other_transformed")
    # One-bit-different identity represents a non-packaged user dataset, even if
    # the declared modality/settings resemble the bundled example.
    altered_hash = ("0" if spec.dataset_a.sha256[0] != "0" else "1") + spec.dataset_a.sha256[1:]
    user_spec = AnalysisSpec(
        schema_version=spec.schema_version,
        method=spec.method,
        dataset_a=DatasetSpec(
            path=spec.dataset_a.path,
            sha256=altered_hash,
            orientation=spec.dataset_a.orientation,
            data_type=spec.dataset_a.data_type,
            preprocessing=spec.dataset_a.preprocessing,
            preprocessing_details=spec.dataset_a.preprocessing_details,
            missing_tokens=spec.dataset_a.missing_tokens,
        ),
        dataset_b=spec.dataset_b,
        study_design=spec.study_design,
        correlation=spec.correlation,
        review=spec.review,
        outputs=spec.outputs,
    )
    assert web._synthetic_example_metadata_issues(user_spec) == ()


def test_rc17_inspection_surfaces_example_mismatch_and_requires_acknowledgement():
    ex = get_example("16s_generic")
    result = web.inspect_callback(
        ex["a"]["path"], ex["b"]["path"],
        "16s", "other_transformed", ex["a"]["details"], "samples_rows",
        "generic", "declared_numeric", ex["b"]["details"], "samples_rows",
        "independent", "Synthetic example test.", "spearman", 10, 9999, 20260915,
        "NA,N/A,NaN,nan", "NA,N/A,NaN,nan",
    )
    banner, issues, state = result[0], result[1], result[5]
    assert "Data readiness: WARNING" in banner
    rows = issues.loc[issues["code"].eq("bundled_example_a_declaration_mismatch")]
    assert len(rows) == 1
    assert rows.iloc[0]["source"] == "synthetic_example"
    assert state.platform_warning_issue_ids == ("synthetic_example:bundled_example_a_declaration_mismatch",)
    assert any(x["code"] == "bundled_example_a_declaration_mismatch" for x in state.prepared.policy_advisories)

    blocked_without_ack = web.analyze_callback(state, False)[0]
    assert "Warning acknowledgement required" in blocked_without_ack
