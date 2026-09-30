from __future__ import annotations

import copy
import math
import warnings
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from correlation_tool.analysis import (
    PEARSON_ALGORITHM_VERSION,
    SPEARMAN_ALGORITHM_VERSION,
    SPEARMAN_TAIL_TOLERANCE,
    AnalysisLimitError,
    CorrelationConfig,
    _SpearmanRunContext,
    _exact_abs_rho_null,
    _is_constant,
    _mc_abs_rho_null,
    _minimum_exact_abs_tail_p,
    _rank_vector,
    _rho_from_ranks,
    _stable_affine_vector,
    benjamini_hochberg,
)
from correlation_tool.workflow import (
    AcknowledgementRequired,
    CompletedRun,
    InspectedRun,
    NoTestablePairsError,
    RunAcknowledgement,
    ValidationError,
    _software_versions,
    dataframe_fingerprint,
    inspect_run,
)

REFERENCE_BACKEND_ID = "reference_scalar_v0.2.4"
OPTIMIZED_PEARSON_BACKEND_ID = "optimized_pearson_v0.4.1"
OPTIMIZED_SPEARMAN_BACKEND_ID = "optimized_spearman_v0.4.2"
OPTIMIZED_BACKEND_VERSION = "pearson-mask-grouping-v0.4.1+spearman-prerank-v0.4.2"
MAX_BROADCAST_VALUES_PER_BLOCK = 2_000_000
# Pairwise-missing Pearson is vectorized only when exact observed-sample masks
# are sufficiently reusable. Highly fragmented missingness deliberately falls
# back to the frozen scalar oracle rather than multiplying tiny SciPy calls.
MAX_PAIRWISE_MASK_CLASS_COMBINATIONS = 4_096
MIN_AVERAGE_PAIRS_PER_MASK_CLASS_COMBINATION = 4.0
MIN_PLANNED_PAIRS_FOR_FRAGMENTATION_FALLBACK = 1_024

# The equivalence contract is intentionally much tighter than the oracle's own
# 1e-12 coefficient cross-check.  These tolerances cover only last-bit changes
# caused by vectorized reduction order; status/inference metadata are exact.
COEFFICIENT_ATOL = 5e-15
COEFFICIENT_RTOL = 5e-14
PVALUE_ATOL = 5e-15
PVALUE_RTOL = 5e-14
QVALUE_ATOL = 5e-15
QVALUE_RTOL = 5e-14


class BackendEquivalenceError(RuntimeError):
    """Raised when an optimized run fails the frozen-reference equivalence contract."""


class OptimizedBackendUnsupported(RuntimeError):
    """Internal signal that the safe optimized subset does not cover this run."""


@dataclass(frozen=True)
class BackendEligibility:
    eligible: bool
    reason: str = ""


def _has_unsafe_exact_integer(df: pd.DataFrame) -> bool:
    for c in df.columns:
        for v in df[c].array:
            if pd.isna(v):
                continue
            if isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)) and abs(int(v)) > 2**53:
                return True
    return False


def _mask_class_count(df: pd.DataFrame) -> int:
    valid = ~df.isna().to_numpy()
    packed = np.packbits(valid.T, axis=1, bitorder="little")
    if packed.shape[0] == 0:
        return 0
    return int(np.unique(packed, axis=0).shape[0])


def optimized_pearson_eligibility(inspected: InspectedRun) -> BackendEligibility:
    if inspected.config.method != "pearson":
        return BackendEligibility(False, "optimized backend currently supports Pearson only")
    if inspected.aligned_a is None or inspected.aligned_b is None:
        return BackendEligibility(False, "validated aligned matrices are unavailable")
    a = inspected.aligned_a
    b = inspected.aligned_b
    if _has_unsafe_exact_integer(a):
        return BackendEligibility(False, "dataset A contains an exact integer above 2**53")
    if _has_unsafe_exact_integer(b):
        return BackendEligibility(False, "dataset B contains an exact integer above 2**53")

    has_missing = bool(a.isna().to_numpy().any() or b.isna().to_numpy().any())
    if has_missing:
        classes_a = _mask_class_count(a)
        classes_b = _mask_class_count(b)
        combinations = int(classes_a * classes_b)
        planned = int(a.shape[1] * b.shape[1])
        if combinations > MAX_PAIRWISE_MASK_CLASS_COMBINATIONS:
            return BackendEligibility(
                False,
                f"pairwise missingness is too fragmented for safe vectorized grouping "
                f"({combinations} mask-class combinations)",
            )
        if (
            planned >= MIN_PLANNED_PAIRS_FOR_FRAGMENTATION_FALLBACK
            and combinations > 0
            and planned / combinations < MIN_AVERAGE_PAIRS_PER_MASK_CLASS_COMBINATION
        ):
            return BackendEligibility(
                False,
                "pairwise missingness masks have insufficient reuse for the optimized grouping path",
            )
    return BackendEligibility(True, "")




def optimized_spearman_eligibility(inspected: InspectedRun) -> BackendEligibility:
    if inspected.config.method != "spearman":
        return BackendEligibility(False, "optimized Spearman backend requires method='spearman'")
    if inspected.aligned_a is None or inspected.aligned_b is None:
        return BackendEligibility(False, "validated aligned matrices are unavailable")
    if inspected.aligned_a.isna().to_numpy().any() or inspected.aligned_b.isna().to_numpy().any():
        return BackendEligibility(False, "optimized Spearman v0.4.2 supports complete aligned data only")
    return BackendEligibility(True, "")


def optimized_backend_eligibility(inspected: InspectedRun) -> BackendEligibility:
    if inspected.config.method == "pearson":
        return optimized_pearson_eligibility(inspected)
    if inspected.config.method == "spearman":
        return optimized_spearman_eligibility(inspected)
    return BackendEligibility(False, f"unsupported correlation method {inspected.config.method!r}")

# Backward-compatible name retained for v0.4.0 tests/downstream imports.
def optimized_complete_pearson_eligibility(inspected: InspectedRun) -> BackendEligibility:
    return optimized_pearson_eligibility(inspected)


def _revalidate(
    inspected: InspectedRun,
    acknowledgement: RunAcknowledgement | None,
) -> tuple[InspectedRun, set[str]]:
    """Re-run the frozen pre-inference validation without invoking its scalar kernel."""
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
        blocked = [i.issue_id for i in fresh.issues if i.severity.value == "BLOCKED"]
        raise ValidationError(f"Run is blocked by validation issues: {blocked}")

    required = set(fresh.warning_issue_ids)
    if required:
        if acknowledgement is None:
            raise AcknowledgementRequired("This inspected run contains warnings that require acknowledgement.")
        if acknowledgement.run_fingerprint != fresh.fingerprint:
            raise AcknowledgementRequired("Acknowledgement belongs to a different inspected run fingerprint.")
        missing = sorted(required - set(acknowledgement.issue_ids))
        if missing:
            raise AcknowledgementRequired(f"Warnings require acknowledgement: {missing}")
    elif acknowledgement is not None and acknowledgement.run_fingerprint != fresh.fingerprint:
        raise AcknowledgementRequired("Acknowledgement belongs to a different inspected run fingerprint.")

    if fresh.aligned_a is None or fresh.aligned_b is None or fresh.alignment is None:
        raise ValidationError("Validated aligned matrices are unavailable.")
    return fresh, required


def _block_shape(n: int, p: int, q: int) -> tuple[int, int]:
    max_pairs = max(1, MAX_BROADCAST_VALUES_PER_BLOCK // max(1, n))
    a_block = max(1, min(p, int(math.sqrt(max_pairs)) or 1))
    b_block = max(1, min(q, max_pairs // a_block))
    return a_block, b_block


def _stabilize_columns(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    constant = np.zeros(df.shape[1], dtype=bool)
    stable_rows: list[np.ndarray | None] = []
    for j, c in enumerate(df.columns):
        values = list(df[c].array)
        if _is_constant(values):
            constant[j] = True
            stable_rows.append(None)
            continue
        if any(isinstance(v, (int, np.integer)) and abs(int(v)) > 2**53 for v in values):
            raise OptimizedBackendUnsupported("Exact integer above 2**53 requires reference Pearson precision handling.")
        try:
            stable_rows.append(_stable_affine_vector(values))
        except Exception as exc:
            raise OptimizedBackendUnsupported(
                f"Frozen affine stabilization did not support a feature: {type(exc).__name__}: {exc}"
            ) from exc

    active = np.where(~constant)[0]
    if active.size:
        matrix = np.stack([stable_rows[i] for i in active], axis=0).astype(np.float64, copy=False)
    else:
        matrix = np.empty((0, len(df)), dtype=np.float64)
    return matrix, constant


def _optimized_complete_pearson_kernel(
    a: pd.DataFrame,
    b: pd.DataFrame,
    config: CorrelationConfig,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    if not a.index.equals(b.index):
        raise ValueError("Datasets are not aligned to identical sample IDs in identical order.")
    if a.isna().to_numpy().any() or b.isna().to_numpy().any():
        raise OptimizedBackendUnsupported("Missing values require pair-specific masks and the reference backend.")
    if config.method != "pearson":
        raise OptimizedBackendUnsupported("Optimized v0.4.0 kernel supports Pearson only.")

    n = int(len(a))
    planned = int(a.shape[1] * b.shape[1])
    if n < config.min_pairwise_n:
        # The frozen inspector normally blocks this before execution.
        raise ValidationError(f"Matched sample count {n} is below min_pairwise_n={config.min_pairwise_n}.")

    x_stable, const_a = _stabilize_columns(a)
    y_stable, const_b = _stabilize_columns(b)
    active_a = np.where(~const_a)[0]
    active_b = np.where(~const_b)[0]

    estimate = np.full((a.shape[1], b.shape[1]), np.nan, dtype=np.float64)
    pvalue = np.full_like(estimate, np.nan)

    if active_a.size and active_b.size:
        # Reference _pearson returns the centered-dot-product coefficient after
        # the same per-feature affine stabilization.  Precompute normalized
        # centered vectors once instead of once per feature pair.
        xc = x_stable - x_stable.mean(axis=1, keepdims=True)
        yc = y_stable - y_stable.mean(axis=1, keepdims=True)
        xnorm = np.linalg.norm(xc, axis=1)
        ynorm = np.linalg.norm(yc, axis=1)
        if (xnorm <= 0).any() or (ynorm <= 0).any() or not np.isfinite(xnorm).all() or not np.isfinite(ynorm).all():
            raise OptimizedBackendUnsupported("Optimized normalized vectors were not finite/nonconstant.")
        xn = xc / xnorm[:, None]
        yn = yc / ynorm[:, None]

        ablock, bblock = _block_shape(n, len(active_a), len(active_b))
        for ai in range(0, len(active_a), ablock):
            xa = x_stable[ai : ai + ablock]
            xna = xn[ai : ai + ablock]
            ia = active_a[ai : ai + ablock]
            for bj in range(0, len(active_b), bblock):
                yb = y_stable[bj : bj + bblock]
                ynb = yn[bj : bj + bblock]
                ib = active_b[bj : bj + bblock]
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    try:
                        scipy_res = stats.pearsonr(xa[:, None, :], yb[None, :, :], axis=-1)
                    except Exception as exc:
                        raise OptimizedBackendUnsupported(
                            f"Vectorized scipy pearsonr failed: {type(exc).__name__}: {exc}"
                        ) from exc
                if caught:
                    raise OptimizedBackendUnsupported(
                        "Vectorized scipy pearsonr emitted a warning after frozen affine stabilization: "
                        + "; ".join(str(w.message) for w in caught)
                    )
                # np.matmul may reduce in a different last-bit order than the
                # scalar np.dot used by the oracle; this is covered by the
                # explicit equivalence contract below.
                r_block = np.clip(xna @ ynb.T, -1.0, 1.0)
                scipy_r = np.asarray(scipy_res.statistic, dtype=np.float64)
                p_block = np.asarray(scipy_res.pvalue, dtype=np.float64)
                if (
                    not np.isfinite(r_block).all()
                    or not np.isfinite(scipy_r).all()
                    or not np.isfinite(p_block).all()
                    or np.max(np.abs(r_block - scipy_r)) > 1e-12
                    or (p_block < 0).any()
                    or (p_block > 1).any()
                ):
                    raise OptimizedBackendUnsupported(
                        "Optimized Pearson numerical cross-check failed; reference backend is required."
                    )
                estimate[np.ix_(ia, ib)] = r_block
                pvalue[np.ix_(ia, ib)] = p_block

    constant_pairs = const_a[:, None] | const_b[None, :]
    status = np.where(constant_pairs, "constant_pair", "ok")
    method_label = np.where(constant_pairs, "", "scipy_pearsonr_beta_null_after_affine_stabilization")

    feature_a = np.repeat(np.asarray([str(x) for x in a.columns], dtype=object), b.shape[1])
    feature_b = np.tile(np.asarray([str(x) for x in b.columns], dtype=object), a.shape[1])
    flat_status = status.reshape(-1)
    rows = pd.DataFrame(
        {
            "feature_a": feature_a,
            "feature_b": feature_b,
            "method": np.full(planned, "pearson", dtype=object),
            "estimate": estimate.reshape(-1),
            "p_value": pvalue.reshape(-1),
            "q_value": np.full(planned, np.nan, dtype=np.float64),
            "n_pairwise": np.full(planned, n, dtype=np.int64),
            "status": flat_status,
            "p_value_method": method_label.reshape(-1),
            "numerical_warning": np.full(planned, "", dtype=object),
            "permutations": np.full(planned, np.nan, dtype=np.float64),
            "extreme_count": np.full(planned, np.nan, dtype=np.float64),
            "p_resolution": np.full(planned, np.nan, dtype=np.float64),
            "exact_probability_unit": np.full(planned, np.nan, dtype=np.float64),
            "exact_min_attainable_p": np.full(planned, np.nan, dtype=np.float64),
            "monte_carlo_floor": np.full(planned, np.nan, dtype=np.float64),
            "tied_x": np.full(planned, np.nan, dtype=np.float64),
            "tied_y": np.full(planned, np.nan, dtype=np.float64),
        }
    )
    testable = rows["status"].eq("ok")
    m_eligible = int(testable.sum())
    if m_eligible:
        if rows.loc[testable, "p_value"].isna().any():
            raise OptimizedBackendUnsupported("Optimized testable result contains a missing p-value.")
        rows.loc[testable, "q_value"] = benjamini_hochberg(rows.loc[testable, "p_value"]).to_numpy()

    family: dict[str, int | str | float] = {
        "correction": "Benjamini-Hochberg",
        "family_scope": "all_eligible_AxB_pairs_for_prespecified_method",
        "method": "pearson",
        "m_planned": planned,
        "m_eligible": m_eligible,
        "m_tested": m_eligible,
        "m_failed": 0,
        "m_ineligible": int(planned - m_eligible),
    }
    return rows, family



def _mask_classes(df: pd.DataFrame) -> tuple[np.ndarray, list[np.ndarray]]:
    """Return unique packed nonmissing masks and feature indices for each mask class."""
    valid = ~df.isna().to_numpy()
    packed = np.packbits(valid.T, axis=1, bitorder="little")
    unique, inverse = np.unique(packed, axis=0, return_inverse=True)
    groups = [np.where(inverse == i)[0].astype(np.int64, copy=False) for i in range(len(unique))]
    return unique, groups


def _stabilized_subset_feature(
    df: pd.DataFrame,
    feature_index: int,
    sample_positions: np.ndarray,
    *,
    mask_key: bytes,
    cache: dict[tuple[bytes, int], tuple[bool, np.ndarray | None]],
) -> tuple[bool, np.ndarray | None]:
    key = (mask_key, int(feature_index))
    cached = cache.get(key)
    if cached is not None:
        return cached
    values = list(df.iloc[sample_positions, int(feature_index)].array)
    if any(
        isinstance(v, (int, np.integer))
        and not isinstance(v, (bool, np.bool_))
        and abs(int(v)) > 2**53
        for v in values
    ):
        raise OptimizedBackendUnsupported("Exact integer above 2**53 requires reference Pearson precision handling.")
    if _is_constant(values):
        out = (True, None)
    else:
        try:
            stable = _stable_affine_vector(values)
        except Exception as exc:
            raise OptimizedBackendUnsupported(
                f"Frozen affine stabilization did not support a pairwise-complete feature subset: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        out = (False, stable)
    cache[key] = out
    return out


def _vectorized_pearson_from_stable(
    x_stable: np.ndarray,
    y_stable: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorize frozen Pearson semantics for already-stabilized feature rows."""
    if x_stable.ndim != 2 or y_stable.ndim != 2 or x_stable.shape[1] != y_stable.shape[1]:
        raise ValueError("Stabilized Pearson matrices must be two-dimensional with identical sample counts.")
    n = int(x_stable.shape[1])
    out_r = np.empty((x_stable.shape[0], y_stable.shape[0]), dtype=np.float64)
    out_p = np.empty_like(out_r)
    if out_r.size == 0:
        return out_r, out_p

    xc = x_stable - x_stable.mean(axis=1, keepdims=True)
    yc = y_stable - y_stable.mean(axis=1, keepdims=True)
    xnorm = np.linalg.norm(xc, axis=1)
    ynorm = np.linalg.norm(yc, axis=1)
    if (xnorm <= 0).any() or (ynorm <= 0).any() or not np.isfinite(xnorm).all() or not np.isfinite(ynorm).all():
        raise OptimizedBackendUnsupported("Optimized normalized vectors were not finite/nonconstant.")
    xn = xc / xnorm[:, None]
    yn = yc / ynorm[:, None]

    ablock, bblock = _block_shape(n, x_stable.shape[0], y_stable.shape[0])
    for ai in range(0, x_stable.shape[0], ablock):
        xa = x_stable[ai : ai + ablock]
        xna = xn[ai : ai + ablock]
        for bj in range(0, y_stable.shape[0], bblock):
            yb = y_stable[bj : bj + bblock]
            ynb = yn[bj : bj + bblock]
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    scipy_res = stats.pearsonr(xa[:, None, :], yb[None, :, :], axis=-1)
                except Exception as exc:
                    raise OptimizedBackendUnsupported(
                        f"Vectorized scipy pearsonr failed: {type(exc).__name__}: {exc}"
                    ) from exc
            if caught:
                raise OptimizedBackendUnsupported(
                    "Vectorized scipy pearsonr emitted a warning after frozen affine stabilization: "
                    + "; ".join(str(w.message) for w in caught)
                )
            r_block = np.clip(xna @ ynb.T, -1.0, 1.0)
            scipy_r = np.asarray(scipy_res.statistic, dtype=np.float64)
            p_block = np.asarray(scipy_res.pvalue, dtype=np.float64)
            if (
                not np.isfinite(r_block).all()
                or not np.isfinite(scipy_r).all()
                or not np.isfinite(p_block).all()
                or np.max(np.abs(r_block - scipy_r)) > 1e-12
                or (p_block < 0).any()
                or (p_block > 1).any()
            ):
                raise OptimizedBackendUnsupported(
                    "Optimized Pearson numerical cross-check failed; reference backend is required."
                )
            out_r[ai : ai + len(xa), bj : bj + len(yb)] = r_block
            out_p[ai : ai + len(xa), bj : bj + len(yb)] = p_block
    return out_r, out_p


def _optimized_pairwise_missing_pearson_kernel(
    a: pd.DataFrame,
    b: pd.DataFrame,
    config: CorrelationConfig,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    """Pearson kernel grouping pairs by exact pairwise-complete sample masks.

    Every mask class is defined solely by the exact nonmissing positions in the
    aligned matrices.  Stabilization and constant checks are performed on each
    pairwise-complete subset, matching the frozen scalar oracle's order of
    operations.  BH is applied exactly once after all eligible raw p-values are
    assembled.
    """
    if not a.index.equals(b.index):
        raise ValueError("Datasets are not aligned to identical sample IDs in identical order.")
    if config.method != "pearson":
        raise OptimizedBackendUnsupported("Optimized v0.4.1 kernel supports Pearson only.")
    n_samples = int(len(a))
    if n_samples > config.max_samples:
        raise OptimizedBackendUnsupported("Matched sample count exceeds the frozen scalar-engine safety limit.")
    planned = int(a.shape[1] * b.shape[1])
    if planned > config.max_planned_tests:
        raise OptimizedBackendUnsupported("Planned test count exceeds the frozen scalar-engine safety limit.")

    unique_a, groups_a = _mask_classes(a)
    unique_b, groups_b = _mask_classes(b)
    combinations = int(len(groups_a) * len(groups_b))
    if combinations > MAX_PAIRWISE_MASK_CLASS_COMBINATIONS:
        raise OptimizedBackendUnsupported(
            f"pairwise missingness is too fragmented for safe vectorized grouping ({combinations} mask-class combinations)"
        )
    if (
        planned >= MIN_PLANNED_PAIRS_FOR_FRAGMENTATION_FALLBACK
        and combinations > 0
        and planned / combinations < MIN_AVERAGE_PAIRS_PER_MASK_CLASS_COMBINATION
    ):
        raise OptimizedBackendUnsupported(
            "pairwise missingness masks have insufficient reuse for the optimized grouping path"
        )

    p = int(a.shape[1])
    q = int(b.shape[1])
    estimate = np.full((p, q), np.nan, dtype=np.float64)
    pvalue = np.full((p, q), np.nan, dtype=np.float64)
    n_pairwise = np.zeros((p, q), dtype=np.int64)
    status = np.empty((p, q), dtype=object)
    status[:] = "uninitialized"
    method_label = np.empty((p, q), dtype=object)
    method_label[:] = ""

    cache_a: dict[tuple[bytes, int], tuple[bool, np.ndarray | None]] = {}
    cache_b: dict[tuple[bytes, int], tuple[bool, np.ndarray | None]] = {}

    for class_a, ia in enumerate(groups_a):
        for class_b, ib in enumerate(groups_b):
            packed_mask = np.bitwise_and(unique_a[class_a], unique_b[class_b])
            mask_key = packed_mask.tobytes()
            mask = np.unpackbits(packed_mask, bitorder="little")[:n_samples].astype(bool, copy=False)
            sample_positions = np.flatnonzero(mask)
            n_pair = int(sample_positions.size)
            ix = np.ix_(ia, ib)
            n_pairwise[ix] = n_pair

            if n_pair < config.min_pairwise_n:
                status[ix] = "insufficient_pairwise_n"
                continue

            const_a = np.zeros(len(ia), dtype=bool)
            stable_a: list[np.ndarray | None] = []
            for k, feature_index in enumerate(ia):
                is_const, stable = _stabilized_subset_feature(
                    a,
                    int(feature_index),
                    sample_positions,
                    mask_key=mask_key,
                    cache=cache_a,
                )
                const_a[k] = is_const
                stable_a.append(stable)

            const_b = np.zeros(len(ib), dtype=bool)
            stable_b: list[np.ndarray | None] = []
            for k, feature_index in enumerate(ib):
                is_const, stable = _stabilized_subset_feature(
                    b,
                    int(feature_index),
                    sample_positions,
                    mask_key=mask_key,
                    cache=cache_b,
                )
                const_b[k] = is_const
                stable_b.append(stable)

            constant_pairs = const_a[:, None] | const_b[None, :]
            local_status = np.where(constant_pairs, "constant_pair", "ok")
            status[ix] = local_status
            method_label[ix] = np.where(
                constant_pairs,
                "",
                "scipy_pearsonr_beta_null_after_affine_stabilization",
            )

            active_a_local = np.where(~const_a)[0]
            active_b_local = np.where(~const_b)[0]
            if active_a_local.size and active_b_local.size:
                x_stable = np.stack([stable_a[k] for k in active_a_local], axis=0).astype(np.float64, copy=False)
                y_stable = np.stack([stable_b[k] for k in active_b_local], axis=0).astype(np.float64, copy=False)
                r_block, p_block = _vectorized_pearson_from_stable(x_stable, y_stable)
                target_a = ia[active_a_local]
                target_b = ib[active_b_local]
                estimate[np.ix_(target_a, target_b)] = r_block
                pvalue[np.ix_(target_a, target_b)] = p_block

    if np.any(status == "uninitialized"):
        raise OptimizedBackendUnsupported("Optimized pairwise-mask grouping did not classify every planned pair.")

    feature_a = np.repeat(np.asarray([str(x) for x in a.columns], dtype=object), q)
    feature_b = np.tile(np.asarray([str(x) for x in b.columns], dtype=object), p)
    flat_status = status.reshape(-1)
    rows = pd.DataFrame(
        {
            "feature_a": feature_a,
            "feature_b": feature_b,
            "method": np.full(planned, "pearson", dtype=object),
            "estimate": estimate.reshape(-1),
            "p_value": pvalue.reshape(-1),
            "q_value": np.full(planned, np.nan, dtype=np.float64),
            "n_pairwise": n_pairwise.reshape(-1),
            "status": flat_status,
            "p_value_method": method_label.reshape(-1),
            "numerical_warning": np.full(planned, "", dtype=object),
            "permutations": np.full(planned, np.nan, dtype=np.float64),
            "extreme_count": np.full(planned, np.nan, dtype=np.float64),
            "p_resolution": np.full(planned, np.nan, dtype=np.float64),
            "exact_probability_unit": np.full(planned, np.nan, dtype=np.float64),
            "exact_min_attainable_p": np.full(planned, np.nan, dtype=np.float64),
            "monte_carlo_floor": np.full(planned, np.nan, dtype=np.float64),
            "tied_x": np.full(planned, np.nan, dtype=np.float64),
            "tied_y": np.full(planned, np.nan, dtype=np.float64),
        }
    )

    testable = rows["status"].eq("ok")
    m_eligible = int(testable.sum())
    if m_eligible:
        if rows.loc[testable, "p_value"].isna().any():
            raise OptimizedBackendUnsupported("Optimized testable result contains a missing p-value.")
        # Statistical invariant: exactly one global BH family after all pairwise
        # mask groups have been assembled. Never adjust within mask groups.
        rows.loc[testable, "q_value"] = benjamini_hochberg(rows.loc[testable, "p_value"]).to_numpy()

    family: dict[str, int | str | float] = {
        "correction": "Benjamini-Hochberg",
        "family_scope": "all_eligible_AxB_pairs_for_prespecified_method",
        "method": "pearson",
        "m_planned": planned,
        "m_eligible": m_eligible,
        "m_tested": m_eligible,
        "m_failed": 0,
        "m_ineligible": int(planned - m_eligible),
    }
    return rows, family


def _optimized_pearson_kernel(
    a: pd.DataFrame,
    b: pd.DataFrame,
    config: CorrelationConfig,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    if a.isna().to_numpy().any() or b.isna().to_numpy().any():
        return _optimized_pairwise_missing_pearson_kernel(a, b, config)
    return _optimized_complete_pearson_kernel(a, b, config)

def _optimized_complete_spearman_kernel(
    a: pd.DataFrame,
    b: pd.DataFrame,
    config: CorrelationConfig,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    """Complete-data Spearman kernel with feature ranks computed once.

    The inferential branch intentionally reuses the frozen oracle's private
    rank/null helpers. This changes only redundant ranking work; exact
    positional permutations, Monte Carlo PCG64 seeds, add-one p-values,
    asymptotic SciPy inference, and family-wide BH semantics are unchanged.
    """
    if not a.index.equals(b.index):
        raise ValueError("Datasets are not aligned to identical sample IDs in identical order.")
    if config.method != "spearman":
        raise OptimizedBackendUnsupported("Optimized v0.4.2 Spearman kernel requires method='spearman'.")
    if a.isna().to_numpy().any() or b.isna().to_numpy().any():
        raise OptimizedBackendUnsupported("Optimized Spearman v0.4.2 supports complete aligned data only.")
    n = int(len(a))
    planned = int(a.shape[1] * b.shape[1])
    if n > config.max_samples or planned > config.max_planned_tests:
        raise OptimizedBackendUnsupported("Run exceeds the frozen scalar-engine safety limits.")
    if n < config.min_pairwise_n:
        raise ValidationError(f"Matched sample count {n} is below min_pairwise_n={config.min_pairwise_n}.")

    def prepare(df: pd.DataFrame):
        ranks: list[np.ndarray | None] = []
        constants: list[bool] = []
        ties: list[bool] = []
        for c in df.columns:
            values = list(df[c].array)
            is_const = _is_constant(values)
            constants.append(is_const)
            if is_const:
                ranks.append(None)
                ties.append(False)
                continue
            try:
                r = _rank_vector(values)
            except Exception as exc:
                raise OptimizedBackendUnsupported(
                    f"Frozen Spearman ranking did not support a feature: {type(exc).__name__}: {exc}"
                ) from exc
            ranks.append(r)
            ties.append(bool(np.unique(r).size < n))
        return ranks, np.asarray(constants, dtype=bool), np.asarray(ties, dtype=bool)

    ranks_a, const_a, ties_a = prepare(a)
    ranks_b, const_b, ties_b = prepare(b)
    ctx = _SpearmanRunContext(config)
    rows: list[dict[str, object]] = []

    for ia, feature_a in enumerate(a.columns):
        for ib, feature_b in enumerate(b.columns):
            row: dict[str, object] = {
                "feature_a": str(feature_a),
                "feature_b": str(feature_b),
                "method": "spearman",
                "estimate": np.nan,
                "p_value": np.nan,
                "q_value": np.nan,
                "n_pairwise": n,
                "status": "ok",
                "p_value_method": "",
                "numerical_warning": "",
                "permutations": np.nan,
                "extreme_count": np.nan,
                "p_resolution": np.nan,
                "exact_probability_unit": np.nan,
                "exact_min_attainable_p": np.nan,
                "monte_carlo_floor": np.nan,
                "tied_x": np.nan,
                "tied_y": np.nan,
            }
            if const_a[ia] or const_b[ib]:
                row["status"] = "constant_pair"
                rows.append(row)
                continue
            rx = ranks_a[ia]
            ry = ranks_b[ib]
            assert rx is not None and ry is not None
            rho = _rho_from_ranks(rx, ry)
            if not math.isfinite(rho):
                raise OptimizedBackendUnsupported("Spearman rank correlation produced a nonfinite coefficient.")
            rho = float(np.clip(rho, -1.0, 1.0))
            tied_x = bool(ties_a[ia])
            tied_y = bool(ties_b[ib])
            obs = abs(rho)
            row["estimate"] = rho
            row["tied_x"] = tied_x
            row["tied_y"] = tied_y

            if n <= config.spearman_exact_max_n:
                null = _exact_abs_rho_null(rx, ry, ctx)
                left = int(np.searchsorted(null, obs - SPEARMAN_TAIL_TOLERANCE, side="left"))
                extreme = int(null.size - left)
                row.update({
                    "p_value": float(extreme / null.size),
                    "p_value_method": "spearman_exact_pairings_abs_tail",
                    "permutations": int(null.size),
                    "extreme_count": extreme,
                    "exact_probability_unit": float(1 / null.size),
                    "exact_min_attainable_p": _minimum_exact_abs_tail_p(null),
                })
            else:
                use_mc = n < config.spearman_asymptotic_min_n or tied_x or tied_y
                if use_mc:
                    if n > config.max_spearman_permutation_n:
                        raise AnalysisLimitError(
                            f"Spearman permutation inference is required for this pair (N={n}, ties={tied_x or tied_y}) "
                            f"but the scalar engine caps permutation N at {config.max_spearman_permutation_n}."
                        )
                    null = _mc_abs_rho_null(rx, ry, ctx=ctx)
                    left = int(np.searchsorted(null, obs - SPEARMAN_TAIL_TOLERANCE, side="left"))
                    extreme = int(null.size - left)
                    floor = float(1 / (null.size + 1))
                    row.update({
                        "p_value": float((extreme + 1) / (null.size + 1)),
                        "p_value_method": "spearman_monte_carlo_pairings_abs_tail_add_one",
                        "permutations": int(null.size),
                        "extreme_count": extreme,
                        "p_resolution": floor,
                        "monte_carlo_floor": floor,
                    })
                else:
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        res = stats.spearmanr(rx, ry)
                    p = float(res.pvalue)
                    if caught or not math.isfinite(p) or not (0.0 <= p <= 1.0):
                        raise OptimizedBackendUnsupported(
                            "; ".join(str(w.message) for w in caught) or "Spearman returned an invalid p-value."
                        )
                    row.update({
                        "p_value": p,
                        "p_value_method": "scipy_spearmanr_asymptotic_N_ge_501_untied",
                    })
            rows.append(row)

    result = pd.DataFrame(rows)
    testable = result["status"].isin(["ok", "ok_with_warning"])
    m_eligible = int(testable.sum())
    if m_eligible:
        if result.loc[testable, "p_value"].isna().any():
            raise OptimizedBackendUnsupported("Optimized Spearman testable result contains a missing p-value.")
        result.loc[testable, "q_value"] = benjamini_hochberg(result.loc[testable, "p_value"]).to_numpy()
    family: dict[str, int | str | float] = {
        "correction": "Benjamini-Hochberg",
        "family_scope": "all_eligible_AxB_pairs_for_prespecified_method",
        "method": "spearman",
        "m_planned": planned,
        "m_eligible": m_eligible,
        "m_tested": m_eligible,
        "m_failed": 0,
        "m_ineligible": int(planned - m_eligible),
        "spearman_exact_null_groups_used": len(ctx.exact_groups_used),
        "spearman_mc_null_groups_used": len(ctx.mc_groups_used),
        "spearman_total_null_evaluations_reserved": ctx.total_null_evaluations,
        "spearman_null_cache_bytes_reserved": ctx.cache_bytes,
    }
    return result, family


def _pearson_semantic_manifest(
    fresh: InspectedRun,
    acknowledgement: RunAcknowledgement | None,
    required: set[str],
    results: pd.DataFrame,
    family: dict[str, object],
) -> dict[str, object]:
    """Build the frozen-v0.2.4 semantic manifest without running its scalar pair loop."""
    return {
        "schema_version": "0.2.4",
        "engine_version": "0.2.4",
        "run_fingerprint": fresh.fingerprint,
        "source_hashes": copy.deepcopy(fresh.source_hashes),
        "content_hashes": {
            "dataset_a_dataframe_sha256": dataframe_fingerprint(fresh.a),
            "dataset_b_dataframe_sha256": dataframe_fingerprint(fresh.b),
            "aligned_a_dataframe_sha256": dataframe_fingerprint(fresh.aligned_a),
            "aligned_b_dataframe_sha256": dataframe_fingerprint(fresh.aligned_b),
        },
        "import_settings": copy.deepcopy(fresh.import_settings),
        "declarations": {
            "dataset_a": asdict(fresh.declaration_a),
            "dataset_b": asdict(fresh.declaration_b),
        },
        "study_design": asdict(fresh.design),
        "config": asdict(fresh.config),
        "alignment": copy.deepcopy(fresh.alignment),
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
            "dataset_a": copy.deepcopy(fresh.report_a.metrics),
            "dataset_b": copy.deepcopy(fresh.report_b.metrics),
        },
        "fdr_family": copy.deepcopy(family),
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
        "pearson_inference": {
            "algorithm_version": PEARSON_ALGORITHM_VERSION,
            "coefficient": "Pearson product-moment correlation after internal affine numerical stabilization only",
            "p_value": "SciPy pearsonr beta null on the stabilized values",
            "numerical_crosscheck": "independent centered-dot-product coefficient must agree within 1e-12",
            "note": "Internal affine stabilization preserves the mathematical correlation estimand and is not a biological data transformation.",
        },
    }


def _spearman_semantic_manifest(
    fresh: InspectedRun,
    acknowledgement: RunAcknowledgement | None,
    required: set[str],
    results: pd.DataFrame,
    family: dict[str, object],
) -> dict[str, object]:
    manifest = _pearson_semantic_manifest(fresh, acknowledgement, required, results, family)
    manifest.pop("pearson_inference", None)
    testable = results["status"].isin(["ok", "ok_with_warning"])
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
        "exact_probability_unit_min_observed": None if exact_rows.empty else float(exact_rows["exact_probability_unit"].min()),
        "exact_min_attainable_p_min_observed": None if exact_rows.empty else float(exact_rows["exact_min_attainable_p"].min()),
        "n_exact_tests": int(len(exact_rows)),
        "n_monte_carlo_tests": int(len(mc_rows)),
        "n_asymptotic_tests": int(len(asym_rows)),
    }
    return manifest


def analyze_optimized_spearman(
    inspected: InspectedRun,
    *,
    acknowledgement: RunAcknowledgement | None,
) -> CompletedRun:
    fresh, required = _revalidate(inspected, acknowledgement)
    eligibility = optimized_spearman_eligibility(fresh)
    if not eligibility.eligible:
        raise OptimizedBackendUnsupported(eligibility.reason)
    assert fresh.aligned_a is not None and fresh.aligned_b is not None
    results, family = _optimized_complete_spearman_kernel(fresh.aligned_a, fresh.aligned_b, fresh.config)
    if int(results["status"].isin(["ok", "ok_with_warning"]).sum()) == 0:
        raise NoTestablePairsError("No feature pairs were testable under the configured minimum N and constant-pair rules.")
    manifest = _spearman_semantic_manifest(fresh, acknowledgement, required, results, family)
    return CompletedRun(inspected=fresh, results=results, family_metadata=family, manifest=manifest)


def analyze_optimized_correlation(
    inspected: InspectedRun,
    *,
    acknowledgement: RunAcknowledgement | None,
) -> CompletedRun:
    if inspected.config.method == "pearson":
        return analyze_optimized_pearson(inspected, acknowledgement=acknowledgement)
    if inspected.config.method == "spearman":
        return analyze_optimized_spearman(inspected, acknowledgement=acknowledgement)
    raise OptimizedBackendUnsupported(f"Unsupported optimized method {inspected.config.method!r}")


def analyze_optimized_pearson(
    inspected: InspectedRun,
    *,
    acknowledgement: RunAcknowledgement | None,
) -> CompletedRun:
    fresh, required = _revalidate(inspected, acknowledgement)
    eligibility = optimized_pearson_eligibility(fresh)
    if not eligibility.eligible:
        raise OptimizedBackendUnsupported(eligibility.reason)
    assert fresh.aligned_a is not None and fresh.aligned_b is not None
    results, family = _optimized_pearson_kernel(fresh.aligned_a, fresh.aligned_b, fresh.config)
    if int(results["status"].isin(["ok", "ok_with_warning"]).sum()) == 0:
        raise NoTestablePairsError("No feature pairs were testable under the configured minimum N and constant-pair rules.")
    manifest = _pearson_semantic_manifest(fresh, acknowledgement, required, results, family)
    return CompletedRun(inspected=fresh, results=results, family_metadata=family, manifest=manifest)


# Backward-compatible v0.4.0 name.
def analyze_optimized_complete_pearson(
    inspected: InspectedRun,
    *,
    acknowledgement: RunAcknowledgement | None,
) -> CompletedRun:
    return analyze_optimized_pearson(inspected, acknowledgement=acknowledgement)


def compare_to_reference(optimized: CompletedRun, reference: CompletedRun) -> dict[str, Any]:
    """Apply the explicit optimized-vs-oracle equivalence contract."""
    left = optimized.results.reset_index(drop=True)
    right = reference.results.reset_index(drop=True)
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        raise BackendEquivalenceError("Result table shape/columns differ from frozen reference.")

    exact_columns = [
        "feature_a",
        "feature_b",
        "method",
        "n_pairwise",
        "status",
        "p_value_method",
        "numerical_warning",
    ]
    for name in exact_columns:
        if not left[name].equals(right[name]):
            raise BackendEquivalenceError(f"Exact result column {name!r} differs from frozen reference.")

    # These metadata fields are NaN for Pearson but are still part of the table contract.
    metadata_numeric = [
        "permutations",
        "extreme_count",
        "p_resolution",
        "exact_probability_unit",
        "exact_min_attainable_p",
        "monte_carlo_floor",
        "tied_x",
        "tied_y",
    ]
    for name in metadata_numeric:
        if not np.array_equal(
            left[name].to_numpy(dtype=float), right[name].to_numpy(dtype=float), equal_nan=True
        ):
            raise BackendEquivalenceError(f"Inference metadata column {name!r} differs from frozen reference.")

    tolerances = {
        "estimate": (COEFFICIENT_ATOL, COEFFICIENT_RTOL),
        "p_value": (PVALUE_ATOL, PVALUE_RTOL),
        "q_value": (QVALUE_ATOL, QVALUE_RTOL),
    }
    maxima: dict[str, float] = {}
    for name, (atol, rtol) in tolerances.items():
        x = left[name].to_numpy(dtype=float)
        y = right[name].to_numpy(dtype=float)
        if not np.allclose(x, y, atol=atol, rtol=rtol, equal_nan=True):
            diff = np.abs(x - y)
            finite = np.isfinite(diff)
            max_diff = float(np.max(diff[finite])) if finite.any() else float("nan")
            raise BackendEquivalenceError(
                f"Numeric result column {name!r} exceeds equivalence tolerance; max abs diff={max_diff!r}, "
                f"atol={atol}, rtol={rtol}."
            )
        diff = np.abs(x - y)
        finite = np.isfinite(diff)
        maxima[name] = float(np.max(diff[finite])) if finite.any() else 0.0

    if optimized.family_metadata != reference.family_metadata:
        raise BackendEquivalenceError("Global multiple-testing family metadata differs from frozen reference.")
    if optimized.inspected.fingerprint != reference.inspected.fingerprint:
        raise BackendEquivalenceError("Run fingerprint differs from frozen reference.")
    if optimized.manifest.get("alignment") != reference.manifest.get("alignment"):
        raise BackendEquivalenceError("Alignment provenance differs from frozen reference.")
    if optimized.manifest.get("fdr_family") != reference.manifest.get("fdr_family"):
        raise BackendEquivalenceError("FDR-family provenance differs from frozen reference.")
    inference_key = "pearson_inference" if str(left["method"].iloc[0]) == "pearson" else "spearman_inference"
    if optimized.manifest.get(inference_key) != reference.manifest.get(inference_key):
        raise BackendEquivalenceError(f"{inference_key} policy provenance differs from frozen reference.")

    optimized_backend = (
        OPTIMIZED_PEARSON_BACKEND_ID if str(left["method"].iloc[0]) == "pearson" else OPTIMIZED_SPEARMAN_BACKEND_ID
    )
    return {
        "status": "passed",
        "reference_backend": REFERENCE_BACKEND_ID,
        "optimized_backend": optimized_backend,
        "rows_compared": int(len(left)),
        "max_abs_difference": maxima,
        "tolerances": {
            "estimate": {"atol": COEFFICIENT_ATOL, "rtol": COEFFICIENT_RTOL},
            "p_value": {"atol": PVALUE_ATOL, "rtol": PVALUE_RTOL},
            "q_value": {"atol": QVALUE_ATOL, "rtol": QVALUE_RTOL},
        },
        "exact_columns": exact_columns + metadata_numeric,
        "global_bh_family_exact": True,
    }
