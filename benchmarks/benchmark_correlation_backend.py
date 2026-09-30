from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from biostat_tool.modules.correlation_backends import (
    _optimized_complete_pearson_kernel,
    _optimized_pairwise_missing_pearson_kernel,
)
from correlation_tool import CorrelationConfig
from correlation_tool.analysis import _compute_cross_correlation


def make_data(n: int, p: int, q: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = [f"S{i:05d}" for i in range(n)]
    a = pd.DataFrame(rng.normal(size=(n, p)), index=idx, columns=[f"A{i:05d}" for i in range(p)])
    b = pd.DataFrame(rng.normal(size=(n, q)), index=idx, columns=[f"B{i:05d}" for i in range(q)])
    return a, b


def add_structured_missingness(a: pd.DataFrame, b: pd.DataFrame, classes: int = 4) -> None:
    n = len(a)
    masks_a: list[np.ndarray] = []
    masks_b: list[np.ndarray] = []
    for k in range(classes):
        ma = np.ones(n, dtype=bool)
        mb = np.ones(n, dtype=bool)
        ma[k::11] = False
        mb[(k + 3)::13] = False
        masks_a.append(ma)
        masks_b.append(mb)
    for j, c in enumerate(a.columns):
        a.loc[~masks_a[j % classes], c] = np.nan
    for j, c in enumerate(b.columns):
        b.loc[~masks_b[j % classes], c] = np.nan


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


def _assert_equivalent(opt: pd.DataFrame, ref: pd.DataFrame, opt_family: dict, ref_family: dict) -> None:
    for col in ["feature_a", "feature_b", "method", "n_pairwise", "status", "p_value_method", "numerical_warning"]:
        assert opt[col].equals(ref[col])
    for col in ["estimate", "p_value", "q_value"]:
        np.testing.assert_allclose(opt[col], ref[col], atol=5e-15, rtol=5e-14, equal_nan=True)
    assert opt_family == ref_family


def run_case(n: int, p: int, q: int, seed: int, missingness: str) -> dict[str, float | int | str]:
    a, b = make_data(n, p, q, seed)
    if missingness == "structured":
        add_structured_missingness(a, b)
    cfg = CorrelationConfig(method="pearson", min_pairwise_n=3, max_planned_tests=max(250_000, p * q))
    ref_s, (ref, ref_family) = timed(_compute_cross_correlation, a, b, cfg)
    kernel = _optimized_pairwise_missing_pearson_kernel if missingness == "structured" else _optimized_complete_pearson_kernel
    opt_s, (opt, opt_family) = timed(kernel, a, b, cfg)
    _assert_equivalent(opt, ref, opt_family, ref_family)
    return {
        "missingness": missingness,
        "samples": n,
        "features_a": p,
        "features_b": q,
        "pairs": p * q,
        "reference_seconds": ref_s,
        "optimized_seconds": opt_s,
        "speedup_x": ref_s / opt_s,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="20x20,50x50,100x100")
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--missingness", choices=["none", "structured"], default="none")
    args = ap.parse_args()
    out = []
    for i, item in enumerate(args.cases.split(",")):
        p, q = (int(x) for x in item.split("x"))
        out.append(run_case(args.samples, p, q, 20260916 + i, args.missingness))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
