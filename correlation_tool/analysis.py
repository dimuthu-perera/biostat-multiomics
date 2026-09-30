from __future__ import annotations

import hashlib
import itertools
import math
import numbers
import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

Method = Literal["pearson", "spearman"]
SPEARMAN_TAIL_TOLERANCE = 1e-12
SPEARMAN_ALGORITHM_VERSION = "pairings-abs-tail-v0.2.1"
PEARSON_ALGORITHM_VERSION = "stable-affine-scipy-beta-v0.2.1"


class AnalysisLimitError(RuntimeError):
    """Raised when a requested run exceeds a documented scalar-engine safety limit."""


class NumericalAnalysisError(RuntimeError):
    """Raised when unresolved numerical failures prevent family-wide inference."""


@dataclass(frozen=True)
class CorrelationConfig:
    method: Method = "spearman"
    min_pairwise_n: int = 3
    # The public reference engine deliberately fixes the supported Spearman inference policy. These remain
    # fields for transparent manifests but are not tunable within the supported API.
    spearman_exact_max_n: int = 8
    spearman_permutations: int = 9_999
    spearman_asymptotic_min_n: int = 501
    random_seed: int = 20_260_915
    max_planned_tests: int = 250_000
    max_samples: int = 10_000
    max_input_cells_per_dataset: int = 5_000_000
    max_spearman_exact_null_groups: int = 64
    max_spearman_mc_null_groups: int = 100
    max_spearman_permutation_n: int = 5_000
    max_spearman_total_null_evaluations: int = 5_000_000
    max_spearman_null_cache_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.method not in {"pearson", "spearman"}:
            raise ValueError(f"Unsupported method: {self.method!r}")
        integer_fields = (
            "min_pairwise_n",
            "spearman_exact_max_n",
            "spearman_permutations",
            "spearman_asymptotic_min_n",
            "random_seed",
            "max_planned_tests",
            "max_samples",
            "max_input_cells_per_dataset",
            "max_spearman_exact_null_groups",
            "max_spearman_mc_null_groups",
            "max_spearman_permutation_n",
            "max_spearman_total_null_evaluations",
            "max_spearman_null_cache_bytes",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, numbers.Integral):
                raise ValueError(f"{name} must be an integer.")
        if self.min_pairwise_n < 3:
            raise ValueError("min_pairwise_n must be at least 3.")
        if self.spearman_exact_max_n != 8 or self.spearman_asymptotic_min_n != 501:
            raise ValueError(
                "The supported reference policy is exact N<=8, Monte Carlo for 9<=N<=500 or any ties, "
                "and asymptotic inference only for untied N>=501. Threshold overrides are not supported."
            )
        if not 99 <= self.spearman_permutations <= 100_000:
            raise ValueError("spearman_permutations must be between 99 and 100,000 in the scalar reference engine.")
        for name in (
            "max_planned_tests",
            "max_samples",
            "max_input_cells_per_dataset",
            "max_spearman_exact_null_groups",
            "max_spearman_mc_null_groups",
            "max_spearman_total_null_evaluations",
            "max_spearman_null_cache_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")
        if self.max_spearman_permutation_n < 9:
            raise ValueError("max_spearman_permutation_n must be at least 9.")


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values, preserving expected NaNs and index."""
    p = p_values.astype(float).to_numpy(copy=True)
    if np.isinf(p).any():
        raise ValueError("p-values must not contain infinity.")
    valid_idx = np.where(~np.isnan(p))[0]
    q = np.full(p.shape, np.nan, dtype=float)
    if valid_idx.size == 0:
        return pd.Series(q, index=p_values.index, name="q_value")
    valid_p = p[valid_idx]
    if np.any((valid_p < 0) | (valid_p > 1)):
        raise ValueError("p-values must be within [0, 1].")
    order = np.argsort(valid_p, kind="mergesort")
    ranked_p = valid_p[order]
    m = ranked_p.size
    adjusted = ranked_p * m / np.arange(1, m + 1, dtype=float)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    unsorted = np.empty_like(adjusted)
    unsorted[order] = adjusted
    q[valid_idx] = unsorted
    return pd.Series(q, index=p_values.index, name="q_value")




def _underlying_numpy_dtype(dtype: object) -> np.dtype | None:
    candidate = getattr(dtype, "numpy_dtype", None)
    try:
        return np.dtype(candidate if candidate is not None else dtype)
    except (TypeError, ValueError):
        return None


def _is_extended_float_dtype(dtype: object) -> bool:
    nd = _underlying_numpy_dtype(dtype)
    return bool(nd is not None and nd.kind == "f" and nd.itemsize > np.dtype(np.float64).itemsize)

def _check_kernel_matrix(df: pd.DataFrame, label: str) -> None:
    if not df.index.is_unique or not df.columns.is_unique:
        raise ValueError(f"Dataset {label} requires unique sample and feature IDs.")
    if any(not isinstance(x, str) or x == "" for x in df.index):
        raise ValueError(f"Dataset {label} sample IDs must be nonempty strings.")
    if any(not isinstance(x, str) or x == "" for x in df.columns):
        raise ValueError(f"Dataset {label} feature IDs must be nonempty strings.")
    for pos in range(df.shape[1]):
        c = df.columns[pos]
        s = df.iloc[:, pos]
        if (
            pd.api.types.is_bool_dtype(s.dtype)
            or pd.api.types.is_complex_dtype(s.dtype)
            or _is_extended_float_dtype(s.dtype)
            or not pd.api.types.is_numeric_dtype(s.dtype)
        ):
            raise ValueError(
                f"Dataset {label} feature {c!r} is not a supported real numeric vector; "
                "supported floating-point inputs are binary16/32/64 only."
            )
        for v in s.array:
            if pd.isna(v):
                continue
            fv = float(v)
            if not math.isfinite(fv):
                raise ValueError(f"Dataset {label} contains a nonfinite nonmissing value in feature {c!r}.")


def _pair_values(x: pd.Series, y: pd.Series) -> tuple[list[object], list[object]]:
    out_x: list[object] = []
    out_y: list[object] = []
    for a, b in zip(x.array, y.array, strict=True):
        if pd.isna(a) or pd.isna(b):
            continue
        fa = float(a)
        fb = float(b)
        if not math.isfinite(fa) or not math.isfinite(fb):
            raise ValueError("Infinity cannot be treated as pairwise missingness.")
        out_x.append(a)
        out_y.append(b)
    return out_x, out_y


def _is_constant(values: list[object]) -> bool:
    return len(values) < 2 or all(v == values[0] for v in values[1:])


def _stable_affine_vector(values: list[object]) -> np.ndarray:
    """Return a dimensionless affine transform preserving correlation of supplied floats.

    Translation is attempted before scaling to preserve small represented differences at
    large offsets. If subtraction overflows, scale first and then translate.
    """
    arr = np.asarray(values, dtype=np.float64)
    if not np.isfinite(arr).all():
        raise FloatingPointError("Pearson input contains a nonfinite value.")
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        shifted = arr - arr[0]
    if np.isfinite(shifted).all():
        scale = float(np.max(np.abs(shifted)))
        if scale > 0.0 and math.isfinite(scale):
            out = shifted / scale
            if np.isfinite(out).all() and np.ptp(out) > 0:
                return out
    max_abs = float(np.max(np.abs(arr)))
    if max_abs == 0.0 or not math.isfinite(max_abs):
        raise FloatingPointError("Pearson input could not be stabilized on a finite scale.")
    scaled = arr / max_abs
    shifted = scaled - scaled[0]
    scale = float(np.max(np.abs(shifted)))
    if scale == 0.0 or not math.isfinite(scale):
        raise FloatingPointError("Pearson input lost all variation during numerical stabilization.")
    out = shifted / scale
    if not np.isfinite(out).all() or np.ptp(out) == 0:
        raise FloatingPointError("Pearson stabilized vector is nonfinite or constant.")
    return out


def _pearson(values_x: list[object], values_y: list[object]) -> dict[str, object]:
    for values in (values_x, values_y):
        if any(isinstance(v, (int, np.integer)) and abs(int(v)) > 2**53 for v in values):
            return {
                "estimate": np.nan,
                "p_value": np.nan,
                "status": "unsupported_precision",
                "p_value_method": "",
                "numerical_warning": "Pearson requires float conversion; exact integer values above 2**53 are not accepted.",
            }
    try:
        x = _stable_affine_vector(values_x)
        y = _stable_affine_vector(values_y)
    except Exception as exc:
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "",
            "numerical_warning": f"Pearson numerical stabilization failed: {type(exc).__name__}: {exc}",
        }

    # Independent coefficient check on stabilized values; this catches a finite but
    # inconsistent library result before it can enter the FDR family.
    xc = x - x.mean()
    yc = y - y.mean()
    denom = float(np.linalg.norm(xc) * np.linalg.norm(yc))
    if denom == 0.0 or not math.isfinite(denom):
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "",
            "numerical_warning": "Pearson stabilized vectors have zero or nonfinite variance.",
        }
    reference_r = float(np.dot(xc, yc) / denom)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            res = stats.pearsonr(x, y)
        except Exception as exc:
            return {
                "estimate": np.nan,
                "p_value": np.nan,
                "status": "numerical_failure",
                "p_value_method": "",
                "numerical_warning": f"pearsonr raised {type(exc).__name__}: {exc}",
            }
    estimate = float(res.statistic)
    p = float(res.pvalue)
    warning_text = "; ".join(str(w.message) for w in caught)
    if caught:
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "scipy_pearsonr_beta_null_after_affine_stabilization",
            "numerical_warning": "Numerical warning remained after affine stabilization: " + warning_text,
        }
    if (
        not math.isfinite(estimate)
        or not math.isfinite(p)
        or not (-1.0 - 1e-12 <= estimate <= 1.0 + 1e-12)
        or not (0.0 <= p <= 1.0)
        or abs(estimate - reference_r) > 1e-12
    ):
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "scipy_pearsonr_beta_null_after_affine_stabilization",
            "numerical_warning": (
                f"Pearson numerical cross-check failed (SciPy r={estimate!r}, reference r={reference_r!r})."
            ),
        }
    return {
        "estimate": float(np.clip(reference_r, -1.0, 1.0)),
        "p_value": p,
        "status": "ok",
        "p_value_method": "scipy_pearsonr_beta_null_after_affine_stabilization",
        "numerical_warning": "",
    }


def _rank_vector(values: list[object]) -> np.ndarray:
    if all(isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)) for v in values):
        arr = np.asarray([int(v) for v in values], dtype=np.int64)
    else:
        if any(isinstance(v, (int, np.integer)) and abs(int(v)) > 2**53 for v in values):
            raise ValueError("Mixed floating/integer Spearman input contains an exact integer above 2**53.")
        arr = np.asarray(values, dtype=np.float64)
    return stats.rankdata(arr, method="average").astype(np.float64, copy=False)


def _rho_from_ranks(rx: np.ndarray, ry: np.ndarray) -> float:
    xc = rx - rx.mean()
    yc = ry - ry.mean()
    denom = float(np.linalg.norm(xc) * np.linalg.norm(yc))
    if denom == 0.0:
        return float("nan")
    return float(np.dot(xc, yc) / denom)


def _rank_pattern(r: np.ndarray) -> tuple[float, ...]:
    return tuple(float(x) for x in np.sort(r))


def _pattern_seed(pattern_x: tuple[float, ...], pattern_y: tuple[float, ...], base_seed: int, b: int) -> int:
    payload = repr((SPEARMAN_ALGORITHM_VERSION, pattern_x, pattern_y, int(base_seed), int(b))).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


@dataclass
class _SpearmanRunContext:
    config: CorrelationConfig
    exact_cache: dict[tuple[tuple[float, ...], tuple[float, ...]], np.ndarray] = field(default_factory=dict)
    mc_cache: dict[tuple[tuple[float, ...], tuple[float, ...], int, int], np.ndarray] = field(default_factory=dict)
    exact_groups_used: set[tuple[tuple[float, ...], tuple[float, ...]]] = field(default_factory=set)
    mc_groups_used: set[tuple[tuple[float, ...], tuple[float, ...], int, int]] = field(default_factory=set)
    total_null_evaluations: int = 0
    cache_bytes: int = 0

    def reserve_exact(self, key: tuple[tuple[float, ...], tuple[float, ...]], n: int) -> None:
        if key in self.exact_groups_used:
            return
        evaluations = math.factorial(n)
        bytes_needed = evaluations * np.dtype(np.float64).itemsize
        if len(self.exact_groups_used) + 1 > self.config.max_spearman_exact_null_groups:
            raise AnalysisLimitError(
                f"Run requires more than {self.config.max_spearman_exact_null_groups} distinct exact Spearman null groups."
            )
        self._reserve_work(evaluations, bytes_needed)
        self.exact_groups_used.add(key)

    def reserve_mc(self, key: tuple[tuple[float, ...], tuple[float, ...], int, int]) -> None:
        if key in self.mc_groups_used:
            return
        evaluations = int(self.config.spearman_permutations)
        bytes_needed = evaluations * np.dtype(np.float64).itemsize
        if len(self.mc_groups_used) + 1 > self.config.max_spearman_mc_null_groups:
            raise AnalysisLimitError(
                f"Run requires more than {self.config.max_spearman_mc_null_groups} distinct Monte Carlo Spearman null groups."
            )
        self._reserve_work(evaluations, bytes_needed)
        self.mc_groups_used.add(key)

    def _reserve_work(self, evaluations: int, bytes_needed: int) -> None:
        if self.total_null_evaluations + evaluations > self.config.max_spearman_total_null_evaluations:
            raise AnalysisLimitError(
                f"Spearman null-generation work would exceed {self.config.max_spearman_total_null_evaluations:,} permutation evaluations."
            )
        if self.cache_bytes + bytes_needed > self.config.max_spearman_null_cache_bytes:
            raise AnalysisLimitError(
                f"Spearman null cache would exceed {self.config.max_spearman_null_cache_bytes:,} bytes."
            )
        self.total_null_evaluations += evaluations
        self.cache_bytes += bytes_needed


def _exact_abs_rho_null(rx: np.ndarray, ry: np.ndarray, ctx: _SpearmanRunContext) -> np.ndarray:
    key = (_rank_pattern(rx), _rank_pattern(ry))
    ctx.reserve_exact(key, len(ry))
    cached = ctx.exact_cache.get(key)
    if cached is not None:
        return cached
    xc = np.sort(rx) - np.mean(rx)
    yc = np.sort(ry) - np.mean(ry)
    denom = float(np.linalg.norm(xc) * np.linalg.norm(yc))
    values = np.empty(math.factorial(len(ry)), dtype=np.float64)
    for i, perm in enumerate(itertools.permutations(yc.tolist())):
        values[i] = abs(float(np.dot(xc, np.asarray(perm, dtype=np.float64)) / denom))
    values.sort()
    ctx.exact_cache[key] = values
    return values


def _mc_abs_rho_null(rx: np.ndarray, ry: np.ndarray, *, ctx: _SpearmanRunContext) -> np.ndarray:
    px = _rank_pattern(rx)
    py = _rank_pattern(ry)
    b = int(ctx.config.spearman_permutations)
    base_seed = int(ctx.config.random_seed)
    key = (px, py, b, base_seed)
    ctx.reserve_mc(key)
    cached = ctx.mc_cache.get(key)
    if cached is not None:
        return cached
    xc = np.sort(rx) - np.mean(rx)
    yc = np.sort(ry) - np.mean(ry)
    denom = float(np.linalg.norm(xc) * np.linalg.norm(yc))
    rng = np.random.Generator(np.random.PCG64(_pattern_seed(px, py, base_seed, b)))
    null = np.empty(b, dtype=np.float64)
    for i in range(b):
        null[i] = abs(float(np.dot(xc, rng.permutation(yc)) / denom))
    null.sort()
    ctx.mc_cache[key] = null
    return null


def _minimum_exact_abs_tail_p(null: np.ndarray, tol: float = SPEARMAN_TAIL_TOLERANCE) -> float:
    if null.size == 0:
        return float("nan")
    max_stat = float(null[-1])
    left = int(np.searchsorted(null, max_stat - tol, side="left"))
    return float((null.size - left) / null.size)


def _spearman(values_x: list[object], values_y: list[object], config: CorrelationConfig, ctx: _SpearmanRunContext) -> dict[str, object]:
    try:
        rx = _rank_vector(values_x)
        ry = _rank_vector(values_y)
    except Exception as exc:
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "unsupported_precision",
            "p_value_method": "",
            "numerical_warning": str(exc),
        }
    rho = _rho_from_ranks(rx, ry)
    if not math.isfinite(rho):
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "",
            "numerical_warning": "Spearman rank correlation produced a nonfinite coefficient.",
        }
    rho = float(np.clip(rho, -1.0, 1.0))
    n = len(rx)
    tied_x = bool(np.unique(rx).size < n)
    tied_y = bool(np.unique(ry).size < n)
    obs = abs(rho)

    if n <= config.spearman_exact_max_n:
        null = _exact_abs_rho_null(rx, ry, ctx)
        left = int(np.searchsorted(null, obs - SPEARMAN_TAIL_TOLERANCE, side="left"))
        extreme = int(null.size - left)
        p = float(extreme / null.size)
        return {
            "estimate": rho,
            "p_value": p,
            "status": "ok",
            "p_value_method": "spearman_exact_pairings_abs_tail",
            "permutations": int(null.size),
            "extreme_count": extreme,
            "p_resolution": np.nan,
            "exact_probability_unit": float(1 / null.size),
            "exact_min_attainable_p": _minimum_exact_abs_tail_p(null),
            "monte_carlo_floor": np.nan,
            "tied_x": tied_x,
            "tied_y": tied_y,
            "numerical_warning": "",
        }

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
        p = float((extreme + 1) / (null.size + 1))
        return {
            "estimate": rho,
            "p_value": p,
            "status": "ok",
            "p_value_method": "spearman_monte_carlo_pairings_abs_tail_add_one",
            "permutations": int(null.size),
            "extreme_count": extreme,
            "p_resolution": floor,
            "exact_probability_unit": np.nan,
            "exact_min_attainable_p": np.nan,
            "monte_carlo_floor": floor,
            "tied_x": tied_x,
            "tied_y": tied_y,
            "numerical_warning": "",
        }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = stats.spearmanr(rx, ry)
    p = float(res.pvalue)
    if caught or not math.isfinite(p) or not (0.0 <= p <= 1.0):
        return {
            "estimate": np.nan,
            "p_value": np.nan,
            "status": "numerical_failure",
            "p_value_method": "scipy_spearmanr_asymptotic_N_ge_501_untied",
            "numerical_warning": "; ".join(str(w.message) for w in caught) or "Spearman returned an invalid p-value.",
        }
    return {
        "estimate": rho,
        "p_value": p,
        "status": "ok",
        "p_value_method": "scipy_spearmanr_asymptotic_N_ge_501_untied",
        "permutations": np.nan,
        "extreme_count": np.nan,
        "p_resolution": np.nan,
        "exact_probability_unit": np.nan,
        "exact_min_attainable_p": np.nan,
        "monte_carlo_floor": np.nan,
        "tied_x": tied_x,
        "tied_y": tied_y,
        "numerical_warning": "",
    }


def _compute_cross_correlation(
    a: pd.DataFrame,
    b: pd.DataFrame,
    config: CorrelationConfig,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    """Private scalar mathematical kernel for already validated and aligned matrices."""
    if not a.index.equals(b.index):
        raise ValueError("Datasets are not aligned to identical sample IDs in identical order.")
    _check_kernel_matrix(a, "A")
    _check_kernel_matrix(b, "B")

    if len(a) > config.max_samples:
        raise AnalysisLimitError(f"Matched sample count {len(a):,} exceeds scalar-engine cap {config.max_samples:,}.")
    planned = int(a.shape[1] * b.shape[1])
    if planned > config.max_planned_tests:
        raise AnalysisLimitError(
            f"Requested {planned:,} feature-pair tests, exceeding the scalar-engine safety limit of {config.max_planned_tests:,}."
        )

    rows: list[dict[str, object]] = []
    spearman_ctx = _SpearmanRunContext(config) if config.method == "spearman" else None
    for feature_a in a.columns:
        xa = a[feature_a]
        for feature_b in b.columns:
            xb = b[feature_b]
            x, y = _pair_values(xa, xb)
            n = len(x)
            row: dict[str, object] = {
                "feature_a": str(feature_a),
                "feature_b": str(feature_b),
                "method": config.method,
                "estimate": np.nan,
                "p_value": np.nan,
                "q_value": np.nan,
                "n_pairwise": int(n),
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
            if n < config.min_pairwise_n:
                row["status"] = "insufficient_pairwise_n"
            elif _is_constant(x) or _is_constant(y):
                row["status"] = "constant_pair"
            else:
                if config.method == "pearson":
                    calc = _pearson(x, y)
                else:
                    assert spearman_ctx is not None
                    calc = _spearman(x, y, config, spearman_ctx)
                row.update(calc)
            rows.append(row)

    result = pd.DataFrame(rows)
    failures = result["status"].isin(["numerical_failure", "unsupported_precision"])
    if failures.any():
        counts = result.loc[failures, "status"].value_counts().to_dict()
        raise NumericalAnalysisError(
            f"Analysis produced unresolved numerical/precision failures {counts}; FDR finalization was withheld."
        )

    testable = result["status"].isin(["ok", "ok_with_warning"])
    m_eligible = int(testable.sum())
    if m_eligible:
        p_for_bh = result.loc[testable, "p_value"]
        if p_for_bh.isna().any():
            raise NumericalAnalysisError("A testable result has a missing p-value; FDR finalization was withheld.")
        result.loc[testable, "q_value"] = benjamini_hochberg(p_for_bh).to_numpy()
    family: dict[str, int | str | float] = {
        "correction": "Benjamini-Hochberg",
        "family_scope": "all_eligible_AxB_pairs_for_prespecified_method",
        "method": config.method,
        "m_planned": planned,
        "m_eligible": m_eligible,
        "m_tested": m_eligible,
        "m_failed": 0,
        "m_ineligible": int(planned - m_eligible),
    }
    if spearman_ctx is not None:
        family.update(
            {
                "spearman_exact_null_groups_used": len(spearman_ctx.exact_groups_used),
                "spearman_mc_null_groups_used": len(spearman_ctx.mc_groups_used),
                "spearman_total_null_evaluations_reserved": spearman_ctx.total_null_evaluations,
                "spearman_null_cache_bytes_reserved": spearman_ctx.cache_bytes,
            }
        )
    return result, family
