# Omics Correlation Tool v0.2.4 — focused acceptance check

**READY FOR PERFORMANCE OPTIMIZATION**

**Ready to freeze the scalar oracle and proceed to platform/performance work within the checked scientific-software scope.** No reproducible HIGH/CRITICAL correctness defect was found in this acceptance check. The prior H1 reproduction is closed, and the stale test assertion is corrected. No software or statistical redesign is recommended.

## Target and scope

Latest attachment: `correlation-tool-v0.2.4-candidate(2).zip`, byte-identical to `correlation-tool-v0.2.4-candidate(1).zip`.

SHA-256: `79025e64090c8266b8b44a67ae71ade5ed1ed17d9726aebb508e142a6cf99f67`.

Baseline: the included v0.2.3 independent audit and the previously audited v0.2.3 source. Verification followed the Code Verification skill: read-only candidate inspection, existing tests, and reuse of the prior focused import/oracle probes. No candidate source, tests, configuration or dependencies were changed. No security testing or search outside the requested scientific correctness questions was performed.

## Requirement-to-evidence results

| Requirement | Fresh evidence | Result |
|---|---|---|
| Close the prior relationship-target mismatch in both orientations | Loaded the exact prior rows/columns fixtures with `load_workbook` replaced by a call-detection sentinel. Both raised structured `MatrixFormatError`; parser call count was zero. | **Pass** |
| Consistent raw inspection and loaded worksheet for supported input | `_referenced_xlsx_worksheet_parts` reads workbook sheet IDs and relationships, normalizes the referenced target, requires the supported worksheet location, and returns that part for preflight. Standard-path imports and complete expected values passed. | **Pass within checked contract** |
| Reject unsupported structures before inference | Standard-path formula/merge and oversized-coordinate cases rejected before workbook construction. Prior nonstandard target rejected before construction. Archive-budget checks also rejected before parsing. | **Pass** |
| Preserve content despite inaccurate dimensions | 18 orientation/dimension/content combinations covered understated, absent and overstated dimensions, ordinary data, duplicate IDs and formulas. Complete expected imports or required rejection occurred. | **Pass** |
| Maintained coverage includes both orientations | The new relationship-target regression is parameterized over `samples_rows` and `samples_columns`; independent probes exercised both as well. | **Pass** |
| Statistical algorithms remain unchanged | `analysis.py` has the same parsed function/class definitions as v0.2.3; `align_samples` is structurally identical; inspection/declaration source is byte-identical. Compact independent numerical checks passed. | **Pass** |
| Existing suite passes with corrected assertion | `python -m pytest -o addopts='' -q`: **60 passed in 7.33s**, exit code 0. | **Pass** |
| Version/provenance consistency | Package, project metadata, manifest engine and schema report 0.2.4. Completed UI manifest includes the new relationship policy and matching acknowledgement fingerprint. | **Pass** |

Specification verdict: **Pass for the checked requirements**. Engineering-quality verdict: **No material correctness finding within this narrow acceptance scope**. This is acceptance of the scalar reference baseline, not a claim of exhaustive malformed-file or platform certification.

## Exact H1 verification

Source locations:

- `correlation_tool/io.py::_referenced_xlsx_worksheet_parts`
- `correlation_tool/io.py::_normalize_workbook_target`
- `correlation_tool/io.py::_preflight_xlsx_worksheet_xml`
- `correlation_tool/io.py::_read_xlsx`

Both original fixtures contain a workbook relationship targeting `/xl/data/matrix.xml`, with an unrelated conventional worksheet member. Previously, preflight scanned the unrelated member while openpyxl loaded the actual matrix and erased a formula during merge processing.

Both now produce:

```text
MatrixFormatError: Unsupported XLSX worksheet relationship target '/xl/data/matrix.xml'.
Worksheets must use the standard xl/worksheets/*.xml location.
```

The sentinel recorded **zero `load_workbook` calls** in each orientation. Thus the original data-loss mechanism cannot reach workbook construction or inference in these reproductions.

Source inspection confirms that the returned referenced worksheet part, rather than a directory-wide filename selection, is passed to raw XML preflight. The implementation requires one workbook sheet entry, rejects an external or non-worksheet relationship for that entry, and checks that its normalized target is present at the supported location. Ordinary workbook relationships unrelated to the worksheet, such as styles, are not incorrectly prohibited.

## Unchanged statistical and UI behavior

Fresh compact oracle evidence:

| Component | Cases | Result |
|---|---:|---|
| Pearson | 65 binary64 stress cases | Maximum absolute coefficient error 2.22e-16; beta-p error 1.53e-15 against the represented-value reference |
| Exact Spearman | 18 tied/untied cases, N=3–8 | Independently enumerated exact p-values agree exactly |
| Monte Carlo Spearman | 12 tied/untied cases, N=9/15/40, two seeds | Independently reconstructed exceedance counts and add-one p-values agree exactly; deterministic reruns agree |
| BH | 53 arrays | Maximum discrepancy 2.22e-16; tested NaN/ordering/tie and invalid-value handling preserved |
| Alignment, pairwise N, global correction | 10 sample scenarios; 120 pair rows | Exact pairing, pairwise N and global method-specific BH results agree |

Pairwise masking/N and global BH live in the unchanged analysis implementation. There is no change to the validated inference methods or omics declaration scope.

The registered `inspect_ui`, `analyze_ui`, `invalidate_ui` wrappers and their internal inspection/analysis/invalidation callbacks are structurally identical to v0.2.3. The fresh maintained suite includes passing real-request injection, two-session generation separation, computation/bundle invalidation, and late-preview regression tests. This acceptance check found no reproduced stale-result defect; it did not repeat broad browser compatibility testing.

## Tests, versions and provenance

The previous Spearman-policy test now matches the current error text. The threshold restriction still rejects unsupported overrides. The actual suite output is **60 passed**, rather than a claim inferred from the validation document.

Verified versions:

- `correlation_tool.__version__`: **0.2.4**
- `pyproject.toml` project version: **0.2.4**
- completed manifest engine/schema: **0.2.4**

The manifest's relationship policy is:

```text
single_standard_xl_worksheets_target_resolved_and_preflighted_before_openpyxl
```

That description agrees with the checked implementation and H1 rejection. Raw formula/merge policies, exact imported sample order, content/source hashes, declarations and fingerprint-bound acknowledgement remain present. Unchanged numerical algorithm identifiers retain v0.2.1 intentionally; preserving them preserves the existing Monte Carlo seed recipe.

## Execution limits and later release work

Executed on Python **3.12.14**, NumPy **2.3.5**, pandas **2.2.3**, SciPy **1.17.0**, Gradio **6.5.1**, openpyxl **3.1.5**, pytest **9.0.2**. The package declares Python 3.13; this check does not independently certify its Python 3.13 build/install path. No dependencies were installed or changed. The candidate's source bytes were verified unchanged after execution.

License selection, a supported-interpreter/platform CI matrix, full environment lock/container, successful-artifact retention and broader browser compatibility are subsequent release-engineering work. None produced a demonstrated correctness/integrity failure here, and none is being used to withhold scalar-oracle acceptance.

Freeze this candidate's source hash, dependency baseline and reference outputs before optimization. Preserve exact matching, pairwise masks/N, inference labels and deterministic seeds, and one global BH family when comparing faster implementations.
