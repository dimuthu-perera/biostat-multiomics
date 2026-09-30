# Validation record — Biostat Research Tool 1.0.0-rc15 live-browser UX candidate

RC15 addresses the live-browser inspection findings U36–U48 reported after RC14. It is intentionally a browser/product-layer candidate. No statistical method, inference rule, AnalysisSpec schema, RunBundle schema, correlation backend algorithm, or visualization-computation algorithm was changed.

## Change boundary

Changed product-layer files include `biostat_tool/web.py`, release metadata/documentation, and browser/product regression tests.

The following protected scientific/platform files are byte-identical to the RC14 review package:

- `biostat_tool/modules/correlation.py`
- `biostat_tool/modules/correlation_backends.py`
- `biostat_tool/runner.py`
- `biostat_tool/bundle.py`
- `biostat_tool/specs.py`
- `correlation_tool/analysis.py`
- `biostat_tool/visualization.py`

## RC15 corrections

RC15 incorporates the complete live-browser follow-up set U36–U48:

- **U36:** adds a compact supported-matrix visual covering metabolomics, proteomics, RNA-seq, 16S/microbiome, metagenomics, and generic biomarkers, with same-domain and cross-domain scope stated explicitly.
- **U37:** forces the synthetic-example success/confirmation surface and its inner Gradio Markdown wrappers to use a dark green semantic surface with high-contrast text in dark mode.
- **U38:** removes the ambiguous leading comma from the visible missing-token field. Blank/empty cells are explicitly documented as always missing; the canonical empty-string token is still inserted internally.
- **U39:** compacts Dataset A/B declarations into aligned two-column rows while retaining all editable declarations and help text.
- **U40:** Minimum pairwise N uses an integer browser control with minimum 3, step 1, default 10, and matching researcher-facing guidance. Backend validation remains authoritative.
- **U41:** Spearman Monte Carlo pairings uses an integer browser control bounded 99–100,000, step 1, default 9,999, matching the scalar-reference validation contract.
- **U42:** the primary `Inspect & validate inputs →` action is at the bottom of Data & design; Readiness retains a secondary `Re-run inspection` action; successful/failed inspection completion opens Readiness for review.
- **U43:** analysis-defining user edits now use one lightweight, unqueued, coalesced invalidation/reset callback instead of four separate queued callbacks per edit. The callback performs one generation bump and clears stale analysis/visualization state while cancelling in-flight work.
- **U44:** both the header and complete `#biostat-main-tabs` workspace are offset beside the persistent rail whenever it is open, preventing Figures and other pages from rendering underneath it.
- **U45:** dark-mode checkboxes use a high-contrast accent and visible keyboard focus ring.
- **U46:** browser result display uses 2 decimals for correlation and 3 decimals for p/BH q, with values below 0.001 displayed as `<0.001`. The source result DataFrame, downloadable CSV, RunBundle, and statistical decisions retain full calculated precision.
- **U47:** Documentation includes an NIH reproducibility-guidance text citation and official link plus a no-endorsement disclaimer. No NIH logo asset is used.
- **U48:** researcher-facing UI terminology uses `Computation: Automatic` and `Computation engine: Optimized/Reference`; exact backend IDs remain in technical provenance and RunBundle metadata.

## Regression results

Environment used for this validation:

- Python 3.13.5
- NumPy 2.3.5
- pandas 2.2.3
- SciPy 1.17.0
- Gradio 6.5.1
- Matplotlib 3.10.8
- openpyxl 3.1.5
- pytest 9.0.2

The maintained suite collects **205 tests**. Because the complete Gradio-heavy suite can exceed one monolithic execution window in this environment, it was executed in two exhaustive groups covering every collected test file.

- Group 1: oracle, analysis-module/spec/backend, product/lifecycle, RC10–RC15, RC3, and RC4 combined-workspace tests — all passed.
- Group 2: remaining visualization, usability, RunBundle, CLI, policy, shared-runner, and core tests — all passed.
- Combined result: **205 passed, 0 failed, 0 skipped**.
- `python scripts/verify_oracle_hashes.py` reports **Frozen oracle hashes: OK**.

## RC15-specific regression coverage

`tests/platform/test_rc15_live_ux_corrections.py` adds 13 checks covering:

1. supported-matrix scope visual and named modalities;
2. dark example-success surface inheritance;
3. human-readable missing-token display with canonical blank preservation;
4. compact dataset-declaration layout contract;
5. minimum pairwise N browser bounds;
6. Spearman pairing browser bounds;
7. Data-tab inspection action and Readiness re-inspection action;
8. one unqueued backend invalidation callback per user input event;
9. complete workspace offset beside the persistent rail;
10. visible dark-mode checkbox selection/focus styling;
11. display-only result precision with canonical result-frame preservation;
12. NIH text citation/no-logo/no-endorsement contract;
13. researcher-facing computation terminology while preserving technical IDs internally.

Prior regression tests were updated only where their UI implementation expectation was intentionally superseded (inspection-button placement/label, sidebar-offset mechanism, and registered invalidation callback name). Their behavioral intent remains covered.

## Packaging and installed-wheel verification

- Wheel built as `biostat_research_tool-1.0.0rc15-py3-none-any.whl` with no dependency resolution.
- Isolated target installation reports `biostat 1.0.0rc15`.
- Installed browser module reports `1.0.0rc15`.
- Installed-wheel CLI Pearson smoke analysis completed using requested backend `auto`; manifest recorded actual backend `optimized_pearson_v0.4.1`.
- `biostat verify` reported **RunBundle: VALID** for the installed-wheel smoke run.
- Installed-wheel `biostat_tool/web.py` is byte-identical to the packaged source `biostat_tool/web.py`.
- A fresh extraction of the source ZIP reports version `1.0.0rc15`, passes frozen-oracle verification, and passes the 13 RC15-specific regressions plus all 8 frozen-oracle tests (21/21).
- The final source ZIP passes `unzip -t` with no archive errors.

## NIH citation boundary

The Documentation panel quotes the official NIH Grants & Funding page *Enhancing Reproducibility through Rigor and Transparency* and links to the official source. The panel explicitly states that NIH does not endorse, certify, or validate this software. NIH logo guidance prohibits use that could imply endorsement; therefore RC15 intentionally uses text attribution only.

## Known external verification boundary

Programmatic CSS/component/event contracts are covered, but exact visual appearance still benefits from a real-browser check on the user's workstation, especially persistent-rail spacing, dark-mode checkbox rendering, and compact declaration density. Remote CI and cross-platform operating-system execution were not independently re-observed in this environment for RC15.

## Release status

RC15 is a **review candidate**, not the final v1.0.0 release. It should receive one final live-browser inspection and targeted independent review of U36–U48 before promotion.
