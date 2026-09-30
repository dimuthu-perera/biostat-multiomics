# Biostat Research Tool v1.0.0 validation record

## Release decision

Biostat Research Tool v1.0.0 is the final promotion of the independently reviewed RC17 candidate. Final promotion changes are release metadata/documentation only, plus one stale researcher-facing sentence in the Video tutorials panel changed from “this release candidate” to “this release.” No statistical method, inference rule, FDR policy, AnalysisSpec scientific semantics, RunBundle schema, correlation backend, or figure-computation algorithm was changed during final promotion.

RC17 independent review reported no reproducible defect in its executed checks. The user separately confirmed in a live browser that the RC16/RC17 dark-mode checkbox check mark is visible, closing the remaining U49 visual acceptance item.

## Validation environment

- Python 3.13.5
- NumPy 2.3.5
- pandas 2.2.3
- SciPy 1.17.0
- Gradio 6.5.1
- Matplotlib 3.10.8
- openpyxl 3.1.5
- pytest 9.0.2

## Frozen scientific core

`python scripts/verify_oracle_hashes.py` reports:

`Frozen oracle hashes: OK`

The following protected files remain byte-identical to RC17:

- `biostat_tool/modules/correlation.py` — `f9442a02f860e195d599e279156ef9a20127da95ea68c010cbd39fa0105ad8fe`
- `biostat_tool/modules/correlation_backends.py` — `fd89f152ed087881f1ecb8589de83aeeed69e493b43e7f911e8e68c78236bf48`
- `biostat_tool/runner.py` — `fc104c1776b74b57e9a94c16dc428db4db66693feaca358333429a9378aba06c`
- `biostat_tool/bundle.py` — `b661dde62a6277afd170ce31a1fa4611e5603df2951e882e7e49e4c4f040a22d`
- `biostat_tool/specs.py` — `b303405bdebcaf7a8057e4df2d9e8f0e8a37b12ed29235d847ecbd440223949c`
- `correlation_tool/analysis.py` — `5f76c90e90662205aaf6ee62c739fc0f0419b65409f38ab111e89f87756faed8`
- `biostat_tool/visualization.py` — `6b1f5e5aa68e153b4db5efb6170c0b40b5b77769ce9e0cce6d0565205daeba85`

## Maintained regression suite

The repository collects exactly **212 tests**. Because a single monolithic Gradio-heavy pytest invocation can exceed the execution window after completing tests, the complete suite was executed in exhaustive non-overlapping groups with plugin autoload disabled. Every collected test file was included.

Combined result: **212 passed, 0 failed, 0 skipped**.

The final promotion also passed the version-sensitive CLI/RunBundle tests after changing the platform version expectation from `1.0.0rc17` to `1.0.0`.

## Packaging verification

The final wheel was built from `pyproject.toml` with version `1.0.0` using:

`python -m pip wheel . --no-deps --no-build-isolation`

Wheel/package checks passed:

- installed-package import reports `1.0.0`;
- CLI reports `biostat 1.0.0`;
- packaged user documentation, schemas, and synthetic example catalog are present;
- installed `biostat_tool/web.py` is byte-identical to the final source file;
- `CITATION.cff` parses successfully and records version `1.0.0`, release date `2026-09-21`, and MIT license metadata.

## Installed-wheel CLI and RunBundle smoke

Using an isolated target installation of the final wheel and the frozen tiny Spearman fixtures:

- `biostat validate analysis.json` completed with the expected WARNING state;
- `biostat run analysis.json --acknowledge-warnings --output bundle` completed successfully;
- `biostat verify bundle` returned **RunBundle: VALID**;
- the manifest records platform version `1.0.0`;
- execution requested backend `auto` and recorded actual backend `optimized_spearman_v0.4.2`;
- the result CSV contains the expected four A×B result rows.

## Documentation/release metadata

- README and packaged/public user docs identify the release as v1.0.0 rather than a release candidate.
- Public repository docs were synchronized with the packaged user docs before final packaging.
- MIT license remains unchanged.
- `CITATION.cff` intentionally retains project-level author metadata as `Biostat Research Tool contributors`; no individual contributor identity was invented.
- Video tutorial slots remain link-free until real published project URLs are supplied.

## Final status

**READY FOR v1.0.0 PUBLIC TAG / GITHUB RELEASE.**
