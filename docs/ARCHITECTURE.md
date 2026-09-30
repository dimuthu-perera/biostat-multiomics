# Platform architecture — v0.4.2

## Principle

There is one execution path:

```text
Web UI ─┐
        ├─> AnalysisSpec v1 -> central runner -> AnalysisModule registry -> module -> RunBundle v1
CLI ────┘
```

The web UI and CLI do not implement separate statistical calculations.

## AnalysisModule boundary

The central runner is deliberately thin. It resolves `spec.analysis_type` through the module registry, calls the module's mandatory inspection path, and later executes only a prepared state whose module ID/version still matches the active registration.

Current registration:

```text
cross_omics_correlation -> CorrelationAnalysisModule v1.2
```

The standardized platform records are:

```text
PreparedAnalysis
  analysis/module identity
  requested spec + hash
  exact source identities
  run fingerprint
  blocked/warning state
  inspection/alignment documents
  statistical-policy metadata
  opaque module state

CompletedAnalysis
  requested/effective specs
  module + numerical-engine identity
  primary result table + schema
  AnalysisSummary
  inspection/alignment/provenance
  opaque module result
```

See `ANALYSIS_MODULE_CONTRACT.md`.

## Frozen correlation oracle

`correlation_tool/` is byte-for-byte unchanged from accepted v0.2.4. `ORACLE_SOURCE_SHA256.txt` and `tests/oracle/test_frozen_oracle.py` fail if those source bytes change.

`CorrelationAnalysisModule` wraps—not rewrites—the oracle. It owns platform-side input snapshotting/import, inspection orchestration, acknowledgement handling, result description, and provenance. Pearson, Spearman, BH, exact sample alignment, pairwise masks/N, omics guardrails, and deterministic permutation behavior remain in the frozen oracle.

Optimized Pearson execution lives behind the correlation module and remains continuously comparable against the scalar oracle. v0.4.2 retains the accepted Pearson coverage and adds complete-data Spearman pre-ranking; Spearman with missingness and unsupported/fragmented cases fall back to reference.

## Statistical policy

Platform statistical policy is non-numerical and independently versioned from the oracle. Policy v1.0 supplies researcher-facing defaults/advisories without changing validated calculations. See `STATISTICAL_POLICY_V1.md`.

## AnalysisSpec

Canonical format: JSON. YAML is an optional convenience adapter and is not a core runtime dependency.

The current v1 spec identifies both input files by SHA-256, declares orientation/data type/preprocessing/study design, prespecifies Pearson or Spearman, defines minimum pairwise N, and fixes the BH family. Warning acknowledgement is bound to the exact frozen-oracle inspection fingerprint.

Runtime path overrides are allowed only as locations of the same SHA-256-identified input bytes.

## RunBundle

RunBundle v1 remains the completed-artifact boundary for the current correlation module. Module-specific execution is normalized into standardized platform records before bundle publication, and the writer now consumes module-declared primary result metadata.

The **public RunBundle v1 JSON Schema remains correlation-shaped** (two matrix inputs, correlation result fields). It must receive a versioned schema extension before a second scientific analysis type is released. Existing v1 bundles will not be silently reinterpreted.

Research datasets are not copied into the bundle by default. Their exact byte hashes are recorded.

Completed inspection/alignment documents are reconstructed from the freshly revalidated module execution, not reused from prepared caller-visible mappings. RunBundle verification cross-checks them against the executed frozen-oracle manifest in provenance.

## Local-first browser

The web application binds to `127.0.0.1`, disables Gradio public sharing, and disables Gradio analytics by default. Statistical execution itself requires no external API or cloud service.
