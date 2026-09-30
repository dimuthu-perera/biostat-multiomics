# Performance backend contract — v0.4.0

## Scope

v0.4.0 introduces a second execution implementation **only for complete-data Pearson correlation**. The accepted `correlation_tool/` v0.2.4 package remains the frozen statistical oracle and is not modified.

Backend choice is runtime-only and is deliberately excluded from AnalysisSpec. A scientific request must therefore have the same method, aligned samples, eligibility rules, p-value definition, multiple-testing family and interpretation regardless of execution backend.

## Backend identifiers

- `reference_scalar_v0.2.4`
- `optimized_complete_pearson_v0.4.0`

CLI request values are `reference`, `optimized`, and `auto`. The v0.4.0 CLI default remains `reference` pending independent performance-backend acceptance.

## Optimized eligibility

The optimized v0.4.0 path is eligible only when all of the following are true:

1. the prespecified method is Pearson;
2. validated aligned matrices are available;
3. neither aligned matrix contains missing values;
4. exact integer values above `2**53` are absent;
5. every nonconstant feature is successfully stabilized by the frozen v0.2.4 affine-stabilization function.

All other requests use the frozen reference backend. This includes all Spearman analyses and all Pearson analyses with pairwise missingness.

## Numerical implementation

The optimized backend reuses `_stable_affine_vector` from the frozen v0.2.4 oracle once per nonconstant feature instead of once per feature pair.

For each bounded feature block it then:

1. centers and norm-scales the stabilized feature vectors;
2. obtains vectorized Pearson p-values from `scipy.stats.pearsonr(..., axis=-1)` using the same beta-null implementation used by the oracle;
3. computes the Pearson coefficient by block matrix dot product on the normalized centered stabilized vectors;
4. requires the coefficient to agree with SciPy's coefficient within the oracle's existing `1e-12` numerical cross-check;
5. assigns the same `constant_pair` status as the reference for pairs containing a constant feature;
6. performs no pair-specific missing-value logic because missingness is outside the optimized subset.

Pair blocks are bounded by `MAX_BROADCAST_VALUES_PER_BLOCK = 2,000,000` sample-values to avoid constructing the full `p × q × n` broadcast array.

## Multiple testing invariant

Benjamini-Hochberg is **not** applied inside computation blocks. Raw p-values for all eligible A×B pairs are assembled first, then the unchanged frozen `benjamini_hochberg` implementation is applied once globally to the full eligible family.

The required family metadata must exactly match the frozen reference:

- correction: Benjamini-Hochberg;
- scope: all eligible A×B pairs for the one prespecified method;
- planned/eligible/tested/ineligible counts;
- zero unresolved failures in a completed run.

## Equivalence contract

Exact equality is required for:

- result row/column structure;
- feature identifiers and order;
- method;
- pairwise N;
- status;
- p-value method label;
- numerical-warning field;
- Pearson-inapplicable permutation/tie metadata;
- global family metadata;
- run fingerprint;
- alignment provenance;
- Pearson-inference policy provenance.

Floating-point fields use explicit tolerances:

| Field | absolute tolerance | relative tolerance |
|---|---:|---:|
| estimate | `5e-15` | `5e-14` |
| p_value | `5e-15` | `5e-14` |
| q_value | `5e-15` | `5e-14` |

These tolerances are intentionally far tighter than the frozen oracle's existing `1e-12` internal coefficient cross-check and are intended only to permit final-bit changes from vectorized reduction order.

## Reference verification mode

`--verify-against-reference` is a development/audit mode. When optimized execution is actually used, the frozen scalar oracle is executed independently on the same prepared run and `compare_to_reference()` must pass before the completed RunBundle can be returned.

A material mismatch raises `BackendEquivalenceError` and prevents successful publication.

## Fallback behavior

If the optimized path is not eligible, or a vectorized numerical warning/failure occurs, execution uses the frozen scalar reference backend. RunBundle provenance records:

- requested backend;
- actual backend;
- optimized subset;
- fallback reason;
- reference-verification request/status and, when run, maximum observed differences and tolerances.

## Performance evidence in the v0.4.0 candidate environment

Environment: Python 3.13.5, NumPy 2.3.5, pandas 2.2.3, SciPy 1.17.0.

Synthetic complete-data Pearson benchmark, 100 samples:

| A features | B features | pairs | scalar seconds | optimized seconds | speedup |
|---:|---:|---:|---:|---:|---:|
| 20 | 20 | 400 | 0.5430 | 0.01333 | 40.7× |
| 50 | 50 | 2,500 | 3.2598 | 0.03127 | 104.3× |
| 100 | 100 | 10,000 | 13.1171 | 0.10197 | 128.6× |

The optimized kernel also completed the current 250,000-pair safety ceiling (500×500 features, 100 samples) in 2.47 seconds in this environment. No scalar timing is claimed for that case.

Benchmark numbers are environment-specific and are not statistical guarantees.

## Out of scope for v0.4.0

- optimized Pearson with pairwise missingness;
- optimized Spearman ranking or permutations;
- parallel Monte Carlo RNG;
- disk-backed result calculation;
- changes to BH, confidence intervals, BY FDR or statistical policy;
- new analysis modules.
