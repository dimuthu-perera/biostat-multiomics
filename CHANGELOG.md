# Changelog

## 1.0.0 — first public release

Biostat Research Tool v1.0.0 promotes the independently reviewed RC17 behavior to the first public release. No statistical method, inference rule, FDR policy, correlation backend, AnalysisSpec scientific semantics, RunBundle schema, or figure-computation algorithm changed during final promotion.

- Includes the complete RC17 bundled-example declaration guardrail and RC16 dark-mode checkbox correction.
- Preserves the frozen v0.2.4 scalar oracle and all accepted optimized backends.
- Finalizes package, citation, user-documentation, and release metadata at version 1.0.0.
- Synchronizes public repository documentation with the packaged documentation.
- Leaves project-specific video tutorial URLs unconfigured until real published links are supplied.

## 1.0.0-rc17 — bundled-example declaration guardrail

- Added a browser-only teaching guardrail for bundled synthetic examples: when both selected input byte identities exactly match a packaged example but the researcher changes its declared data type or preprocessing state, Readiness now adds an explicit `synthetic_example` WARNING rather than silently trusting the edited catalog declaration.
- The guardrail is exact-byte scoped and is not used to infer preprocessing history for ordinary uploaded datasets.
- Mismatch warnings require browser acknowledgement before analysis; the user's declaration is never silently overwritten. The warning is also recorded as a platform advisory in RunBundle provenance, and browser acknowledgement is recorded in execution metadata.
- Statistical engines, AnalysisSpec semantics, FDR policy, correlation calculations, and figure-generation logic are unchanged from rc16.

## 1.0.0-rc16 — dark-mode checkbox visibility patch

- Fixes U49: checked Gradio checkboxes now render an explicit high-contrast white tick on a green selected surface in dark mode.
- Applies the correction through the shared checkbox styling so warning acknowledgement, heatmap q emphasis, and other checkbox controls use the same visible selected state.
- Statistical methods, inference, AnalysisSpec/RunBundle schemas, computation backends, and visualization calculations are unchanged from rc15.

## 1.0.0-rc15 — live-browser workflow and readability corrections

RC15 addresses the live-browser findings U36–U48 reported after the RC14 combined workstation review. It is a browser/product-layer release candidate; the protected statistical engine, optimized backends, runner, AnalysisSpec, RunBundle, and visualization computation remain byte-identical to RC14.

- Added a compact supported-data visual for metabolomics, proteomics, RNA-seq, 16S/microbiome, metagenomics, and generic biomarker matrices, explicitly covering same-domain and cross-domain workflows.
- Strengthened dark-mode success surfaces and checkbox selected/focus states for visible confirmation.
- Replaced the ambiguous leading-comma missing-token display with an explicit rule that blank cells are always missing while the canonical empty-string token is preserved internally.
- Compressed Dataset A/B declarations into paired rows without removing editable scientific declarations.
- Added browser bounds matching the validated contracts: minimum pairwise N ≥ 3; Spearman Monte Carlo pairings 99–100,000; integer step 1.
- Moved the primary **Inspect & validate inputs →** action to the bottom of Data & design, retained **Re-run inspection** in Readiness, and automatically opens Readiness after inspection.
- Replaced four per-input invalidation callbacks with one unqueued, coalesced state-reset callback to prevent rapid invalid→valid edits from producing a cancellation/cleanup backlog.
- Offset both the header and the complete main workspace beside the persistent 235 px rail so the rail cannot cover Figures or other sections.
- Browser result tables now display correlation coefficients to 2 decimals and p/BH q values to 3 decimals, with values below 0.001 displayed as `<0.001`; CSV/RunBundle values retain full calculated precision.
- Added an NIH reproducibility-guidance citation panel using official text attribution and links without using the NIH logo or implying endorsement.
- Replaced researcher-facing `Backend: auto` wording with **Computation: Automatic** and simple Optimized/Reference execution-engine labels; exact backend identifiers remain in provenance.
- Added RC15 regression coverage for the new layout, display, validation, lifecycle, and terminology contracts.

## 1.0.0-rc14 — workstation visual-polish and context-sensitive figures

RC14 is the combined workstation review candidate. It carries the RC13 research-workstation layout forward and incorporates the live-browser visual findings U28–U35 without changing the validated statistical or provenance core.

- Increased header vertical breathing room and replaced the absolute header controls with a grid so Help/About and Light/Dark/System do not overlap.
- Strengthened dark-theme success/readiness surfaces with darker semantic backgrounds and high-contrast text.
- Preserved the 235 px workflow rail while preventing the open rail from covering the main workspace at narrow widths; the header and content are offset beside the rail.
- Made figure controls context-sensitive: Association shows only pair controls; summary figures show the relevant multi-feature selectors and only the q/heatmap/bubble options they actually use.
- Fixed readiness advisory header/body column alignment with one explicit fixed-width contract shared by all cells.
- Made the batch association report action an unmistakable primary **Generate report** button.
- Added RC14 UI regressions for header/theme layout, dark status contrast, sidebar offset, context-sensitive figure controls, readiness-table alignment, and batch-report action visibility.
- Maintains the RC13 curated browser result table while retaining the full technical result schema in CSV exports.

The correlation engine, optimized backends, runner, AnalysisSpec implementation, RunBundle implementation, original correlation analysis module, and visualization computation are byte-identical to RC13.

## 1.0.0-rc13 — research workstation layout and learning surfaces

RC13 is a researcher-facing layout candidate built on RC12. It preserves the validated correlation engine, optimized backends, runner, AnalysisSpec semantics, RunBundle implementation, and visualization computation while reorganizing the browser application into a denser research-workstation layout.

- Added a persistent left workflow/navigation rail for Data & design, Readiness, Analysis, Results, Figures, and Provenance.
- Removed the duplicate visible top-level tab navigation; the analytical workspace now uses the left rail as its primary navigation.
- Added Quick start, Video tutorials, Documentation, and About sections outside the six-step analysis workflow.
- Added top-header Help and About shortcuts.
- Reworked dark mode into a coherent two-tone dark palette with explicit native Gradio surface coverage.
- Reworked the Figures page into a compact control sidebar plus a larger figure stage.
- Curated the browser result preview to the key scientific columns (features, method, correlation, pairwise N, p, BH q, status) while retaining the complete technical schema in the downloadable CSV.
- Added result-table header sizing/wrapping rules to prevent character-by-character column headings.
- Tightened layout spacing without changing minimum interactive control sizes or contextual-help behavior.
- Added RC13 workstation-layout regression coverage.
- Project-specific YouTube tutorial slots are present but intentionally have no invented external URLs; links can be populated when the project videos are published.

No statistical method, inference result, AnalysisSpec schema, RunBundle schema, or figure-computation algorithm changed.

## 1.0.0-rc12 — request-replacement state safety and coherent dark theme

RC12 is a targeted follow-up to RC11. It preserves RC11's user-only invalidation listeners while restoring one coordinated invalidation when a synthetic example or saved AnalysisSpec successfully replaces the active request. Successful replacement now advances the session generation exactly once, removes prior artifacts, clears prepared/completed browser state, resets acknowledgement and outputs, and requires fresh inspection. Malformed or missing restore input remains non-destructive.

RC12 also corrects the live dark-theme mismatch found during manual inspection by switching Gradio's native `.dark` theme class together with the application's custom theme class and by supplying explicit dark surface/input/table variables. This prevents light Gradio accordion/form surfaces from remaining inside an otherwise dark application.

- Added request-replacement regressions covering stale prepared/completed state, artifact cleanup, restored identity replacement, and in-flight analysis supersession.
- Added registered dependency checks for atomic success cleanup after Load Example / Restore.
- Added dark-theme integration checks for Gradio's native dark class and full surface variables.
- No statistical method, inference result, AnalysisSpec schema, RunBundle schema, or correlation backend changed.

## 1.0.0-rc11 — synthetic-example event-cascade correction

RC11 is a narrow browser-workflow follow-up to RC10. It fixes the live-browser loading cascade observed when a synthetic example programmatically populated many analysis inputs. Gradio `change` listeners had treated those callback-driven updates like separate user edits, queuing repeated invalidation/clearing work. RC11 registers invalidation on user-originated `input` events and File upload/delete/clear events instead. User edits still invalidate stale state; coherent example/spec population no longer fans out through the invalidation queue.

- Added two RC11 regressions for event registration and the registered example-load callback.
- No statistical method, inference result, AnalysisSpec semantics, RunBundle logic, or figure computation changed.

## 1.0.0-rc10 — targeted post-RC9 release corrections

RC10 addresses the four reproducible defects reported in the independent RC9 re-check. It does not change the correlation engine, optimized backends, runner, AnalysisSpec semantics, or RunBundle implementation.

- Bubble-plot Y coordinates now preserve the exact `-log10(BH q)` value for every positive q-value. Marker-size capping is independent of position; `q = 0` is handled explicitly with a disclosed finite display position.
- The two-stage association selector can now render every eligible analyzed pair even when the quick-search list is capped at 5,000 ranked pairs. The UI now labels that list as a 5,000-pair shortcut rather than claiming complete coverage.
- Correlogram triangular display now requires explicit same-variable-space identity. Matching feature names plus a numerically symmetric A×B result matrix are no longer sufficient; ordinary cross-dataset selections remain rectangular.
- Batch association-report message/PDF/ZIP outputs now clear with other visualization artifacts on input invalidation and fresh inspection, preventing stale links to removed files.
- Added four RC10 targeted regressions. The maintained suite now contains 172 tests.

## 1.0.0-rc9 — researcher usability and visualization redesign

RC9 incorporates the complete live-browser usability inspection (U1–U23) while preserving the validated inference engine, runner, AnalysisSpec semantics, and RunBundle implementation.

- Corrected header contrast, compact spacing, containment, readiness-table wrapping, and colorbar/legend clipping.
- Added Light / Dark / System display themes and collision-aware contextual help.
- Added readiness severity definitions and visible PASS / INFO / WARNING / BLOCKED states.
- Made inspection and blocked-analysis state changes explicit; blocked runs keep the analysis button disabled.
- Made the three input paths collapsible and reframed AnalysisSpec/RunBundle terminology in plain language.
- Replaced internal underscore-style selection labels with researcher-facing labels while retaining canonical internal values.
- Added same-domain synthetic examples for metabolomics, RNA-seq, and proteomics.
- Made missing AnalysisSpec restoration non-destructive instead of marking many controls as Error.
- Added two-stage/searchable association selection for large result sets.
- Added combined Top-N association PDF reports plus ZIP export of individual PNGs and a CSV index.
- Added choice-level help and concrete explanation for Minimum pairwise N and scatter-matrix limits.
- Redesigned correlogram as a color-cell matrix with values/significance when readable and symmetric half-triangle handling.
- Redesigned bubble plot as a true continuous scatter-style bubble plot: x = correlation, y = -log10(BH q), bubble area configurable by effect magnitude or statistical evidence.
- Added rendered-bounds checks for summary-figure colorbar labels.
- Added RC9 acceptance coverage; maintained suite now contains 168 tests.

## 1.0.0-rc8 — guided workflow and contextual help

RC8 is a researcher-facing usability candidate built on the independently cleared RC7 statistical/platform behavior. It adds no new statistical method and changes no inference definition.

- Added a persistent six-step workflow guide: load data → inspect readiness → run analysis → review results → create figures → verify provenance.
- Numbered the three primary execution actions so the required run sequence is explicit.
- Made successful synthetic-example loading visually unmistakable with a check-marked loaded state.
- Added accessible contextual help bubbles for technical controls. Help opens on mouse hover, keyboard focus/Enter, and tap/click.
- Added visualization empty-state instructions and an explicit **Download this figure** heading for each of the five figure workflows.
- Preserved semantic component labels while suppressing duplicate visual labels where the help-enabled label is shown.
- Added five RC8 UI regressions; maintained suite is 162 tests.

## 1.0.0-rc7 — browser-preview long-identifier containment

RC7 is a narrow follow-up to the independent RC6 re-check. It completes M2 for the browser preview without changing statistical definitions, inference, provenance, AnalysisSpec behavior, RunBundle integrity, or visualization lifecycle guards.

### Visualization layout
- Pair-plot titles now wrap from actual rendered glyph width rather than character-count heuristics, including pathological wide unbroken identifiers.
- Pair figures expand vertically only when the measured wrapped title requires additional native-canvas space, so Gradio's native-canvas preview retains the complete identifiers instead of clipping them.
- Pair-label layout explicitly checks the rotated Y-axis label's lower canvas boundary in addition to header and left-edge clearance.
- Axis display-label abbreviation behavior and complete-identifier retention in the title are unchanged.

### Validation
- Added two Gradio `Plot.postprocess()` regressions for `"X" * 240` and `"W" * 240`, asserting title/subtitle/X/Y label bounds are inside the native canvas and that the browser preview uses that complete canvas.
- Full maintained suite: **157 passed, 0 failed, 0 skipped** on Python 3.13.5.
- Frozen oracle hash verification remained **OK**.

## 1.0.0-rc6 — targeted pair-axis layout correction

RC6 is a narrow follow-up to the independent RC5 re-check. It corrects the remaining M2 visualization defect without changing the statistical engine, AnalysisSpec behavior, RunBundle integrity logic, provenance enforcement, or visualization lifecycle guards.

### Visualization layout
- Exceptionally long pair-plot axis identifiers now use bounded, explicitly identified display labels while complete feature identifiers remain in the figure-level title.
- Both whitespace-delimited and unbroken identifiers are wrapped/truncated for axis display, and Spearman rank-space display labels retain the `average rank` meaning.
- Pair layout now measures rendered X/Y axis-label bounds and reserves canvas/header clearance; it raises instead of silently collapsing the plotting region below a usable height.

### Validation
- Added three RC6 regressions covering the repeated long-identifier reproduction, a 240-character unbroken identifier, export clipping/bounds, and long-name Spearman `average rank` labeling.
- Full maintained suite: **155 passed, 0 failed, 0 skipped** on Python 3.13.5 in the original RC6 validation run.
- Frozen oracle hash verification remained **OK**.

## 1.0.0-rc5 — targeted release corrections after combined RC4 review

RC5 addresses the reproducible release defects reported in the independent combined RC3/RC4 review without changing the frozen statistical oracle or accepted optimized correlation backends.

### Provenance and lifecycle
- Restored AnalysisSpecs now retain their expected Dataset A/B SHA-256 identities in session-scoped server state. Selected source bytes are compared with those recorded identities before inspection proceeds; modified bytes are blocked rather than silently replacing the restored hashes.
- Byte-identical relocated/renamed files remain valid because identity is based on content hash, not filename. A dedicated **Start new request** action clears restored identity when different source bytes are intentional; loading a bundled synthetic example also clears restored identity.
- All visualization workflows now recheck session generation before export, after export, and again at UI publication. Superseded work is suppressed and any artifact root recreated by an in-flight stale export is removed.

### Visualization correctness
- Pairwise plot extraction preserves exact supported int64 measurements through pairwise selection. Spearman rank-space plotting therefore retains distinctions above `2**53` and continues to use average ranks for genuine ties. Raw plots explicitly refuse integer coordinates that binary64 rendering would collapse.
- Figure headers now reserve vertical space from measured rendered text extents instead of assuming a fixed one/two-line title height.
- Correlogram and bubble annotations now state the implemented minimum-size/nonlinear marker-area formulas rather than claiming direct area proportionality.
- SVG export applies `svg.fonttype=none` during `savefig()`, preserving editable `<text>` elements.

### Validation
- Added 12 targeted RC5 regressions for restored-hash enforcement (including registered Gradio `Blocks.process_api`), intentional new-request behavior, in-flight invalidation for pair/heatmap/correlogram/bubble/scatter-matrix exports, final UI publication suppression, large-integer Spearman ranks/ties, long-label rendered overlap, marker-area wording, and SVG text preservation.
- Full maintained suite: **152 passed, 0 failed, 0 skipped** on Python 3.13.5 with the declared reference package versions.
- Frozen oracle hash verification remains **5/5 OK**.

## 1.0.0-rc4 — combined product-completion and scientific-visualization review candidate

This is the first candidate intended for a single external review covering the previously unreviewed RC3 product-completion work plus the visualization/UX additions developed afterward.

### Product completion carried forward from RC3
- Added explicit compute-readiness checks and visible hard limits before analysis: 250,000 planned A×B correlations, 10,000 matched samples, 5,000,000 cells per dataset, and 100 MiB per source file.
- Added feature-level QC/data-dictionary output, alignment transparency, custom missing-token declarations, direct CSV/report downloads, browser AnalysisSpec restoration, and deterministic teaching examples.
- Added per-pair association exploration using the exact pairwise-complete observations used by the stored statistic, with pairwise-N equality checks before rendering.
- Added local session-tracked plot/export artifacts and privacy wording for sample-level visualizations.

### Scientific visualization workspace
- Reorganized the browser into **Data & design → Readiness → Analysis → Results → Visualize → Provenance**.
- Replaced internal engineering wording with **Analysis readiness** and a secondary **Supported analysis limits** section.
- Added shared feature selection across visualization views.
- Added cross-omics heatmap, correlogram, and bubble-plot result views based only on already validated A×B result rows.
- Added a scatterplot matrix for 2–9 selected variables. Raw exploratory panels may show any selected measurements, but inferential annotations appear only for validated A×B result pairs already in the result table; no within-omics inferential tests are created.
- Added a shared publication-oriented figure theme with consistent signed-correlation encoding.
- Added PNG (300 dpi), SVG, and PDF export for every formal figure.
- Added visualization limits: heatmap ≤60 features/axis, correlogram ≤30/axis, bubble ≤600 selected eligible A×B associations, scatter matrix ≤9 total variables.
- Added six deliberately distinct teaching relationships: positive linear, negative linear, monotonic nonlinear, outlier-sensitive, null, and missing-data patterns.
- Added a fixed figure-level title/subtitle header band so statistical subtitles cannot collide with plot titles; long titles wrap and reserve extra header height.

### Statistical scope
- No change to the frozen scalar oracle or accepted optimized Pearson/Spearman backends.
- No change to AnalysisSpec semantics, the central runner, RunBundle integrity model, BH correction, pairwise-N semantics, sample alignment, omics guardrails, or deterministic Spearman inference policy.

## 1.0.0-rc3 — product-completion prototype (not externally reviewed)

- Added resource-safety preflight, direct results/report downloads, alignment visibility, feature-level QC, browser AnalysisSpec loading, explicit missing-value token controls, pair correlation plots, and the Pearson-vs-Spearman teaching dataset.
- Added PNG/SVG/PDF plot exports and session cleanup for generated artifacts.
- This prototype was not sent for external review; its functionality is included in the combined RC4 candidate above.

## 1.0.0-rc2 — targeted release/privacy corrections

- Corrected Load Example preprocessing-choice updates through registered Gradio callbacks.
- Corrected browser download-cache lifecycle by keeping Biostat-generated artifacts in session-tracked local cache paths and documenting cleanup boundaries.
- This candidate was externally accepted for the two targeted fixes, before the later RC3 product-completion expansion.

## 1.0.0-rc1 — product completion release candidate

### Added
- Product-stage browser workflow with synthetic-example loading, omics-aware preprocessing choices, explicit data-readiness inspection, results/RunBundle stage, privacy notice, and local temporary-artifact cleanup on input invalidation/new inspection.
- Deterministic synthetic library covering metabolomics, transformed RNA-seq, proteomics, metagenomics CLR, 16S CLR, and generic quantitative data, plus blocked raw-count/relative-abundance guardrail examples and truth metadata.
- Packaged user documentation (`METHODS`, `PRIVACY`, examples, release checklist) available inside the installed wheel.
- MIT `LICENSE`, `CITATION.cff`, cross-platform Python 3.13 GitHub Actions workflow, frozen-oracle verification script, and exact reference-environment lock.

### Changed
- Normal CLI/browser backend selection is now `auto` after independent acceptance of v0.4.0-v0.4.2 optimized subsets; unsupported cases transparently fall back to the frozen scalar oracle. The Python API retains its historical reference default.
- Browser version labeling now reflects the installed package version rather than stale v0.3 text.
- Conda environment name and release documentation updated for v1 preparation.

### Frozen
- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No change to Pearson/Spearman definitions, Spearman inference policy, BH arithmetic, sample matching, pairwise-N semantics, seed logic, or omics guardrails.

## 0.4.2 — complete-data Spearman pre-ranking backend

### Added
- `optimized_spearman_v0.4.2` for complete aligned Spearman analyses.
- Feature-level rank reuse: each nonconstant feature is ranked once, while the frozen oracle's exact positional permutations, Monte Carlo null generator/PCG64 seed derivation/add-one correction, asymptotic SciPy branch, and global BH implementation are reused unchanged.
- Explicit complete-data Spearman eligibility and missing-data fallback to the frozen scalar reference.
- Cross-check coverage for exact N<=8, Monte Carlo 9<=N<=500, tied Monte Carlo above 500, untied asymptotic N>=501, constant pairs, and bundle provenance.
- `docs/PERFORMANCE_BACKEND_V042.md` and focused performance review materials.

### Validation
- 100 maintained tests pass on the development Python 3.13 environment.
- A 120-case independent complete-data Spearman sweep (720 result rows) matched the frozen scalar oracle exactly for estimates, p-values, q-values, branch labels, permutation/extreme counts, tie flags, family counters and deterministic metadata.
- Default reference execution retains the accepted static Spearman CSV SHA-256 `3b972d8e6223464bde0ecb1c082de27f4ae969f8db15199e7eec2673feb13f9e`.
- Frozen oracle source hashes remain 5/5 unchanged.

### Scope
- Spearman with missing values remains on the frozen reference backend.
- Pearson optimized behavior from accepted v0.4.1 is unchanged.
- Backend choice remains runtime execution provenance and is not added to AnalysisSpec.


## 0.4.1 — optimized Pearson with reusable pairwise-missing masks

### Added

- `optimized_pearson_v0.4.1`, extending the independently accepted complete-data Pearson backend to pairwise-missing Pearson when exact observed-sample masks are sufficiently reusable.
- Exact mask-class grouping using aligned nonmissing positions; `n_pairwise`, insufficient-N status, and constant-pair status are preserved pair-by-pair.
- Pairwise-subset affine stabilization keyed by exact mask and feature, rather than incorrectly reusing a whole-feature transform across different pairwise subsets.
- Deliberate fallback for highly fragmented/random missingness instead of forcing a slower or harder-to-audit vectorized path.
- Maintained regressions for randomized structured missingness, pairwise-subset constants, insufficient N, one global BH call, public-runner optimized execution, and fragmented-mask fallback.
- `docs/PERFORMANCE_BACKEND_V041.md` and a focused performance v0.4.1 review materials.

### Performance boundary

- Complete-data Pearson continues through the accepted v0.4.0 vectorized kernel.
- Structured/reused pairwise missingness can use the v0.4.1 mask-grouped kernel.
- Spearman, unsafe exact integer precision, highly fragmented missingness, or any unsupported numerical condition continue through the frozen reference backend.
- BH is still called once globally after all eligible raw p-values are assembled; it is never applied per mask group.
- CLI default remains `reference` for this review candidate.

### Compatibility

- RunBundle verification accepts the historical `optimized_complete_pearson_v0.4.0` backend identifier and the new `optimized_pearson_v0.4.1` identifier.
- Backend selection remains runtime-only and does not alter AnalysisSpec.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson/Spearman statistical definitions, exact/Monte Carlo Spearman policy, BH arithmetic, sample matching, pairwise N semantics, deterministic seeds, omics guardrails, or Statistical Policy v1.0.

## 0.4.0 — bounded optimized complete-data Pearson backend

### Added

- Runtime execution backends: `reference`, `optimized`, and `auto`; backend selection is intentionally outside AnalysisSpec.
- `optimized_complete_pearson_v0.4.0`, limited to validated complete-data Pearson runs.
- Bounded vectorized Pearson blocks reusing the frozen v0.2.4 per-feature affine stabilization and SciPy beta-null p-value implementation.
- Explicit optimized-vs-reference equivalence contract with fixed absolute/relative tolerances and exact metadata/family checks.
- `--verify-against-reference` CLI mode that independently executes the frozen oracle and blocks completion on equivalence failure.
- RunBundle execution provenance recording requested/actual backend, fallback reason and reference-verification result.
- Performance/equivalence benchmark script and maintained randomized/stress regressions.

### Safety boundary

- All Spearman analyses fall back to the frozen reference backend.
- Pearson with any aligned missingness falls back to the frozen reference backend.
- Exact integers above `2**53`, stabilization failures, or vectorized numerical warnings fall back to/reference-preserve the frozen behavior.
- BH is still applied once globally after all eligible pairs; it is never applied per chunk.
- CLI default remains `reference` for this review candidate.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson/Spearman statistical definitions, exact/Monte Carlo policy, BH arithmetic, sample matching, pairwise N, deterministic seeds, omics guardrails or Statistical Policy v1.0.

## 0.3.5 — provenance isolation and mandatory semantic authority

### Fixed

- Completed inspection/alignment documents and the retained executed-oracle manifest no longer share nested mutable containers; caller-visible metadata mutation cannot rewrite the semantic reference used by RunBundle verification.
- `verify_run_bundle()` now requires the executed frozen-oracle metadata for current correlation RunBundle v1 bundles. Removing `provenance.json` → `oracle` (or its manifest) is a verification error rather than a silent downgrade to hash-only checks.
- Added regressions for nested `common_order` mutation and for removing executed-oracle metadata while recomputing inventory hashes.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson, exact/Monte Carlo Spearman, BH, exact sample matching, pairwise missing masks/N, deterministic seeds, or omics guardrails.

## 0.3.4 — AnalysisModule provenance consistency correction

### Fixed

- Completed correlation inspection/alignment documents are rebuilt from the freshly revalidated frozen-oracle execution (`oracle_run.inspected`) rather than copied from caller-visible prepared mappings.
- RunBundle verification now cross-checks `inspection.json`, `alignment.json`, run fingerprint, source hashes, and FDR-family metadata against the executed frozen-oracle manifest in `provenance.json`.
- A bundle whose file hashes are internally self-consistent but whose inspection/alignment metadata disagree with the executed run is rejected before atomic publication.
- Added maintained regressions for the exact v0.3.3 review reproduction and for post-execution metadata mutation before bundle publication.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson, exact/Monte Carlo Spearman, BH, exact sample matching, pairwise missing masks/N, deterministic seeds, or omics guardrails.

## 0.3.3 — formal AnalysisModule boundary

### Added

- Formal `AnalysisModule` abstract contract and analysis-type registry.
- Standardized `PreparedAnalysis`, `CompletedAnalysis`, `AnalysisSummary`, and engine-identity records.
- `CorrelationAnalysisModule` wrapper around the unchanged v0.2.4 scalar oracle.
- `biostat modules` command for introspecting registered analysis modules.
- Statistical policy v1.0 as a non-numerical provenance/reporting layer.
- Browser starting default `minimum_pairwise_n=10`, while retaining the frozen algorithmic hard minimum of 3 for explicit advanced/reproducibility use.
- Non-gating low-N policy caution and explicit `unadjusted_marginal_association` interpretation advisory.
- Pairwise-N summary and policy section in HTML reports.
- `docs/ANALYSIS_MODULE_CONTRACT.md` and `docs/STATISTICAL_POLICY_V1.md`.

### Changed

- The central runner now performs module dispatch only; it no longer contains correlation import/inspection/inference logic.
- RunBundle construction consumes standardized module outputs for inspection, alignment, primary results, result schema, engine identity, and provenance.
- Report loading follows the primary result paths declared by the RunBundle manifest.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson, exact/Monte Carlo Spearman, BH, exact sample matching, pairwise missing masks/N, or omics guardrails.

## 0.3.2 — architecture boundary corrections

### Fixed

- Report rendering now preserves literal feature identifiers using `results/schema.json`; values such as `001` and `NA` are no longer reinterpreted by pandas.
- Input preparation now parses a private snapshot whose bytes are hashed while copying and matched to the AnalysisSpec before import. RunBundle input byte counts/hashes come from that verified snapshot identity rather than a later `stat()` of the mutable source path.
- Web prepared state is bound to the exact browser session and inspection generation; invalidation during inspection return preparation suppresses the obsolete state, and stale prepared state is rejected at analysis entry.
- Canonical JSON parsing rejects duplicate keys at any nesting level before `AnalysisSpec` canonicalization; optional YAML loading applies the same rule.
- Added maintained regressions for all four findings reproduced in the independent v0.3.0 architecture review.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson, exact/Monte Carlo Spearman, BH, exact matching, pairwise N, or omics guardrails.

## 0.3.1 — RunBundle v1 contract candidate

### Added

- Formal immutable RunBundle v1 contract.
- Generic `manifest.json` inventory separated from correlation-specific `provenance.json`.
- `results/schema.json` with machine-readable result-table column semantics.
- Full bundle content inventory with SHA-256 and byte counts.
- `verify_run_bundle()` API and `biostat verify` CLI command.
- Packaged RunBundle manifest JSON Schema and `biostat bundle-schema` command.
- Cross-file verification of AnalysisSpec hashes, input identities, run fingerprint and result schema.
- Integrity validation before atomic RunBundle publication and before ZIP packaging.
- Portable AnalysisSpec path rules: dataset paths and output root must be logical relative POSIX paths.
- RunBundle tamper/unlisted/missing-file regression tests.

### Changed

- Published RunBundles are treated as immutable.
- `biostat report` returns the bundled report by default instead of rewriting it; exported report copies must be outside the bundle.
- Raw source datasets and resolved absolute source paths remain outside the bundle by design.
- Platform version advances to 0.3.1; RunBundle schema remains independently versioned at 1.0.

### Frozen

- `correlation_tool/` remains byte-for-byte identical to independently accepted v0.2.4.
- No changes to Pearson, exact/Monte Carlo Spearman, BH, sample alignment, pairwise N or omics guardrails.

## 0.3.0 — platform architecture candidate

- Introduced AnalysisSpec v1, central runner, first-class CLI/web paths, initial RunBundle output, local-first defaults and permanent v0.2.4 oracle fixtures.

## 1.0.0-rc3 — product-completion candidate

- Added explicit, visible resource preflight and documented validated limits (250,000 pairs, 10,000 samples, 5,000,000 cells per dataset, 100 MiB per source file).
- Added explicit per-dataset missing-token declarations.
- Added feature-level QC/data-dictionary and exact sample-alignment detail views.
- Added direct full-results CSV and HTML-report browser downloads.
- Added an on-demand association explorer with Pearson raw scatter + least-squares line, Spearman raw/rank-space views, and PNG/SVG export.
- Plot generation verifies pairwise-complete N against the stored statistical result before rendering.
- Added AnalysisSpec settings loading and a deterministic Pearson-vs-Spearman teaching example.
- Browser preview is capped at 500 rows; bulk automatic plot generation remains intentionally unavailable.
- No accepted statistical oracle/backend implementation changed.
