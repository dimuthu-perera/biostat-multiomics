# Synthetic examples

Biostat Research Tool ships a deterministic synthetic example library for learning, screenshots, regression testing, and demonstrations.

All bundled examples are completely synthetic and are **not derived from real participants**. They demonstrate supported matrix structures and software safeguards; they are not claimed to reproduce the full biological distribution of a real assay.

The library deliberately includes both **same-domain** and **cross-domain/cross-omics** workflows so the browser does not imply that Dataset A and Dataset B must be different assay types.

Supported demonstrations include:

- same-domain metabolomics × metabolomics;
- same-domain transformed RNA-seq × transformed RNA-seq;
- same-domain proteomics × proteomics;
- cross-omics metabolomics × transformed RNA-seq;
- cross-omics metabolomics × proteomics;
- cross-omics metabolomics × metagenomics CLR;
- cross-domain 16S CLR × generic quantitative biomarkers;
- a Pearson-vs-Spearman teaching dataset;
- intentionally blocked raw RNA-seq and relative-abundance microbiome guardrail examples.

The browser's **Synthetic example** selector reads `catalog.json`. `truth.json` records a small number of planted relationships for teaching and regression support. The files can be regenerated deterministically with `python scripts/generate_synthetic_examples.py`.

## Correlation teaching plot presets

The `Teaching: Pearson vs Spearman` example contains deliberately different synthetic scatter structures rather than repeated variants of one line: strong positive linear, strong negative linear, monotonic nonlinear, outlier-sensitive, null, and missing-data pairs. `truth.json` records their feature names and teaching descriptions. A constant-feature pair is retained as an ineligible guardrail example.

Association figures can be exported as 300-dpi PNG, SVG, or PDF. All formats are generated from the same Matplotlib figure and the exact pairwise-complete observations used for the selected statistical result.

## Bundled-example declaration guardrail

When both selected input files exactly match the SHA-256 byte identities of a bundled synthetic example, the browser compares the current **data type** and **preprocessing** declarations with that example's catalog metadata. If a researcher intentionally or accidentally changes one of those declarations, Readiness adds a `synthetic_example` warning and requires browser acknowledgement before analysis. The tool never silently restores the catalog value.

This guardrail is limited to the deterministic packaged examples, where the generating metadata are known. It is **not** used to infer preprocessing history for ordinary uploaded datasets; numerical values alone generally cannot establish how a real dataset was normalized, transformed, or otherwise preprocessed.
