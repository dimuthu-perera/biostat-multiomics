from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .analysis import (
    PEARSON_ALGORITHM_VERSION,
    SPEARMAN_ALGORITHM_VERSION,
    SPEARMAN_TAIL_TOLERANCE,
    CorrelationConfig,
    _compute_cross_correlation,
)
from .inspection import (
    DatasetDeclaration,
    InspectionReport,
    Severity,
    StudyDesignDeclaration,
    inspect_dataset,
    validate_declaration,
    validate_study_design,
)
from .io import align_samples


@dataclass(frozen=True)
class RunIssue:
    source: str
    severity: Severity
    code: str
    message: str

    @property
    def issue_id(self) -> str:
        return f"{self.source}:{self.code}"


@dataclass(frozen=True)
class RunAcknowledgement:
    run_fingerprint: str
    issue_ids: tuple[str, ...]


@dataclass
class InspectedRun:
    a: pd.DataFrame
    b: pd.DataFrame
    aligned_a: pd.DataFrame | None
    aligned_b: pd.DataFrame | None
    declaration_a: DatasetDeclaration
    declaration_b: DatasetDeclaration
    report_a: InspectionReport
    report_b: InspectionReport
    design: StudyDesignDeclaration
    config: CorrelationConfig
    alignment: dict[str, object] | None
    issues: list[RunIssue]
    fingerprint: str
    source_hashes: dict[str, str]
    import_settings: dict[str, object]

    @property
    def blocked(self) -> bool:
        return any(i.severity == Severity.BLOCKED for i in self.issues)

    @property
    def warning_issue_ids(self) -> list[str]:
        return [i.issue_id for i in self.issues if i.severity == Severity.WARNING]

    def issues_frame(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame([{"source": "run", "severity": "PASS", "code": "ok", "issue_id": "run:ok", "message": "No issues detected."}])
        return pd.DataFrame(
            [
                {
                    "source": i.source,
                    "severity": i.severity.value,
                    "code": i.code,
                    "issue_id": i.issue_id,
                    "message": i.message,
                }
                for i in self.issues
            ]
        )


@dataclass
class CompletedRun:
    inspected: InspectedRun
    results: pd.DataFrame
    family_metadata: dict[str, object]
    manifest: dict[str, object]


class ValidationError(RuntimeError):
    pass


class AcknowledgementRequired(ValidationError):
    pass


class NoTestablePairsError(ValidationError):
    pass


def _hash_text(h: "hashlib._Hash", text: str) -> None:
    data = text.encode("utf-8")
    h.update(len(data).to_bytes(8, "big"))
    h.update(data)


def _is_missing_scalar(v: object) -> bool:
    try:
        result = pd.isna(v)
    except Exception:
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _hash_scalar(h: "hashlib._Hash", v: object) -> None:
    if _is_missing_scalar(v):
        h.update(b"M")
    elif isinstance(v, (bool, np.bool_)):
        h.update(b"B1" if bool(v) else b"B0")
    elif isinstance(v, (int, np.integer)):
        h.update(b"I")
        _hash_text(h, str(int(v)))
    elif isinstance(v, np.floating):
        arr = np.asarray(v)
        if arr.dtype.itemsize > np.dtype(np.float64).itemsize:
            # Extended-precision floats are blocked from analysis, but fingerprint them
            # without first narrowing to binary64 so distinct invalid inputs do not
            # collapse to the same inspection identity.
            h.update(b"FX")
            _hash_text(h, str(arr.dtype))
            _hash_text(h, np.format_float_scientific(v, unique=True, trim="k"))
        else:
            h.update(b"F")
            _hash_text(h, float(v).hex())
    elif isinstance(v, float):
        h.update(b"F")
        _hash_text(h, float(v).hex())
    elif isinstance(v, (complex, np.complexfloating)):
        h.update(b"C")
        _hash_text(h, repr(complex(v)))
    elif isinstance(v, str):
        h.update(b"S")
        _hash_text(h, v)
    else:
        h.update(b"O")
        _hash_text(h, f"{type(v).__module__}.{type(v).__qualname__}:{repr(v)}")


def dataframe_fingerprint(df: pd.DataFrame) -> str:
    """Fingerprint exact labels and cell values without assuming the input is valid."""
    h = hashlib.sha256()
    _hash_text(h, "omics-correlation-dataframe-v0.2.4")
    h.update(int(df.shape[0]).to_bytes(8, "big", signed=False))
    h.update(int(df.shape[1]).to_bytes(8, "big", signed=False))
    for x in df.index:
        _hash_scalar(h, x)
    h.update(b"|columns|")
    for x in df.columns:
        _hash_scalar(h, x)
    h.update(b"|values|")
    for j in range(df.shape[1]):
        series = df.iloc[:, j]
        _hash_text(h, str(series.dtype))
        for v in series.array:
            _hash_scalar(h, v)
    return h.hexdigest()


def _run_fingerprint(
    a: pd.DataFrame,
    b: pd.DataFrame,
    decl_a: DatasetDeclaration,
    decl_b: DatasetDeclaration,
    design: StudyDesignDeclaration,
    config: CorrelationConfig,
    source_hashes: dict[str, str],
    import_settings: dict[str, object],
) -> str:
    payload = {
        "schema": "inspected-run-v0.2.4",
        "a": dataframe_fingerprint(a),
        "b": dataframe_fingerprint(b),
        "declaration_a": asdict(decl_a),
        "declaration_b": asdict(decl_b),
        "design": asdict(design),
        "config": asdict(config),
        "source_hashes": dict(sorted(source_hashes.items())),
        "import_settings": import_settings,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _convert_report_issues(source: str, report: InspectionReport) -> list[RunIssue]:
    return [RunIssue(source, issue.severity, issue.code, issue.message) for issue in report.issues]


def _inspect_with_size_guard(df: pd.DataFrame, declaration: DatasetDeclaration, config: CorrelationConfig) -> InspectionReport:
    pre_issues = validate_declaration(declaration)
    size_issues = []
    cells = int(df.shape[0] * df.shape[1])
    if df.shape[0] > config.max_samples:
        size_issues.append(
            RunIssue(
                "dataset",
                Severity.BLOCKED,
                "sample_count_limit",
                f"Dataset has {df.shape[0]:,} samples, exceeding scalar-engine cap {config.max_samples:,}.",
            )
        )
    if cells > config.max_input_cells_per_dataset:
        size_issues.append(
            RunIssue(
                "dataset",
                Severity.BLOCKED,
                "input_cell_limit",
                f"Dataset has {cells:,} sample×feature cells, exceeding scalar-engine cap {config.max_input_cells_per_dataset:,}.",
            )
        )
    if size_issues:
        from .inspection import InspectionIssue

        return InspectionReport(
            declaration,
            {"n_samples": int(df.shape[0]), "n_features": int(df.shape[1]), "n_cells": cells},
            pre_issues + [InspectionIssue(x.severity, x.code, x.message) for x in size_issues],
        )
    return inspect_dataset(df, declaration)


def inspect_run(
    a: pd.DataFrame,
    b: pd.DataFrame,
    declaration_a: DatasetDeclaration,
    declaration_b: DatasetDeclaration,
    design: StudyDesignDeclaration,
    config: CorrelationConfig,
    *,
    source_hashes: dict[str, str] | None = None,
    import_settings: dict[str, object] | None = None,
) -> InspectedRun:
    """Mandatory public validation/orchestration boundary before computation."""
    source_hashes = dict(source_hashes or {})
    import_settings = dict(import_settings or {})
    report_a = _inspect_with_size_guard(a, declaration_a, config)
    report_b = _inspect_with_size_guard(b, declaration_b, config)
    issues = _convert_report_issues("dataset_a", report_a) + _convert_report_issues("dataset_b", report_b)
    issues += [RunIssue("study_design", x.severity, x.code, x.message) for x in validate_study_design(design)]

    structural_codes = {
        "duplicate_sample_ids",
        "duplicate_feature_ids",
        "invalid_sample_ids",
        "invalid_feature_ids",
        "boolean_features_unsupported",
        "complex_features_unsupported",
        "extended_precision_float_unsupported",
        "non_numeric_features",
        "infinite_values",
        "empty_matrix",
        "sample_count_limit",
        "input_cell_limit",
    }
    structural_block = any(i.severity == Severity.BLOCKED and i.code in structural_codes for i in issues)
    aligned_a: pd.DataFrame | None = None
    aligned_b: pd.DataFrame | None = None
    alignment: dict[str, object] | None = None

    if not structural_block:
        try:
            aligned_a, aligned_b, alignment = align_samples(a, b)
        except ValueError as exc:
            issues.append(RunIssue("alignment", Severity.BLOCKED, "alignment_structure_error", str(exc)))
        else:
            if alignment["only_a"] or alignment["only_b"]:
                issues.append(
                    RunIssue(
                        "alignment",
                        Severity.WARNING,
                        "partial_sample_overlap",
                        f"Exact-ID alignment retained {alignment['n_common']} shared samples; "
                        f"{len(alignment['only_a'])} occur only in A and {len(alignment['only_b'])} only in B. Excluded IDs are recorded in the manifest.",
                    )
                )
            if int(alignment["n_common"]) < config.min_pairwise_n:
                issues.append(
                    RunIssue(
                        "alignment",
                        Severity.BLOCKED,
                        "insufficient_matched_samples",
                        f"Only {alignment['n_common']} exact sample IDs are shared, below min_pairwise_n={config.min_pairwise_n}.",
                    )
                )
            planned = int(aligned_a.shape[1] * aligned_b.shape[1])
            if planned > config.max_planned_tests:
                issues.append(
                    RunIssue(
                        "analysis",
                        Severity.BLOCKED,
                        "run_size_limit",
                        f"The requested run contains {planned:,} feature-pair tests, exceeding scalar-engine cap {config.max_planned_tests:,}.",
                    )
                )
            if aligned_a.isna().to_numpy().any() or aligned_b.isna().to_numpy().any():
                issues.append(
                    RunIssue(
                        "alignment",
                        Severity.WARNING,
                        "aligned_missingness_review",
                        "Missing values remain after exact matching. Different feature pairs may use different participant subsets; pairwise deletion does not correct LOD-related or otherwise informative missingness and may affect permutation exchangeability.",
                    )
                )
            if config.method == "spearman" and planned > 0:
                mc_floor = 1.0 / (config.spearman_permutations + 1.0)
                bh_rank1_at_005 = 0.05 / planned
                if mc_floor > bh_rank1_at_005:
                    issues.append(
                        RunIssue(
                            "analysis",
                            Severity.WARNING,
                            "spearman_mc_resolution_vs_family",
                            f"If any pair uses Monte Carlo Spearman inference, the configured floor is {mc_floor:.3g}. "
                            f"For {planned:,} planned hypotheses, the BH rank-1 threshold at FDR 0.05 is {bh_rank1_at_005:.3g}. "
                            "This limits discovery resolution; the tool will not report finer Monte Carlo p-values than the configured budget supports.",
                        )
                    )

    fingerprint = _run_fingerprint(a, b, declaration_a, declaration_b, design, config, source_hashes, import_settings)
    return InspectedRun(
        a=a,
        b=b,
        aligned_a=aligned_a,
        aligned_b=aligned_b,
        declaration_a=declaration_a,
        declaration_b=declaration_b,
        report_a=report_a,
        report_b=report_b,
        design=design,
        config=config,
        alignment=alignment,
        issues=issues,
        fingerprint=fingerprint,
        source_hashes=source_hashes,
        import_settings=import_settings,
    )


def create_acknowledgement(inspected: InspectedRun) -> RunAcknowledgement:
    """Create an acknowledgement bound to this exact inspected run fingerprint."""
    return RunAcknowledgement(inspected.fingerprint, tuple(sorted(inspected.warning_issue_ids)))


def _software_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "scipy", "gradio", "openpyxl"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    return versions


def analyze_validated_run(
    inspected: InspectedRun,
    *,
    acknowledgement: RunAcknowledgement | None = None,
) -> CompletedRun:
    """Analyze exactly the inspected run; validation is recomputed before inference."""
    fresh = inspect_run(
        inspected.a,
        inspected.b,
        inspected.declaration_a,
        inspected.declaration_b,
        inspected.design,
        inspected.config,
        source_hashes=inspected.source_hashes,
        import_settings=inspected.import_settings,
    )
    if fresh.fingerprint != inspected.fingerprint:
        raise ValidationError("The inspected data or run configuration changed after inspection; inspect again.")
    if fresh.blocked:
        blocked = [i.issue_id for i in fresh.issues if i.severity == Severity.BLOCKED]
        raise ValidationError(f"Run is blocked by validation issues: {blocked}")

    required = set(fresh.warning_issue_ids)
    if required:
        if acknowledgement is None:
            raise AcknowledgementRequired("This inspected run contains warnings that require acknowledgement.")
        if acknowledgement.run_fingerprint != fresh.fingerprint:
            raise AcknowledgementRequired("Acknowledgement belongs to a different inspected run fingerprint.")
        acknowledged = set(acknowledgement.issue_ids)
        missing = sorted(required - acknowledged)
        if missing:
            raise AcknowledgementRequired(f"Warnings require acknowledgement: {missing}")
    else:
        acknowledged = set()
        if acknowledgement is not None and acknowledgement.run_fingerprint != fresh.fingerprint:
            raise AcknowledgementRequired("Acknowledgement belongs to a different inspected run fingerprint.")

    if fresh.aligned_a is None or fresh.aligned_b is None or fresh.alignment is None:
        raise ValidationError("Validated aligned matrices are unavailable.")

    results, family = _compute_cross_correlation(fresh.aligned_a, fresh.aligned_b, fresh.config)
    testable = results["status"].isin(["ok", "ok_with_warning"])
    if int(testable.sum()) == 0:
        raise NoTestablePairsError("No feature pairs were testable under the configured minimum N and constant-pair rules.")

    content_hashes = {
        "dataset_a_dataframe_sha256": dataframe_fingerprint(fresh.a),
        "dataset_b_dataframe_sha256": dataframe_fingerprint(fresh.b),
        "aligned_a_dataframe_sha256": dataframe_fingerprint(fresh.aligned_a),
        "aligned_b_dataframe_sha256": dataframe_fingerprint(fresh.aligned_b),
    }
    manifest: dict[str, object] = {
        "schema_version": "0.2.4",
        "engine_version": "0.2.4",
        "run_fingerprint": fresh.fingerprint,
        "source_hashes": fresh.source_hashes,
        "content_hashes": content_hashes,
        "import_settings": fresh.import_settings,
        "declarations": {
            "dataset_a": asdict(fresh.declaration_a),
            "dataset_b": asdict(fresh.declaration_b),
        },
        "study_design": asdict(fresh.design),
        "config": asdict(fresh.config),
        "alignment": fresh.alignment,
        "issues": [
            {
                "issue_id": i.issue_id,
                "source": i.source,
                "severity": i.severity.value,
                "code": i.code,
                "message": i.message,
            }
            for i in fresh.issues
        ],
        "acknowledgement": None
        if acknowledgement is None
        else {
            "run_fingerprint": acknowledgement.run_fingerprint,
            "acknowledged_warning_issue_ids": sorted(set(acknowledgement.issue_ids) & required),
        },
        "inspection_metrics": {
            "dataset_a": fresh.report_a.metrics,
            "dataset_b": fresh.report_b.metrics,
        },
        "fdr_family": family,
        "software_versions": _software_versions(),
        "interpretation": {
            "correlation_is_unadjusted": True,
            "causal_claim_supported": False,
            "pairwise_complete_observations": True,
            "different_pairs_may_use_different_sample_subsets": True,
            "pairwise_deletion_corrects_informative_missingness": False,
            "automatic_imputation": False,
            "automatic_normalization_or_transformation": False,
            "bh_assumption_note": "BH control relies on its applicable independence/positive-dependence conditions; arbitrary dependence is not automatically covered.",
        },
    }

    if fresh.config.method == "spearman":
        exact_rows = results.loc[testable & results["p_value_method"].eq("spearman_exact_pairings_abs_tail")]
        mc_rows = results.loc[testable & results["p_value_method"].eq("spearman_monte_carlo_pairings_abs_tail_add_one")]
        asym_rows = results.loc[testable & results["p_value_method"].eq("scipy_spearmanr_asymptotic_N_ge_501_untied")]
        manifest["spearman_inference"] = {
            "algorithm_version": SPEARMAN_ALGORITHM_VERSION,
            "null": "independence/random pairing under exchangeability of independent observations",
            "two_sided_statistic": "abs(rho)",
            "tail_comparison": f"T_perm >= T_observed with numerical tolerance {SPEARMAN_TAIL_TOLERANCE:g}",
            "exact_policy": "N<=8: enumerate all positional pairings; repeated tied permutations retain probability mass",
            "monte_carlo_policy": "9<=N<=500, or any ties above 500: fixed-budget positional pairings with (b+1)/(B+1)",
            "asymptotic_policy": "untied N>=501 only",
            "random_seed": fresh.config.random_seed,
            "rng": "numpy.random.PCG64",
            "seed_derivation": "SHA-256 of algorithm version, sorted rank patterns, base seed, and B",
            "monte_carlo_permutations": fresh.config.spearman_permutations,
            "monte_carlo_floor": float(1 / (fresh.config.spearman_permutations + 1)),
            "exact_probability_unit_min_observed": None
            if exact_rows.empty
            else float(exact_rows["exact_probability_unit"].min()),
            "exact_min_attainable_p_min_observed": None
            if exact_rows.empty
            else float(exact_rows["exact_min_attainable_p"].min()),
            "n_exact_tests": int(len(exact_rows)),
            "n_monte_carlo_tests": int(len(mc_rows)),
            "n_asymptotic_tests": int(len(asym_rows)),
        }
    else:
        manifest["pearson_inference"] = {
            "algorithm_version": PEARSON_ALGORITHM_VERSION,
            "coefficient": "Pearson product-moment correlation after internal affine numerical stabilization only",
            "p_value": "SciPy pearsonr beta null on the stabilized values",
            "numerical_crosscheck": "independent centered-dot-product coefficient must agree within 1e-12",
            "note": "Internal affine stabilization preserves the mathematical correlation estimand and is not a biological data transformation.",
        }

    return CompletedRun(inspected=fresh, results=results, family_metadata=family, manifest=manifest)
