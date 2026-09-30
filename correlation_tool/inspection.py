from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np
import pandas as pd


class Severity(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class DatasetDeclaration:
    data_type: str
    preprocessing: str
    name: str = "dataset"
    preprocessing_details: str = ""


@dataclass(frozen=True)
class StudyDesignDeclaration:
    observation_structure: Literal["unknown", "independent", "dependent_or_clustered"] = "unknown"
    notes: str = ""


@dataclass(frozen=True)
class InspectionIssue:
    severity: Severity
    code: str
    message: str


@dataclass
class InspectionReport:
    declaration: DatasetDeclaration
    metrics: dict[str, Any]
    issues: list[InspectionIssue] = field(default_factory=list)

    @property
    def status(self) -> Severity:
        if any(i.severity == Severity.BLOCKED for i in self.issues):
            return Severity.BLOCKED
        if any(i.severity == Severity.WARNING for i in self.issues):
            return Severity.WARNING
        return Severity.PASS

    @property
    def is_blocked(self) -> bool:
        return self.status == Severity.BLOCKED

    def issues_frame(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame([{"severity": "PASS", "code": "ok", "message": "No blocking or warning conditions detected."}])
        return pd.DataFrame([{"severity": i.severity.value, "code": i.code, "message": i.message} for i in self.issues])


ALLOWED_PREPROCESSING: dict[str, set[str]] = {
    "rna_seq": {"vst", "rlog", "log_cpm", "other_transformed"},
    "metagenomics": {"clr", "other_transformed"},
    "16s": {"clr", "other_transformed"},
    "metabolomics": {"quantitative", "normalized", "log_transformed", "scaled", "other_transformed"},
    "proteomics": {"quantitative", "normalized", "log_transformed", "scaled", "other_transformed"},
    "generic": {"declared_numeric", "other_transformed"},
}

UNSUPPORTED_EXPLICIT_STATES = {
    "rna_seq": {"raw_counts", "normalized_counts", "tpm", "fpkm", "cpm"},
    "metagenomics": {"raw_counts", "normalized_counts", "relative_abundance"},
    "16s": {"raw_counts", "normalized_counts", "relative_abundance"},
}


def validate_declaration(declaration: DatasetDeclaration) -> list[InspectionIssue]:
    issues: list[InspectionIssue] = []
    data_type = declaration.data_type.strip().lower()
    preprocessing = declaration.preprocessing.strip().lower()
    if data_type not in ALLOWED_PREPROCESSING:
        return [InspectionIssue(Severity.BLOCKED, "unsupported_data_type", f"Unsupported data type declaration: {declaration.data_type!r}.")]
    if preprocessing in UNSUPPORTED_EXPLICIT_STATES.get(data_type, set()):
        issues.append(
            InspectionIssue(
                Severity.BLOCKED,
                "unsupported_preprocessing_state",
                f"{data_type} preprocessing state {preprocessing!r} is outside this tool's supported Pearson/Spearman scope.",
            )
        )
    elif preprocessing not in ALLOWED_PREPROCESSING[data_type]:
        issues.append(
            InspectionIssue(
                Severity.BLOCKED,
                "invalid_preprocessing_declaration",
                f"Preprocessing state {preprocessing!r} is not an allowed declaration for {data_type}. "
                f"Allowed states: {', '.join(sorted(ALLOWED_PREPROCESSING[data_type]))}.",
            )
        )
    if preprocessing == "other_transformed" and not declaration.preprocessing_details.strip():
        issues.append(
            InspectionIssue(
                Severity.BLOCKED,
                "transformation_details_required",
                "'other_transformed' requires a substantive description of the transformation and normalization history.",
            )
        )
    if data_type in {"metagenomics", "16s"} and preprocessing == "clr" and not declaration.preprocessing_details.strip():
        issues.append(
            InspectionIssue(
                Severity.BLOCKED,
                "clr_details_required",
                "CLR input requires preprocessing details describing zero handling and the reference feature set used for the log-ratio coordinates.",
            )
        )
    return issues


def validate_study_design(design: StudyDesignDeclaration) -> list[InspectionIssue]:
    if design.observation_structure == "unknown":
        return [InspectionIssue(Severity.BLOCKED, "study_design_unknown", "Declare whether observations are independent before inferential correlation analysis.")]
    if design.observation_structure == "dependent_or_clustered":
        return [
            InspectionIssue(
                Severity.BLOCKED,
                "dependent_observations_unsupported",
                "Ordinary Pearson/Spearman p-values are not supported for declared repeated, clustered, familial, technical-replicate, or time-dependent observations in v0.2.",
            )
        ]
    if design.observation_structure != "independent":
        return [InspectionIssue(Severity.BLOCKED, "invalid_study_design", f"Unsupported observation structure: {design.observation_structure!r}.")]
    return [
        InspectionIssue(
            Severity.WARNING,
            "unadjusted_association",
            "This analysis is unadjusted for covariates or batch/group composition; correlation does not establish causation or an adjusted biological association.",
        )
    ]




def _underlying_numpy_dtype(dtype: object) -> np.dtype | None:
    candidate = getattr(dtype, "numpy_dtype", None)
    try:
        return np.dtype(candidate if candidate is not None else dtype)
    except (TypeError, ValueError):
        return None


def _is_extended_float_dtype(dtype: object) -> bool:
    nd = _underlying_numpy_dtype(dtype)
    return bool(nd is not None and nd.kind == "f" and nd.itemsize > np.dtype(np.float64).itemsize)

def _safe_fraction(mask: np.ndarray) -> float:
    return float(mask.mean()) if mask.size else float("nan")


def _numeric_values(df: pd.DataFrame) -> np.ndarray:
    vals: list[float] = []
    for col in df.columns:
        for v in df[col].array:
            if pd.isna(v):
                continue
            vals.append(float(v))
    return np.asarray(vals, dtype=float)


def _relative_abundance_signature(df: pd.DataFrame) -> dict[str, Any]:
    # Diagnostic only. Missing sample cells are excluded from total-based classification.
    sample_sums: list[float] = []
    complete_rows = 0
    finite_values: list[float] = []
    for _, row in df.iterrows():
        values = []
        complete = True
        for v in row.array:
            if pd.isna(v):
                complete = False
                continue
            fv = float(v)
            if not np.isfinite(fv):
                complete = False
                continue
            values.append(fv)
            finite_values.append(fv)
        if complete and values:
            complete_rows += 1
            sample_sums.append(float(sum(values)))
    if not finite_values:
        return {
            "relative_abundance_like": False,
            "relative_scale": None,
            "median_complete_sample_sum": np.nan,
            "complete_sample_fraction": 0.0,
            "fraction_complete_samples_near_1": 0.0,
            "fraction_complete_samples_near_100": 0.0,
        }
    fv = np.asarray(finite_values, dtype=float)
    nonnegative = bool(np.min(fv) >= 0)
    frac_in_0_1 = _safe_fraction((fv >= 0) & (fv <= 1.0 + 1e-12))
    frac_in_0_100 = _safe_fraction((fv >= 0) & (fv <= 100.0 + 1e-9))
    sums = np.asarray(sample_sums, dtype=float)
    if sums.size:
        near1 = np.abs(sums - 1.0) <= 0.02
        near100 = np.abs(sums - 100.0) / 100.0 <= 0.02
        frac_near1 = float(near1.mean())
        frac_near100 = float(near100.mean())
        median_sum = float(np.median(sums))
    else:
        frac_near1 = frac_near100 = 0.0
        median_sum = np.nan
    looks_fraction = nonnegative and frac_in_0_1 >= 0.98 and sums.size > 0 and frac_near1 >= 0.80
    looks_percent = nonnegative and frac_in_0_100 >= 0.98 and sums.size > 0 and frac_near100 >= 0.80
    scale = "fraction_0_to_1" if looks_fraction else "percent_0_to_100" if looks_percent else None
    return {
        "relative_abundance_like": bool(looks_fraction or looks_percent),
        "relative_scale": scale,
        "median_complete_sample_sum": median_sum,
        "complete_sample_fraction": float(complete_rows / len(df)) if len(df) else 0.0,
        "fraction_complete_samples_near_1": frac_near1,
        "fraction_complete_samples_near_100": frac_near100,
    }


def inspect_dataset(
    df: pd.DataFrame,
    declaration: DatasetDeclaration,
    *,
    high_missing_threshold: float = 0.50,
    count_integer_fraction: float = 0.98,
) -> InspectionReport:
    """Inspect a sample×feature matrix without normalization, imputation, or transformation."""
    issues = validate_declaration(declaration)
    if df.empty:
        issues.append(InspectionIssue(Severity.BLOCKED, "empty_matrix", "The matrix contains no data."))
        return InspectionReport(declaration, {"n_samples": len(df), "n_features": df.shape[1]}, issues)

    if not df.index.is_unique:
        issues.append(InspectionIssue(Severity.BLOCKED, "duplicate_sample_ids", "Duplicate sample IDs detected."))
    if not df.columns.is_unique:
        issues.append(InspectionIssue(Severity.BLOCKED, "duplicate_feature_ids", "Duplicate feature IDs detected."))
    if any(not isinstance(x, str) or x == "" for x in df.index):
        issues.append(InspectionIssue(Severity.BLOCKED, "invalid_sample_ids", "Sample IDs must be nonempty strings."))
    if any(not isinstance(x, str) or x == "" for x in df.columns):
        issues.append(InspectionIssue(Severity.BLOCKED, "invalid_feature_ids", "Feature IDs must be nonempty strings."))

    # Do not index columns by duplicate labels or continue through structurally invalid
    # identifiers. Return a structured blocked report instead of raising incidentally.
    if any(i.code in {"duplicate_sample_ids", "duplicate_feature_ids", "invalid_sample_ids", "invalid_feature_ids"} for i in issues):
        return InspectionReport(
            declaration,
            {"n_samples": int(df.shape[0]), "n_features": int(df.shape[1])},
            issues,
        )

    whitespace_sample_ids = sum(isinstance(x, str) and x != x.strip() for x in df.index)
    if whitespace_sample_ids:
        issues.append(
            InspectionIssue(
                Severity.WARNING,
                "sample_id_whitespace",
                f"{whitespace_sample_ids} sample IDs contain leading/trailing whitespace. IDs are matched exactly and are never trimmed automatically.",
            )
        )

    non_numeric: list[str] = []
    boolean_cols: list[str] = []
    complex_cols: list[str] = []
    extended_float_cols: list[str] = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s.dtype):
            boolean_cols.append(str(c))
        elif pd.api.types.is_complex_dtype(s.dtype):
            complex_cols.append(str(c))
        elif _is_extended_float_dtype(s.dtype):
            extended_float_cols.append(str(c))
        elif not pd.api.types.is_numeric_dtype(s.dtype):
            non_numeric.append(str(c))
    if boolean_cols:
        issues.append(InspectionIssue(Severity.BLOCKED, "boolean_features_unsupported", f"Boolean features are unsupported: {', '.join(boolean_cols[:8])}."))
    if complex_cols:
        issues.append(InspectionIssue(Severity.BLOCKED, "complex_features_unsupported", f"Complex-valued features are unsupported: {', '.join(complex_cols[:8])}."))
    if extended_float_cols:
        issues.append(
            InspectionIssue(
                Severity.BLOCKED,
                "extended_precision_float_unsupported",
                "Floating-point dtypes wider than binary64 are unsupported because silently narrowing them can change ranks, Pearson variation, and run identity. "
                f"Affected features: {', '.join(extended_float_cols[:8])}.",
            )
        )
    if non_numeric:
        issues.append(InspectionIssue(Severity.BLOCKED, "non_numeric_features", f"Nonnumeric features detected: {', '.join(non_numeric[:8])}."))
    if boolean_cols or complex_cols or extended_float_cols or non_numeric:
        return InspectionReport(declaration, {"n_samples": int(df.shape[0]), "n_features": int(df.shape[1])}, issues)

    finite_values: list[float] = []
    missing_count = 0
    inf_count = 0
    integer_like = 0
    finite_count = 0
    negative_count = 0
    zero_count = 0
    constant_features: list[str] = []
    high_missing_features: list[str] = []

    for col in df.columns:
        observed: list[object] = []
        for v in df[col].array:
            if pd.isna(v):
                missing_count += 1
                continue
            if isinstance(v, (bool, np.bool_)) or isinstance(v, (complex, np.complexfloating)):
                continue
            fv = float(v)
            if not np.isfinite(fv):
                inf_count += 1
                continue
            observed.append(v)
            finite_values.append(fv)
            finite_count += 1
            zero_count += int(fv == 0.0)
            negative_count += int(fv < 0.0)
            is_int_like = bool(np.isclose(fv, np.round(fv), rtol=0.0, atol=1e-12))
            integer_like += int(is_int_like)
        if len(observed) < 2 or len(set(observed)) <= 1:
            constant_features.append(str(col))
        if float(df[col].isna().mean()) > high_missing_threshold:
            high_missing_features.append(str(col))

    if inf_count:
        issues.append(InspectionIssue(Severity.BLOCKED, "infinite_values", f"The matrix contains {inf_count} infinite values; infinities are never treated as missing."))
    if missing_count:
        issues.append(
            InspectionIssue(
                Severity.WARNING,
                "missing_values_present",
                f"The matrix contains {missing_count} missing cells. Correlations use pairwise complete observations, so different feature pairs may use different participant subsets. No imputation is performed, and informative/LOD-related missingness is not corrected by pairwise deletion.",
            )
        )
    if constant_features:
        issues.append(InspectionIssue(Severity.WARNING, "constant_features", f"{len(constant_features)} features are constant or have fewer than two observed finite values."))
    if high_missing_features:
        issues.append(InspectionIssue(Severity.WARNING, "high_missingness", f"{len(high_missing_features)} features exceed {high_missing_threshold:.0%} missingness."))

    fv = np.asarray(finite_values, dtype=float)
    integer_fraction = float(integer_like / finite_count) if finite_count else np.nan
    minimum = float(np.min(fv)) if finite_count else np.nan
    maximum = float(np.max(fv)) if finite_count else np.nan
    nonnegative = bool(finite_count and minimum >= 0)
    count_like = bool(nonnegative and integer_fraction >= count_integer_fraction)
    relsig = _relative_abundance_signature(df)

    data_type = declaration.data_type.strip().lower()
    preprocessing = declaration.preprocessing.strip().lower()
    if data_type == "rna_seq" and preprocessing in ALLOWED_PREPROCESSING.get("rna_seq", set()) and count_like:
        issues.append(
            InspectionIssue(
                Severity.WARNING,
                "rna_transformation_mismatch",
                f"The matrix is declared {preprocessing!r}, but {integer_fraction:.1%} of observed values are nonnegative and integer-like. This is only a numerical count-like signal; verify the intended transformed matrix.",
            )
        )
    if data_type in {"metagenomics", "16s"} and preprocessing in {"clr", "other_transformed"}:
        if preprocessing == "clr":
            issues.append(
                InspectionIssue(
                    Severity.WARNING,
                    "clr_relative_coordinate_interpretation",
                    "CLR values are relative log-ratio coordinates defined by the declared reference feature set and upstream zero handling. Correlations are not absolute-abundance effects, microbial interactions, causal relationships, or automatically covariate-adjusted associations.",
                )
            )
        if relsig["relative_abundance_like"]:
            issues.append(
                InspectionIssue(
                    Severity.WARNING,
                    "microbiome_relative_abundance_mismatch",
                    f"The transformed microbiome declaration conflicts with a relative-abundance-like numerical signature ({relsig['relative_scale']}). Verify the uploaded matrix.",
                )
            )
        if count_like:
            issues.append(
                InspectionIssue(
                    Severity.WARNING,
                    "microbiome_count_like_mismatch",
                    f"The transformed microbiome declaration conflicts with a count-like numerical signature ({integer_fraction:.1%} integer-like, nonnegative values). Verify the uploaded matrix.",
                )
            )
        if preprocessing == "clr" and finite_count and minimum >= 0:
            issues.append(
                InspectionIssue(
                    Severity.WARNING,
                    "clr_nonnegative_matrix",
                    "All observed CLR values are nonnegative. Legitimate CLR subsets can violate a zero-sum check, so this is not proof of invalid preprocessing, but the upload should be reviewed.",
                )
            )

    total_cells = int(df.shape[0] * df.shape[1])
    metrics = {
        "n_samples": int(df.shape[0]),
        "n_features": int(df.shape[1]),
        "missing_fraction": float(missing_count / total_cells) if total_cells else np.nan,
        "zero_fraction_of_finite": float(zero_count / finite_count) if finite_count else np.nan,
        "negative_fraction_of_finite": float(negative_count / finite_count) if finite_count else np.nan,
        "integer_fraction_of_finite": integer_fraction,
        "minimum_finite": minimum,
        "maximum_finite": maximum,
        "constant_feature_count": len(constant_features),
        "high_missing_feature_count": len(high_missing_features),
        "count_like_signature": count_like,
        **relsig,
    }
    return InspectionReport(declaration, metrics, issues)
