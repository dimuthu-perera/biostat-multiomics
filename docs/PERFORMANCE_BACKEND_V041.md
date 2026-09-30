# Performance backend contract — v0.4.1

## Scope

v0.4.1 extends the independently accepted v0.4.0 Pearson performance backend to Pearson analyses with **pairwise missingness when exact observed-sample masks are sufficiently reusable across features**. The accepted `correlation_tool/` v0.2.4 package remains the frozen statistical oracle and is not modified.

Backend choice remains runtime-only and is deliberately excluded from AnalysisSpec. A scientific request therefore has the same method, exact sample alignment, pairwise masks/N, eligibility rules, Pearson beta-null p-value definition, and one global BH family regardless of backend.

## Backend identifiers

- `reference_scalar_v0.2.4`
- accepted historical optimized identifier: `optimized_complete_pearson_v0.4.0`
- current optimized identifier: `optimized_pearson_v0.4.1`

The RunBundle v1 verifier accepts the historical v0.4.0 identifier for backward readability and records the v0.4.1 identifier for new optimized executions.

CLI request values remain `reference`, `optimized`, and `auto`. The v0.4.1 review candidate keeps the CLI default at `reference` until this extension is independently accepted.

## Optimized eligibility

The optimized v0.4.1 path requires:

1. prespecified method = Pearson;
2. validated aligned matrices are available;
3. no exact integer above `2**53` is present in the aligned matrices;
4. complete-data Pearson, or pairwise missingness with bounded/reusable observed-sample mask classes;
5. pairwise subset stabilization succeeds under the frozen v0.2.4 affine-stabilization policy;
6. vectorized SciPy computation remains finite and warning-free after stabilization.

All Spearman runs use the frozen reference backend.

Highly fragmented missingness also falls back to reference. The current engineering threshold is:

- at most 4,096 dataset-A-mask × dataset-B-mask class combinations; and
- for runs with at least 1,024 planned pairs, at least 4 planned feature pairs per mask-class combination on average.

These are performance/complexity thresholds, not statistical thresholds. Fallback does not change the requested analysis.

## Exact pairwise-mask semantics

For each dataset feature, v0.4.1 records the exact aligned positions that are nonmissing. Boolean masks are packed only for grouping/comparison; no sample is imputed or dropped globally.

For one A-mask class and one B-mask class:

1. the exact pairwise-complete mask is the logical intersection of the two observed-sample masks;
2. `n_pairwise` is the exact count of positions in that intersection;
3. if `n_pairwise < minimum_pairwise_n`, every feature pair in that rectangular class product is `insufficient_pairwise_n`;
4. otherwise constant checks are performed on the exact pairwise-complete feature subset;
5. nonconstant subsets are stabilized using the frozen `_stable_affine_vector` implementation;
6. vectorized Pearson coefficients/p-values are calculated only among nonconstant subsets sharing that exact mask;
7. pair results are placed back into the original A-major/B-minor result order.

A feature may participate in more than one pairwise-complete mask because the opposite dataset feature can have a different missingness pattern. Stabilization is therefore cached by **(side, exact pairwise mask, feature)**, not globally by feature.

## Numerical implementation

Within one exact pairwise mask group, the implementation uses the same numerical contract as accepted v0.4.0:

- frozen affine stabilization;
- centered/norm-scaled coefficient cross-check;
- vectorized `scipy.stats.pearsonr(..., axis=-1)` for the same beta-null p-value calculation;
- coefficient agreement with SciPy within the oracle's existing `1e-12` internal check;
- bounded broadcast blocks (`MAX_BROADCAST_VALUES_PER_BLOCK = 2,000,000`).

Any unsupported stabilization state or vectorized numerical warning causes the optimized execution to abandon that run and use the frozen reference backend.

## Multiple-testing invariant

BH is never applied per mask group or per vectorization block.

All pair statuses and raw p-values are assembled first. The unchanged frozen `benjamini_hochberg` implementation is then called **once** on all eligible A×B p-values for the prespecified Pearson run.

The full family metadata must exactly match the frozen reference.

## Equivalence contract

Exact equality is required for:

- feature identifiers/order;
- method;
- pairwise N;
- pair status;
- p-value method label;
- numerical warning field;
- Pearson-inapplicable permutation/tie metadata;
- family metadata;
- run fingerprint;
- alignment provenance;
- Pearson inference-policy provenance.

Floating-point tolerances remain unchanged from independently accepted v0.4.0:

| Field | absolute tolerance | relative tolerance |
|---|---:|---:|
| estimate | `5e-15` | `5e-14` |
| p_value | `5e-15` | `5e-14` |
| q_value | `5e-15` | `5e-14` |

`--verify-against-reference` independently runs the frozen scalar oracle and prevents successful completion if any equivalence condition fails.

## Maintained regression coverage

v0.4.1 adds tests for:

- randomized Pearson matrices with structured/reused missingness masks;
- exact pairwise N equivalence;
- pairwise-subset constants;
- insufficient pairwise N;
- one global BH invocation after all mask groups;
- optimized missing-data execution through the public runner;
- highly fragmented random-cell missingness fallback;
- unchanged complete-data optimized path;
- unchanged default-reference Spearman fixture and frozen source hashes.

## Independent numerical sweep

A separate 120-case structured-missingness sweep used varying sample sizes, feature counts, scales, large represented offsets, inserted constants, and reusable missingness masks.

For successfully optimized/reference-comparable cases, 1,581 result rows were compared. Maximum absolute differences were:

- estimate: `3.3306690738754696e-16`;
- p-value: `0.0`;
- q-value: `0.0`.

All compared fields satisfied the accepted v0.4.0 equivalence contract.

## Candidate-environment performance evidence

Environment used for the candidate benchmark: Python 3.13.5 with the repository's scientific dependency set.

Structured missingness used four reusable observed-sample masks per dataset and 100 samples:

| A features | B features | pairs | scalar seconds | optimized seconds | speedup |
|---:|---:|---:|---:|---:|---:|
| 20 | 20 | 400 | 0.2736 | 0.04462 | 6.13× |
| 50 | 50 | 2,500 | 1.5032 | 0.09797 | 15.34× |
| 100 | 100 | 10,000 | 6.0912 | 0.20169 | 30.20× |

The optimized pairwise-missing kernel also completed 250,000 structured-missing feature pairs (500×500, 100 samples, four masks per side) in about 2.00 seconds. No scalar timing is claimed for that ceiling case.

Complete-data Pearson performance remained in the accepted v0.4.0 range in this run (approximately 40×–121× across 400–10,000 pairs).

These are environment-specific performance measurements, not statistical guarantees.

## Out of scope for v0.4.1

- optimized Spearman ranking/permutation inference;
- optimization of highly fragmented/random pairwise missingness;
- parallel Monte Carlo RNG;
- disk-backed computation;
- confidence intervals;
- BY FDR or other new multiplicity procedures;
- preprocessing algorithms;
- new analysis modules.
