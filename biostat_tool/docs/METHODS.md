# Statistical Methods and Scope

## Scope

Biostat Research Tool v1.0.0 provides a validated cross-dataset correlation module for two quantitative samples-by-features matrices. It is intended for exploratory, unadjusted, independent-sample screening in biomedical, same-domain, and multi-omics research. It does not infer causality, regulation, mediation, prediction, or an adjusted independent effect.

The accepted scalar statistical oracle is correlation engine v0.2.4. Accepted optimized backends accelerate only supported subsets and are required to preserve the oracle's statistical contract; unsupported cases fall back to the scalar oracle.

## Inputs and alignment

Sample and feature identifiers are treated as literal text. Duplicate identifiers are blocking errors. Dataset A and Dataset B are aligned by exact shared sample identifier and one canonical common order. No fuzzy matching or row-position-only matching is used.

Rows must represent independent observations for current inferential use. Unknown, repeated, clustered, nested, or otherwise dependent observations are blocked from ordinary correlation inference.

## Supported data declarations

Supported profiles are metabolomics, RNA-seq, metagenomics, 16S/amplicon microbiome, proteomics, and generic quantitative data.

RNA-seq raw counts, normalized but untransformed counts, TPM, FPKM, and untransformed CPM are blocked for this generic correlation workflow. Accepted RNA-seq states are VST, rlog, log-CPM, or another documented transformed representation.

Raw/normalized microbiome counts and relative abundance are blocked for ordinary Pearson/Spearman analysis. CLR or another documented compositionally appropriate transformed representation may proceed. CLR results are interpreted as associations among relative log-ratio coordinates, not absolute microbial abundances or ecological interactions.

Metabolomics and proteomics do not receive an automatic universal transformation. The researcher declares the processed quantitative state; the tool inspects for consistency but does not silently normalize, log-transform, scale, impute, batch-correct, or delete outliers.

## Missing values

Correlation uses pairwise complete observations. For each feature pair, `N` is the number of aligned samples with finite values for both variables. Different pairs may therefore use different subsets. No automatic imputation is performed. Pairwise deletion does not correct informative missingness, detection-limit censoring, MNAR mechanisms, or feature-dependent missingness.

The statistical engine permits a hard minimum pairwise N of 3 for reproducibility and advanced use. Product policy starts new analyses at N=10 and warns for explicit thresholds below 10. Neither value is a universal sample-size recommendation.

## Pearson correlation

Pearson correlation estimates linear association. The two-sided inferential null is zero population Pearson correlation under the assumptions of the standard Pearson test. Numerical affine stabilization is used internally for binary64 reliability; it is not a biological transformation of the uploaded values. Unresolved numerical failures stop inferential finalization rather than silently dropping a hypothesis.

The product does not automatically choose Pearson versus Spearman based on a normality test. Distributional diagnostics are warnings and interpretation aids, not automatic method-selection rules.

## Spearman correlation

Spearman rho estimates monotonic association using average ranks for ties. Two-sided inference uses the absolute observed rho.

Inference policy is fixed in the accepted oracle:

- N <= 8: exact positional permutation enumeration;
- 9 <= N <= 500: Monte Carlo pairings permutation;
- N >= 501 without ties: asymptotic SciPy Spearman p-value;
- ties at large N continue through permutation inference, subject to the reference engine's bounded computational policy.

For Monte Carlo inference with B permutations and b extreme permutations, `p = (b + 1) / (B + 1)`. The default B is 9,999, giving a minimum attainable Monte Carlo p-value of 0.0001. The software records the seed, permutation count, extreme count, inference branch, tie state, and p-value floor. The operational permutation null is independence/random pairing under exchangeability; it is not presented as assumption-free inference under arbitrary dependence.

## Multiple testing

One correlation method is prespecified per run. The multiple-testing family is all eligible Dataset-A × Dataset-B feature pairs for that method. Pairs that are not tested because of insufficient pairwise N or a constant variable are not included in `m`. Benjamini-Hochberg adjustment is then applied once globally over the assembled eligible p-values. Correction is not performed separately by feature, chunk, mask group, or selected hits.

BH is the current validated default. The software discloses that omics hypotheses are dependent and that arbitrary dependence is not covered by the usual BH guarantees. Benjamini-Yekutieli is not yet implemented because it would be a new statistical procedure requiring separate validation.

## Reporting and interpretation

Each result retains feature identifiers, method, coefficient estimate, raw p-value, BH-adjusted p-value (`q_value` field), pairwise N, status, p-value/inference method, and applicable Spearman permutation metadata. Non-significant results remain in the result table.

Every current correlation run is labeled an **unadjusted marginal association**. Associations can reflect confounding, group composition, batch effects, medication, demographics, ancestry, technical factors, or other common causes. The module does not currently adjust for covariates.

Confidence intervals are not yet part of the accepted v1 statistical contract. They are planned only after a method-specific implementation and validation review.

## Reproducibility

The scientific request is encoded in a versioned AnalysisSpec. Runtime backend choice is deliberately outside the AnalysisSpec because execution strategy must not change the requested method. The RunBundle records requested and actual backend, fallback reason, input hashes, alignment, warnings, statistical policy, software versions, and the completed result family.

Normal CLI/browser execution uses `auto`: accepted optimized paths are used when eligible and otherwise transparently fall back to the frozen scalar oracle. The Python API retains its historical reference default unless a backend is explicitly requested.

## Key references

- Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and powerful approach to multiple testing. *JRSS B*. 1995;57:289-300.
- Benjamini Y, Yekutieli D. The control of the false discovery rate in multiple testing under dependency. *Annals of Statistics*. 2001;29:1165-1188.
- Schober P, Boer C, Schwarte LA. Correlation Coefficients: Appropriate Use and Interpretation. *Anesth Analg*. 2018;126:1763-1768. PMID 29481436.
- Love MI, Huber W, Anders S. Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2. *Genome Biol*. 2014;15:550. PMID 25516281.
- Gloor GB, Macklaim JM, Pawlowsky-Glahn V, Egozcue JJ. Microbiome Datasets Are Compositional: And This Is Not Optional. *Front Microbiol*. 2017;8:2224. PMID 29187837.
- Sun J, Xia Y. Pretreating and normalizing metabolomics data for statistical analysis. *Genes Dis*. 2024;11:100979. PMID 38299197.
