# Supported analysis limits and resource safety

Biostat Research Tool v1.0 deliberately blocks analyses outside its validated software safeguards instead of attempting unbounded work. The browser presents these checks under **Analysis readiness** and keeps the exact ceilings in a collapsible **Supported analysis limits** section.

## Hard analysis/import limits

- Planned cross-dataset feature pairs: **250,000** maximum.
- Samples: **10,000** maximum.
- Input cells per dataset: **5,000,000** maximum.
- Source file size: **100 MiB** maximum per file.
- CSV/TSV raw rows: **100,000** maximum; raw columns: **50,000** maximum.
- XLSX expansion and entry-size caps remain enforced by the validated importer.

These are software validation/resource limits, not recommendations for statistical power, biological study design, or feature selection.

The browser shows planned correlations and resource utilization during mandatory inspection. At 80% or more of a validated ceiling, it issues a compute warning. A hard-limit violation is BLOCKED before inference.

## Spearman workload

Spearman inference can require exact or Monte Carlo pairing-null calculations. The validated oracle additionally limits permutation sample size, null-group counts, total null evaluations, and null-cache memory. Optimized execution may reduce elapsed time but does not relax those statistical-engine safeguards.

## Browser/result rendering limits

- Results preview: at most **500** rows. The complete result table remains downloadable as CSV.
- Pair association figures: generated only for the explicitly selected A×B result pair.
- Heatmap: at most **60 features per axis**.
- Correlogram: at most **30 features per axis**.
- Bubble plot: at most **600 selected eligible A×B associations**.
- Scatterplot matrix: at most **9 total selected variables** across Dataset A and Dataset B.
- No visualization is generated automatically for every result row.

Summary views (heatmap, correlogram, bubble) use stored result statistics. Pair plots and scatter matrices contain sample-level measurement coordinates and must be handled according to source-data sensitivity.

## When a study exceeds the analysis limit

The software does not automatically select a smaller hypothesis family. Researchers should reduce features using a scientifically justified, preferably prespecified criterion independent of the observed correlation significance results. The resulting AnalysisSpec and source matrices should document the analysis-ready feature set actually tested.
