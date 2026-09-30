# Performance Backend v0.4.2 — Complete-data Spearman

## Scope

v0.4.2 adds one new optimized subset: **Spearman correlation when both aligned matrices are complete (no missing values)**. Pearson behavior remains the independently accepted v0.4.1 implementation.

The scientific request is unchanged. `AnalysisSpec` does not contain backend selection. Runtime options may request `reference`, `optimized`, or `auto`; RunBundle records requested and actual backend plus fallback/reference-verification metadata.

## Statistical invariants

The optimized Spearman path must preserve the frozen v0.2.4 contract:

- exact sample and feature order;
- pairwise N and constant-pair status;
- average-rank tie handling;
- exact positional permutation enumeration for N<=8;
- Monte Carlo positional pairings for 9<=N<=500 or any ties above 500;
- identical SHA-256 rank-pattern seed derivation, NumPy PCG64 stream, B, extreme count, add-one p-value and Monte Carlo floor;
- asymptotic SciPy `spearmanr` only for untied N>=501;
- identical inference labels and tie flags;
- one global BH correction after all eligible p-values are assembled;
- identical Spearman null-group/cache accounting in family metadata.

## Optimization

The scalar oracle reranks each feature independently for each A×B pair. v0.4.2 computes the frozen `_rank_vector` once per nonconstant feature and reuses that rank vector across all cross-dataset pairs. Pairwise rho uses the frozen `_rho_from_ranks`. Exact and Monte Carlo null distributions use the frozen `_exact_abs_rho_null` and `_mc_abs_rho_null` functions and the same `_SpearmanRunContext`. The asymptotic branch calls SciPy `spearmanr` on the same rank vectors.

Thus the optimization removes redundant ranking work without replacing the accepted inferential algorithms.

## Eligibility and fallback

Optimized Spearman is eligible only when:

1. method is Spearman;
2. validated aligned matrices are available; and
3. neither aligned matrix contains missing values.

Any aligned missingness falls back to `reference_scalar_v0.2.4`. Ranking/precision exceptions also fall back through the normal optimized-backend unsupported path.

## Equivalence contract

For optimized-vs-reference verification, identifiers/order/status/N/inference metadata and family metadata are exact. Numerical tolerance infrastructure remains `atol=5e-15`, `rtol=5e-14` for estimate/p/q, but the maintained Spearman branch sweep and 120-case independent sweep matched those quantities exactly (zero observed difference).

## Measured performance

Development environment, N=80, B=9,999, continuous complete data:

| A×B pairs | optimized | scalar reference | speedup |
|---:|---:|---:|---:|
| 400 | 0.0609 s | 0.1462 s | 2.40× |
| 2,500 | 0.1437 s | 0.8092 s | 5.63× |
| 10,000 | 0.4482 s | 3.0169 s | 6.73× |

These timings are environment-specific performance observations, not correctness evidence.

## Explicit non-goals

- no Spearman missing-data optimization in v0.4.2;
- no change to exact/Monte Carlo/asymptotic thresholds;
- no change to B, seed logic, p-value definition or BH;
- no new statistical methods;
- no change to frozen `correlation_tool/`.
