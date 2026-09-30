# RunBundle v1

RunBundle v1 is the immutable archival output of a completed analysis. It is designed for four goals:

1. **reproducibility** — preserve the exact analysis specification, input identities and statistical provenance;
2. **integrity** — inventory and SHA-256 every artifact included in the bundle;
3. **portability** — never require the original machine's absolute filesystem paths;
4. **privacy by default** — do not copy source research datasets into the bundle.

A completed correlation bundle has this required structure:

```text
run_.../
├── manifest.json
├── analysis.json
├── analysis.requested.json
├── inspection.json
├── alignment.json
├── provenance.json
├── results/
│   ├── correlations.csv
│   └── schema.json
├── report/
│   └── report.html
└── logs/
    └── run.log
```

## File roles

### `manifest.json`

The top-level inventory and integrity index. It records:

- RunBundle schema version and completion status;
- platform and frozen-oracle versions;
- requested/effective AnalysisSpec hashes;
- exact inspected run fingerprint;
- logical input paths, source SHA-256 digests and input byte sizes;
- result row/testable counts and the FDR family summary;
- privacy declarations;
- every bundle file's role, media type, byte count and SHA-256 digest.

`manifest.json` does not hash itself. Bundle hashes detect accidental or unreviewed content changes; they are not a cryptographic signature against a malicious party who can rewrite the entire bundle.

### `analysis.json`

The **effective canonical AnalysisSpec**. If warnings were acknowledged, this file contains the fingerprint-bound acknowledgement metadata used by the completed run. This is the preferred specification for an exact rerun.

### `analysis.requested.json`

The canonical specification submitted before any new warning acknowledgement was added by this execution.

### `inspection.json`

Dataset inspection metrics and every blocking/warning issue produced before inference.

### `alignment.json`

The exact sample-alignment record, including retained and excluded sample identifiers.

### `provenance.json`

Detailed scientific provenance. For the correlation module it retains the full accepted v0.2.4 oracle manifest, including:

- data/content hashes;
- preprocessing declarations;
- study-design declaration;
- software versions;
- inference branch and method labels;
- deterministic Spearman seed/permutation recipe;
- FDR family metadata;
- warning acknowledgement;
- interpretation/assumption notes.

The top-level manifest stays generic so future analysis modules can use RunBundle v1 without embedding correlation-specific fields into the bundle inventory.

### `results/correlations.csv`

The primary tidy result table.

### `results/schema.json`

Machine-readable result-table metadata: analysis/table ID, row count, primary-key fields, column order, storage types, nullability and field meanings.

### `report/report.html`

A static human-readable report rendered from completed results. Report generation does **not** rerun inference.

### `logs/run.log`

Compact execution identifiers and versions. It intentionally excludes absolute source-data paths.

## Portability and input identity

`AnalysisSpec` dataset paths and `outputs.root` are logical **relative POSIX paths**. Absolute machine paths, drive-letter paths, backslashes and `..` traversal segments are rejected from the portable specification.

A researcher may still execute the same specification against files stored elsewhere by using runtime path overrides:

```bash
biostat run analysis.json \
  --dataset-a /different/location/a.csv \
  --dataset-b /different/location/b.csv
```

The override is accepted only when its SHA-256 matches the identity recorded in the AnalysisSpec.

## Raw data policy

RunBundle v1 does not copy source research datasets by default. It records their SHA-256 identities and logical names instead. Reproduction therefore requires the original input bytes or byte-identical copies.

This avoids silently creating additional copies of potentially sensitive research datasets when results are archived, emailed or committed to a repository.

## Immutability

A published RunBundle is treated as immutable.

- Bundle construction occurs in a temporary staging directory.
- Scientific outputs, report and inventory are completed first.
- The staging bundle is fully verified.
- Only then is it atomically renamed to its final destination.
- `biostat report` reads the existing bundled report by default instead of rewriting the bundle.
- New report copies must be written outside the completed bundle.

## Verification

Verify structure and all recorded SHA-256 hashes with:

```bash
biostat verify runs/run_...
```

Machine-readable verification:

```bash
biostat verify runs/run_... --json
```

The verifier checks, among other invariants:

- required files exist;
- no unlisted files have appeared;
- all listed files exist;
- byte counts and SHA-256 digests agree;
- requested/effective AnalysisSpec hashes agree across files;
- input SHA-256 identities agree between the spec and manifest;
- run fingerprint agrees between manifest and provenance;
- result-table row/column metadata agree with the CSV.

`zip_run_bundle()` refuses to archive an invalid bundle.

## Schema

The packaged top-level manifest schema can be printed with:

```bash
biostat bundle-schema
```

RunBundle schema version is independent from the platform software version. Compatible future software may continue reading RunBundle v1 even as the application version changes.
