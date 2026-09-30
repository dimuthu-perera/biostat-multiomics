# Biostat Research Tool v1.0.0

Biostat Research Tool v1.0.0 is the first public release of the local-first reproducible correlation research workstation.

## Included in v1.0.0

- matrix-to-matrix Pearson and Spearman correlation for same-domain and cross-omics quantitative data;
- mandatory readiness inspection and explicit preprocessing/study-design declarations;
- pairwise-N tracking and one global Benjamini-Hochberg family over eligible A×B pairs;
- automatic validated computation-engine selection with transparent reference fallback;
- AnalysisSpec reproducibility and SHA-256 input identity enforcement;
- integrity-verified RunBundles with provenance and reproducible execution metadata;
- deterministic synthetic examples across metabolomics, proteomics, transformed RNA-seq, 16S/microbiome, metagenomics, and generic biomarkers;
- bundled-example teaching guardrails for declaration mismatches;
- research-workstation browser UI with light/dark/system appearance;
- publication-oriented association, heatmap, correlogram, bubble, scatter-matrix, and batch-report outputs;
- local-first browser defaults and documented privacy boundaries.

## Validation

The final promotion preserves the RC17 scientific behavior. The frozen oracle hashes pass, the protected scientific/platform files are byte-identical to RC17, and all **212 maintained tests pass on Python 3.13.5** in the final validation environment. An installed-wheel CLI smoke produced a RunBundle that verified as **VALID**.

See `BIOSTAT_V1.0.0_VALIDATION.md` for the detailed validation record.

## Scope limitations

v1.0.0 reports unadjusted marginal correlations. It does not provide covariate-adjusted correlation, causal inference, preprocessing/imputation, confidence intervals, or additional statistical modules. Those require separate methodological specification and validation.

## License and citation

Released under the MIT License. Use `CITATION.cff` to cite the software version used in an analysis.

Project-specific video tutorial links are intentionally left unconfigured until the videos are published.
