from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
from typing import Mapping

import pandas as pd

import correlation_tool
from correlation_tool import (
    AcknowledgementRequired,
    CompletedRun,
    CorrelationConfig,
    DatasetDeclaration,
    InspectedRun,
    RunAcknowledgement,
    StudyDesignDeclaration,
    analyze_validated_run,
    inspect_run,
    load_matrix,
)

from ..specs import ANALYSIS_TYPE, AnalysisSpec
from ..policy import STATISTICAL_POLICY_VERSION, correlation_policy_advisories
from .base import AnalysisModule, AnalysisSummary, CompletedAnalysis, EngineIdentity, ExecutionOptions, PreparedAnalysis
from .correlation_backends import (
    OPTIMIZED_PEARSON_BACKEND_ID,
    OPTIMIZED_SPEARMAN_BACKEND_ID,
    REFERENCE_BACKEND_ID,
    OptimizedBackendUnsupported,
    analyze_optimized_correlation,
    compare_to_reference,
    optimized_backend_eligibility,
)


class InputIntegrityError(RuntimeError):
    """Raised when an input file does not match the AnalysisSpec identity."""


def _resolve_path(logical_path: str, base_dir: Path, override: str | Path | None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    p = Path(logical_path).expanduser()
    return (p if p.is_absolute() else base_dir / p).resolve()


def _snapshot_input(source: Path, destination: Path) -> tuple[str, int]:
    """Copy one input into a private snapshot while hashing the exact copied bytes."""
    h = hashlib.sha256()
    total = 0
    with source.open("rb") as src, destination.open("xb") as dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
            dst.write(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def _import_settings(spec: AnalysisSpec) -> dict[str, object]:
    return {
        "analysis_spec_schema": spec.schema_version,
        "dataset_a_orientation": spec.dataset_a.orientation,
        "dataset_b_orientation": spec.dataset_b.orientation,
        "dataset_a_measurement_missing_tokens": list(spec.dataset_a.missing_tokens),
        "dataset_b_measurement_missing_tokens": list(spec.dataset_b.missing_tokens),
        "identifier_policy": "literal_nonempty_text_exact_match_no_trimming_no_fuzzy_matching",
        "xlsx_formula_policy": "reject_all_formula_cells_during_raw_ooxml_preflight",
        "xlsx_merge_policy": "reject_all_merged_cells_during_raw_ooxml_preflight",
        "xlsx_relationship_policy": "single_standard_xl_worksheets_target_resolved_and_preflighted_before_openpyxl",
        "xlsx_extent_policy": "stream_exact_referenced_worksheet_xml_enforce_actual_coordinates_ignore_untrusted_dimension_metadata",
        "xlsx_archive_budget_policy": "bounded_total_and_per_entry_uncompressed_bytes_before_openpyxl",
        "source_byte_identity_policy": "parse_private_snapshot_hashed_while_copying_and_match_spec_before_import",
    }


def _inspection_document(inspected: InspectedRun) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "run_fingerprint": inspected.fingerprint,
        "blocked": inspected.blocked,
        # Completed provenance must not share nested mutable structures with
        # the executed oracle state.  Caller-visible document mutations must
        # be unable to rewrite the semantic authority used for verification.
        "metrics": {
            "dataset_a": copy.deepcopy(inspected.report_a.metrics),
            "dataset_b": copy.deepcopy(inspected.report_b.metrics),
        },
        "issues": [
            {
                "issue_id": issue.issue_id,
                "source": issue.source,
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
            }
            for issue in inspected.issues
        ],
    }


def _alignment_document(inspected: InspectedRun) -> dict[str, object]:
    payload = copy.deepcopy(inspected.alignment or {})
    return {"schema_version": "1.0", **payload}


def _correlation_result_schema(results: pd.DataFrame) -> dict[str, object]:
    meanings = {
        "feature_a": "Feature identifier from dataset A.",
        "feature_b": "Feature identifier from dataset B.",
        "method": "Prespecified correlation method for this run.",
        "estimate": "Pearson r or Spearman rho, depending on method.",
        "p_value": "Raw two-sided inferential p-value under the recorded method-specific null.",
        "q_value": "Benjamini-Hochberg adjusted p-value within the recorded global eligible A×B family.",
        "n_pairwise": "Number of exact matched samples with finite values for this feature pair.",
        "status": "Pair-level eligibility/numerical status.",
        "p_value_method": "Exact method label used to obtain the p-value.",
        "numerical_warning": "Recorded numerical warning, if any.",
        "permutations": "Number of permutations used for permutation-based Spearman inference, when applicable.",
        "extreme_count": "Monte Carlo extreme-count numerator before add-one correction, when applicable.",
        "p_resolution": "Recorded p-value resolution metadata for the inference branch, when applicable.",
        "exact_probability_unit": "Probability unit of exact positional enumeration, when applicable.",
        "exact_min_attainable_p": "Minimum attainable absolute-tail exact p-value for the cached exact null, when applicable.",
        "monte_carlo_floor": "Minimum Monte Carlo p-value 1/(B+1), when applicable.",
        "tied_x": "Whether the pairwise-complete dataset A values contain ties for Spearman inference.",
        "tied_y": "Whether the pairwise-complete dataset B values contain ties for Spearman inference.",
    }
    cols: list[dict[str, object]] = []
    for name in results.columns:
        dtype = results[name].dtype
        if pd.api.types.is_bool_dtype(dtype):
            storage_type = "boolean"
        elif pd.api.types.is_integer_dtype(dtype):
            storage_type = "integer"
        elif pd.api.types.is_float_dtype(dtype):
            storage_type = "number"
        else:
            storage_type = "string"
        cols.append(
            {
                "name": name,
                "storage_type": storage_type,
                "nullable": bool(results[name].isna().any()),
                "meaning": meanings.get(name, "Correlation result field."),
            }
        )
    return {
        "schema_version": "1.0",
        "analysis_type": ANALYSIS_TYPE,
        "table_id": "correlations",
        "path": "results/correlations.csv",
        "format": "text/csv",
        "row_count": int(len(results)),
        "primary_key": ["feature_a", "feature_b", "method"],
        "columns": cols,
    }


class CorrelationAnalysisModule(AnalysisModule):
    analysis_type = ANALYSIS_TYPE
    module_id = "correlation"
    module_version = "1.3"

    def validate_spec(self, spec: AnalysisSpec) -> None:
        if spec.analysis_type != self.analysis_type:
            raise ValueError(
                f"Correlation module cannot execute analysis type {spec.analysis_type!r}; expected {self.analysis_type!r}."
            )

    def inspect(
        self,
        spec: AnalysisSpec,
        *,
        base_dir: str | Path | None = None,
        path_overrides: Mapping[str, str | Path] | None = None,
    ) -> PreparedAnalysis:
        self.validate_spec(spec)
        base = Path(base_dir or ".").resolve()
        overrides = dict(path_overrides or {})
        unknown = set(overrides) - {"dataset_a", "dataset_b"}
        if unknown:
            raise ValueError(f"Unknown path override(s): {', '.join(sorted(unknown))}")

        paths = {
            "dataset_a": _resolve_path(spec.dataset_a.path, base, overrides.get("dataset_a")),
            "dataset_b": _resolve_path(spec.dataset_b.path, base, overrides.get("dataset_b")),
        }
        for key, path in paths.items():
            if not path.is_file():
                raise InputIntegrityError(f"{key} file does not exist: {path}")

        expected = {
            "dataset_a": spec.dataset_a.sha256.lower(),
            "dataset_b": spec.dataset_b.sha256.lower(),
        }
        source_identity: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(prefix="biostat_input_snapshot_") as snapshot_root_text:
            snapshot_root = Path(snapshot_root_text)
            snapshot_paths: dict[str, Path] = {}
            for key in ("dataset_a", "dataset_b"):
                source = paths[key]
                snapshot = snapshot_root / f"{key}{source.suffix.lower()}"
                observed_hash, observed_bytes = _snapshot_input(source, snapshot)
                if observed_hash.lower() != expected[key]:
                    raise InputIntegrityError(
                        f"{key} SHA-256 mismatch: AnalysisSpec expects {expected[key]}, observed {observed_hash}."
                    )
                source_identity[key] = {"sha256": observed_hash.lower(), "bytes": int(observed_bytes)}
                snapshot_paths[key] = snapshot

            a = load_matrix(
                snapshot_paths["dataset_a"],
                spec.dataset_a.orientation,
                missing_tokens=spec.dataset_a.missing_tokens,
            )
            b = load_matrix(
                snapshot_paths["dataset_b"],
                spec.dataset_b.orientation,
                missing_tokens=spec.dataset_b.missing_tokens,
            )

        decl_a = DatasetDeclaration(
            spec.dataset_a.data_type,
            spec.dataset_a.preprocessing,
            "Dataset A",
            spec.dataset_a.preprocessing_details,
        )
        decl_b = DatasetDeclaration(
            spec.dataset_b.data_type,
            spec.dataset_b.preprocessing,
            "Dataset B",
            spec.dataset_b.preprocessing_details,
        )
        design = StudyDesignDeclaration(spec.study_design.observation_structure, spec.study_design.notes)
        config = CorrelationConfig(
            method=spec.method,
            min_pairwise_n=spec.correlation.minimum_pairwise_n,
            spearman_permutations=spec.correlation.spearman_permutations,
            random_seed=spec.correlation.random_seed,
        )
        inspected = inspect_run(
            a,
            b,
            decl_a,
            decl_b,
            design,
            config,
            source_hashes={
                "dataset_a_sha256": str(source_identity["dataset_a"]["sha256"]),
                "dataset_b_sha256": str(source_identity["dataset_b"]["sha256"]),
            },
            import_settings=_import_settings(spec),
        )
        policy_advisories = tuple(x.to_dict() for x in correlation_policy_advisories(spec))
        return PreparedAnalysis(
            analysis_type=self.analysis_type,
            module_id=self.module_id,
            module_version=self.module_version,
            spec=spec,
            module_state=inspected,
            resolved_paths=paths,
            requested_spec_sha256=spec.sha256(),
            source_identity=source_identity,
            run_fingerprint=inspected.fingerprint,
            blocked=inspected.blocked,
            warning_issue_ids=tuple(inspected.warning_issue_ids),
            inspection_document=_inspection_document(inspected),
            alignment_document=_alignment_document(inspected),
            statistical_policy_version=STATISTICAL_POLICY_VERSION,
            policy_advisories=policy_advisories,
        )

    @staticmethod
    def _acknowledgement_from_spec(prepared: PreparedAnalysis, inspected: InspectedRun) -> RunAcknowledgement | None:
        review = prepared.spec.review
        if not review.inspected_run_fingerprint and not review.acknowledged_warning_issue_ids:
            return None
        if review.inspected_run_fingerprint != inspected.fingerprint:
            raise AcknowledgementRequired(
                "AnalysisSpec review metadata belongs to a different inspected run fingerprint; inspect and acknowledge again."
            )
        if set(review.acknowledged_warning_issue_ids) != set(inspected.warning_issue_ids):
            raise AcknowledgementRequired(
                "AnalysisSpec review warning IDs do not exactly match the current inspected warning set; inspect and acknowledge again."
            )
        return RunAcknowledgement(
            run_fingerprint=review.inspected_run_fingerprint,
            issue_ids=tuple(review.acknowledged_warning_issue_ids),
        )

    def run(
        self,
        prepared: PreparedAnalysis,
        *,
        acknowledge_warnings: bool = False,
        execution: ExecutionOptions | None = None,
    ) -> CompletedAnalysis:
        if prepared.analysis_type != self.analysis_type or prepared.module_id != self.module_id:
            raise ValueError("Prepared analysis belongs to a different AnalysisModule.")
        if prepared.module_version != self.module_version:
            raise ValueError(
                f"Prepared analysis module version {prepared.module_version!r} does not match active {self.module_version!r}."
            )
        if not isinstance(prepared.module_state, InspectedRun):
            raise TypeError("Correlation module received an incompatible prepared state.")
        inspected = prepared.module_state
        execution = execution or ExecutionOptions()

        acknowledgement = self._acknowledgement_from_spec(prepared, inspected)
        if acknowledge_warnings:
            acknowledgement = RunAcknowledgement(
                inspected.fingerprint,
                tuple(sorted(inspected.warning_issue_ids)),
            )

        requested_backend = execution.backend
        actual_backend = REFERENCE_BACKEND_ID
        fallback_reason = ""
        reference_verification: dict[str, object] = {
            "requested": bool(execution.verify_against_reference),
            "status": "not_requested",
        }

        eligibility = optimized_backend_eligibility(inspected)
        use_optimized = requested_backend in {"optimized", "auto"} and eligibility.eligible
        if use_optimized:
            try:
                oracle_run = analyze_optimized_correlation(inspected, acknowledgement=acknowledgement)
            except OptimizedBackendUnsupported as exc:
                fallback_reason = str(exc)
                oracle_run = analyze_validated_run(inspected, acknowledgement=acknowledgement)
                if execution.verify_against_reference:
                    reference_verification = {
                        "requested": True,
                        "status": "not_applicable_fallback_to_reference",
                        "reference_backend": REFERENCE_BACKEND_ID,
                    }
            else:
                actual_backend = (OPTIMIZED_PEARSON_BACKEND_ID if inspected.config.method == "pearson" else OPTIMIZED_SPEARMAN_BACKEND_ID)
                if execution.verify_against_reference:
                    reference_run = analyze_validated_run(inspected, acknowledgement=acknowledgement)
                    reference_verification = compare_to_reference(oracle_run, reference_run)
                    reference_verification["requested"] = True
        else:
            if requested_backend in {"optimized", "auto"} and not eligibility.eligible:
                fallback_reason = eligibility.reason
            oracle_run = analyze_validated_run(inspected, acknowledgement=acknowledgement)
            if execution.verify_against_reference:
                reference_verification = {
                    "requested": True,
                    "status": "not_applicable_reference_backend",
                    "reference_backend": REFERENCE_BACKEND_ID,
                }

        effective_spec = prepared.spec
        if acknowledgement is not None:
            effective_spec = prepared.spec.with_review(
                acknowledgement.run_fingerprint,
                acknowledgement.issue_ids,
            )
        summary = self.summarize(oracle_run, effective_spec)
        execution_metadata = {
            "requested_backend": requested_backend,
            "actual_backend": actual_backend,
            "optimized_subset": "pearson_complete_or_reusable_pairwise_missing_masks_and_spearman_complete_data_prerank",
            "fallback_reason": fallback_reason,
            "reference_verification": copy.deepcopy(reference_verification),
        }
        return CompletedAnalysis(
            analysis_type=self.analysis_type,
            module_id=self.module_id,
            module_version=self.module_version,
            engine_identity=EngineIdentity("omics-correlation-tool", correlation_tool.__version__),
            requested_spec=prepared.spec,
            effective_spec=effective_spec,
            module_result=oracle_run,
            primary_results=oracle_run.results,
            result_schema=self.result_schema(oracle_run),
            summary=summary,
            inspection_document=_inspection_document(oracle_run.inspected),
            alignment_document=_alignment_document(oracle_run.inspected),
            statistical_policy_version=prepared.statistical_policy_version,
            policy_advisories=tuple(copy.deepcopy(prepared.policy_advisories)),
            module_provenance={
                "oracle": {
                    "name": "omics-correlation-tool",
                    "version": correlation_tool.__version__,
                    "manifest": copy.deepcopy(oracle_run.manifest),
                }
            },
            execution_metadata=execution_metadata,
            resolved_paths=dict(prepared.resolved_paths),
            requested_spec_sha256=prepared.requested_spec_sha256,
            source_identity=copy.deepcopy(prepared.source_identity),
            run_fingerprint=oracle_run.inspected.fingerprint,
        )

    def summarize(self, module_result: object, effective_spec: AnalysisSpec) -> AnalysisSummary:
        if not isinstance(module_result, CompletedRun):
            raise TypeError("Correlation module summarize() requires a correlation CompletedRun.")
        results = module_result.results
        testable = int(results["status"].isin(["ok", "ok_with_warning"]).sum())
        return AnalysisSummary(
            primary_table_id="correlations",
            primary_table_path="results/correlations.csv",
            result_schema_path="results/schema.json",
            row_count=int(len(results)),
            testable_rows=testable,
            method=effective_spec.method,
            family_metadata=copy.deepcopy(dict(module_result.family_metadata)),
            interpretation=copy.deepcopy(dict(module_result.manifest.get("interpretation", {}))),
        )

    def result_schema(self, module_result: object) -> Mapping[str, object]:
        if not isinstance(module_result, CompletedRun):
            raise TypeError("Correlation module result_schema() requires a correlation CompletedRun.")
        return _correlation_result_schema(module_result.results)


CORRELATION_MODULE = CorrelationAnalysisModule()
