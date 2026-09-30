# AnalysisSpec v1

`AnalysisSpec` is the canonical request contract used by both the CLI and local web interface.

Canonical serialization is JSON with `schema_version: "1.0"`. A JSON Schema is packaged at `biostat_tool/schemas/analysis-spec-v1.schema.json` and can be printed with:

```bash
biostat schema
```

## Reproducibility rules

1. Dataset SHA-256 is mandatory.
2. Dataset paths and `outputs.root` are portable logical relative POSIX paths. Absolute machine paths are rejected from the specification. A runtime path override may point anywhere locally, but it is accepted only when its SHA-256 matches the spec.
3. The analysis method and full BH family are prespecified.
4. Preprocessing/study-design declarations remain explicit and are revalidated at every run.
5. Warning acknowledgement includes the exact inspection fingerprint and exact warning-ID set.
6. Unknown fields are rejected rather than silently ignored.
7. Old schema versions will not be silently reinterpreted under a newer schema.

## Current v1 scope

Only `cross_omics_correlation` is currently implemented. Future analysis types will be added as separately validated modules rather than overloading correlation-specific fields.
