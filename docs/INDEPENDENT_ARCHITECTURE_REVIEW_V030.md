# Independent architecture review — Biostat Research Tool v0.3.0

**Verdict: NEEDS TARGETED ARCHITECTURE FIXES**

Reviewed 2026-09-16. Three HIGH platform correctness defects and one MEDIUM strict-parsing defect were reproduced. None requires modifying the accepted correlation mathematics or the frozen `correlation_tool/` package. The shared-runner architecture is sound in outline, but report identity, import provenance, and browser inspection lifecycle need corrections before platform acceptance.

## Target and execution evidence

Source archive: `biostat-tool-v0.3.0-candidate.zip`

SHA-256: `3d84622c3cae32d7cb59aa119129190dec1698f3d30b3bd57ea4af0ec8b2c381`

Wheel: `biostat_research_tool-0.3.0-py3-none-any.whl`

SHA-256: `c7c184d2c5d3270474978af3a088d0e6ce3a9ba16177a227861f13fd443f426e`

The first verification was `sha256sum -c ORACLE_SOURCE_SHA256.txt`: **5/5 files matched**. Independent byte comparison against the supplied accepted v0.2.4 source also matched all five Python files. All 12 Python files in the supplied wheel matched the corresponding v0.3.0 source files. No source, maintained tests, dependency files, or configuration was changed.

Maintained suite command, run from the source root:

```text
python -m pytest -o addopts='' -q
50 passed in 3.45s
```

**Exact maintained count: 50 passed, 0 failed, 0 skipped.** Independent probes are separate from this count.

Available execution environment: Python **3.12.14**, NumPy 2.3.5, pandas 2.2.3, SciPy 1.17.0, Gradio 6.5.1, openpyxl 3.1.5, pytest 9.0.2. The package declares Python `>=3.13,<3.14`; therefore this is fresh verification in the available environment, **not certification of the declared Python 3.13 environment**. Dependencies were not installed or changed. The CLI was exercised in subprocesses using a temporary `biostat` launcher calling the exact wheel-declared entry point, `biostat_tool.cli:main`; no package-install claim is made.

## Reproduced findings

All four findings have high confidence. The companion evidence archive contains `reproduce_findings.py`, a standalone synthetic reproduction requiring only the candidate's dependencies:

```bash
python reproduce_findings.py /absolute/path/to/biostat-tool-v0.3.0
```

It writes synthetic inputs/output into a new temporary directory and leaves candidate source untouched.

### H1 — HIGH: HTML reports silently change exact feature identities

**Source:** `biostat_tool/reporting.py:21`, `render_html_report`, specifically `pd.read_csv(results_path)`.

**Smallest demonstrated input:** two four-sample CSV files:

```csv
id,001
S1,1
S2,2
S3,4
S4,8
```

```csv
id,NA
S1,1
S2,3
S3,2
S4,9
```

Declare both metabolomics/quantitative, samples in rows, independent observations; prepare and execute Pearson with explicit warning acknowledgement, then write the bundle.

The engine and result CSV correctly identify the pair as `001` / `NA`. The completed HTML report instead displays **`1` / `NaN`**, with estimate `0.921277` and p/q `0.078723`. pandas re-infers feature types and applies its default missing-token rules when the report reads the CSV.

**Consequence:** a completed scientific report attaches valid statistics to altered or missing feature names. This is a normal supported input, not a numerical edge case. The bundle's report is inconsistent with its results, despite valid file checksums.

**Smallest correction:** explicitly preserve feature identifier columns as literal strings on report import and disable missing-token recognition for those identifiers. Preserve numeric parsing for estimate/p/q/N and numeric missing values. A string dtype alone is insufficient if default NA recognition remains enabled. Add report round-trip assertions for `001`, `1`, `NA`, and numeric-looking exponent strings; do not change the oracle.

### H2 — HIGH: source hashes and imported bytes can refer to different file versions

**Source:** `biostat_tool/runner.py:97` and `:105`, `prepare_analysis`.

Both paths are hashed first; they are reopened later by `load_matrix`. There is no immutable input snapshot connecting those operations.

**Minimal deterministic scheduling reproduction:** wrap `runner.load_matrix` so that, immediately before its real call for dataset A, it replaces the already-hashed CSV's first measurement `1` with `99`. This models an ordinary producer/editor replacing a local input during preparation. No hash function, parser, statistical routine, or validation outcome is mocked.

Observed:

- `prepare_analysis` succeeded and its dataframe contained `99`.
- `execute_prepared(..., acknowledge_warnings=True)` succeeded and a completed bundle was written.
- Recorded A hash remained `494f815be20571529cf5363ca4cf112bb570988ae665392e4dbae7f389d33dd5`.
- Actual imported file hash was `c3fd7193e56e28df989d35dcc2463b21c16d55d1e8681787d8dd42a81f748a04`.
- Replaying the saved effective spec against the original byte-identical files then failed because the saved review fingerprint belonged to the replacement data. Replacement bytes would instead fail the spec's SHA check.

**Consequence:** a purportedly reproducible completed run can contain correct calculations on data that do not match its declared source identity. This is a local file-consistency defect, not a cybersecurity finding. It does not imply that editing a file after a fully completed preparation should alter an intentionally retained in-memory snapshot.

**Smallest reliable correction:** import from a private, bounded snapshot whose exact bytes are hashed and matched against the spec. Preserve the supported import format/suffix and logical provenance. A post-import rehash detects many concurrent edits, but a verified immutable snapshot establishes that the parser consumed the bytes whose digest is recorded. Add an ordinary concurrent-replacement regression.

### H3 — HIGH: obsolete inspection can restore executable browser state

**Source:** `biostat_tool/web.py:175`, `inspect_callback`; `:246`, `inspect_ui`; `:208`, `analyze_callback`.

The inspection generation check occurs at line 187, **before** issue/metric/alignment table preparation and serialization. The registered wrapper checks only whether the generation moved backwards; normal invalidation increases it. Prepared state carries no web-session generation that analysis validates.

**Minimal deterministic reproduction through installed Gradio:**

1. Dispatch the actual registered `inspect_ui` via `Blocks.call_function`, with a real `gr.Request(session_hash=...)`.
2. While `_metrics_df` prepares the return value, invoke the registered input invalidator `invalidate_ui` for that same request. This schedules invalidation after the existing guard and before the return.
3. Inspection still returns non-null old `PreparedAnalysis` and a non-null spec download, although invalidation had cleared them.
4. Pass that returned state and explicit acknowledgement to the registered `analyze_ui` through `Blocks.call_function`.

Observed result: **“Analysis complete”; four result rows; nonempty preview and downloadable bundle.** The old prepared state is adopted under the newer generation. The calculations themselves match that old state; they are obsolete relative to the input invalidation.

**Consequence:** the supported callback path can restore an inspection that the UI has invalidated and publish results from it. Existing analysis-in-flight guards do not fix stale state accepted at the start of a later analysis.

**Smallest correction:** bind browser prepared state to the inspection's session/generation token; reject it at analysis entry when that token is obsolete. Prepare the entire inspection return value before a final current-generation check, and make the registered wrapper enforce that exact token. Add this interleaving to the maintained registered-callback tests. The reproduction covers the server callback boundary, not a claim of full browser/network scheduling certification.

### M1 — MEDIUM: conflicting duplicate JSON keys silently choose a method

**Source:** `biostat_tool/specs.py:293`, `load_analysis_spec`.

In an otherwise valid spec, replace its analysis member with:

```json
"analysis": {
  "type": "cross_omics_correlation",
  "method": "spearman",
  "method": "pearson"
}
```

`load_analysis_spec` accepts this request as Pearson. The standard `json.loads` last-value behavior removes the conflict before `from_dict` can validate it. Canonical serialization then loses the ambiguity entirely.

**Consequence:** the advertised strict specification parser silently resolves an ambiguous scientific request, potentially selecting a different method from the one its author or another parser expects. Unknown-key rejection otherwise works.

**Smallest correction:** reject duplicate object members during JSON decoding, including nested objects, with a standard-library `object_pairs_hook`. Apply an explicit equivalent policy to the optional YAML adapter; the executable demonstration here is for JSON. This needs no new core dependency and no statistical policy changes.

## Requirement-to-evidence reconciliation

| Requirement | Result | Fresh evidence / limits |
|---|---|---|
| 1. One execution path | PASS | CLI `cmd_validate`/`cmd_run` and web inspection/analysis call the shared `prepare_analysis`/`execute_prepared`. Only the runner delegates inference to the frozen public oracle. No second statistical implementation found. Registered Gradio and CLI tests passed. |
| 2. AnalysisSpec v1 | PARTIAL | Version, unknown root/nested keys, fractional N, Boolean permutation counts and alternate BH family were rejected. Seed/B are serialized; BH scope is fixed. Wrong fingerprint, warning IDs, changed settings and mutated inspected data were rejected. Duplicate JSON members fail strictness (M1); input-read identity has H2. |
| 3. Portable paths | PARTIAL | CLI relocation to byte-identical copies succeeds without rewriting the saved scientific spec or review; altered bytes reject with exit 2 before bundle creation. Web runtime overrides use the same runner. H2 leaves a concurrent-read gap. |
| 4. RunBundle v1 | PARTIAL | Required files, versions, canonical spec hashes, review, alignment and all seven manifest-listed file hashes checked. Report regeneration was byte-identical and source contains no inference call. Injected JSON-write, report-write and final-rename failures left no completed destination or staging directory. Missing-data/constant rows serialize as strict JSON. H1/H2 prevent complete semantic consistency. |
| 5. Frozen oracle protection | PASS for current freeze | Five source hashes match the manifest, hardcoded test expectations and independent accepted v0.2.4 bytes. Wheel source matches. Static Pearson/Spearman fixtures and core tests pass. No source change to Pearson, Spearman, BH, matching, pairwise N or omics guards. |
| 6. Local-first boundary | PASS for defaults | Recorded launch call uses `server_name='127.0.0.1'`, `share=False`; analytics environment defaults to `False` before Gradio import. Explicit host/environment overrides exist. No external statistical service found. No broad browser or network testing performed. |
| 7. Dependency boundary | PASS | JSON/CLI/hashing/filesystem/archive infrastructure uses stdlib. JSON loading succeeded with YAML import deliberately unavailable. Core direct dependencies are NumPy, pandas, SciPy, Gradio and openpyxl; PyYAML is an optional extra. Source and wheel metadata agree. |
| 8. CLI validate/run/replay | PASS for stable inputs | Actual subprocess commands returned 0; completed effective spec replayed without a new acknowledgement flag using relocated inputs. Result CSV bytes were identical. Changed input returned 2 and no bundle. H2 identifies the concurrent-mutation exception. |
| 9. Maintained suite | PASS in available environment | 50 passed, 0 failed, 0 skipped. Python 3.12.14 was available; declared Python 3.13 execution remains unverified here. |

Replay result CSV SHA-256, identical in original/replay bundles:

```text
19400bc2de02dc15b68a52a7de725c5eccd0a64f588a88f107e6529797f82521
```

A separate compact missing-data check reordered B relative to A and returned pairwise N **3** for the nonconstant feature and **4** for the constant feature, with statuses `ok` and `constant_pair`. The maintained core suite also exercised exact/tied Spearman, Monte Carlo add-one behavior, BH arithmetic/invalid inputs, exact alignment, numerical failure handling and omics blocks. This review did not reopen the accepted statistical design.

## What the fixtures establish—and do not

Hardcoded independent expected source hashes are meaningful freeze protection, not hashes regenerated from the current files during each test. Static fixture outputs cover coefficients, p/q, N, status, branch labels and permutation fields for their small fixed datasets; they are not a complete future optimizer equivalence suite. The retained core tests provide additional missingness, tie and MC examples.

Before using the fixtures to gate an optimized implementation, make numerical tolerance intent explicit: the fixture comparisons use `pytest.approx(..., abs=1e-14)` while retaining pytest's default relative tolerance. This is a test-contract clarification, not a demonstrated current statistical defect or a request to change the oracle. Candidate architecture tests do not cover the four reproduced defects.

## Required targeted work before acceptance

1. Preserve literal result identifiers in reports and verify report/CSV identity.
2. Tie imported data to the exact bytes whose mandatory SHA-256 was verified.
3. Reject stale prepared browser state, including invalidation during inspection return preparation.
4. Reject ambiguous duplicate specification members before canonicalization.
5. Add focused regressions for these boundaries; rerun the maintained suite and CLI replay in the declared Python 3.13 environment while keeping all five oracle hashes unchanged.

No new statistical method, automatic transformation, distance correlation, cloud dependency or frozen-oracle rewrite is warranted. Licensing, a wider CI/browser matrix, full dependency locks/containers and retention policy remain separate release-engineering work and do not drive this verdict.
