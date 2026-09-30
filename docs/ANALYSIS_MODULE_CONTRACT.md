# AnalysisModule contract — v1

## Purpose

`AnalysisModule` is the boundary between platform infrastructure and statistical/domain-specific logic.
The web UI and CLI never implement statistical calculations. They create/read an `AnalysisSpec` and call the central runner; the runner resolves `analysis.type` through the module registry.

Current registration:

```text
cross_omics_correlation -> correlation module v1.3
```

The current `AnalysisSpec` v1 schema/parser is intentionally correlation-specific. A second scientific analysis type requires a versioned specification-schema extension and parser dispatch; it must not be smuggled into v1 through generic free-form fields. Likewise, the public RunBundle v1 manifest schema remains correlation-shaped and must be versioned/generalized before the second analysis type is released. The module records introduced here are the stable execution boundary that makes those future schema migrations tractable.

## Required module methods

Every module implements:

```text
validate_spec(spec)
inspect(spec, base_dir, path_overrides) -> PreparedAnalysis
run(prepared, acknowledge_warnings) -> CompletedAnalysis
summarize(module_result, effective_spec) -> AnalysisSummary
result_schema(module_result) -> mapping
```

### `validate_spec`

Checks module-specific specification semantics without inference.

### `inspect`

Owns input resolution, exact-byte identity checks, import, mandatory domain inspection, alignment/design checks, and construction of the module-private prepared state. It returns a standardized `PreparedAnalysis` containing:

- analysis/module identity and module version;
- requested AnalysisSpec hash;
- source byte identities;
- run fingerprint;
- blocked state and acknowledgement-bound warning IDs;
- machine-readable inspection/alignment documents;
- statistical-policy version/advisories;
- opaque module-private state.

### `run`

May execute only a `PreparedAnalysis` created by the same registered module/version. It performs the validated numerical path and returns a standardized `CompletedAnalysis`.

### `summarize` and `result_schema`

Describe completed scientific output without rerunning inference. RunBundle/report infrastructure consumes these standardized descriptions rather than importing the statistical engine directly.

## Current correlation module

`CorrelationAnalysisModule` owns the platform orchestration around the byte-frozen `correlation_tool` v0.2.4 oracle:

```text
AnalysisSpec
  -> hash-verified private input snapshots
  -> frozen oracle inspection
  -> fingerprint-bound acknowledgement
  -> frozen oracle execution
  -> standardized CompletedAnalysis
```

The module wrapper does not reimplement Pearson, Spearman, Benjamini-Hochberg, sample alignment, pairwise missing masks/N, omics guardrails, or deterministic permutation logic.

## Backend/performance boundary

The next performance milestone may add an optimized correlation backend **inside** the correlation module. The frozen scalar oracle remains permanently available as the reference implementation.

An optimized backend is acceptable only when equivalence tests establish the intended agreement for:

- exact sample IDs and ordering;
- pairwise complete-case masks and N;
- eligibility/status;
- Pearson coefficient and p-value within declared numerical tolerances;
- Spearman coefficient and inference-branch selection;
- exact permutation p-values;
- deterministic Monte Carlo seed/count behavior where the optimized design preserves identical RNG semantics;
- full eligible hypothesis family;
- BH-adjusted values;
- failure behavior and provenance labels.

Performance code must not silently redefine a scientific parameter or FDR family.

## Compatibility note

v0.4.1 temporarily retains `prepared.inspected` and `completed.oracle_run` read-only compatibility properties for the accepted v0.3.2 web/test surface. New platform code should use standardized fields such as `run_fingerprint`, `inspection_document`, `primary_results`, `result_schema`, and `summary`.

## Completed-provenance authority

Prepared inspection/alignment documents are caller-visible convenience artifacts and are not authoritative after execution. A module must construct completed scientific provenance from the freshly validated execution state. For correlation, v0.4.1 derives completed inspection/alignment documents from `oracle_run.inspected`; RunBundle verification independently cross-checks those documents against the executed oracle manifest.

## v0.4 execution backend boundary

`AnalysisModule.run()` accepts a runtime-only `ExecutionOptions` object. Backend selection is intentionally excluded from AnalysisSpec because it must not change the requested scientific analysis. The correlation module v1.3 supports `reference`, `optimized`, and `auto` requests; v0.4.2 optimized execution covers accepted Pearson paths plus complete-data Spearman pre-ranking; Spearman with missingness and unsupported cases fall back to the frozen reference backend. `CompletedAnalysis.execution_metadata` records requested/actual backend, fallback reason, and optional frozen-reference equivalence evidence.
