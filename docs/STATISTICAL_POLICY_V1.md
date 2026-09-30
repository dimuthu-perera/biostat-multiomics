# Statistical policy v1.0 — correlation module

Statistical policy is intentionally separate from the frozen numerical oracle.

Current non-numerical policy:

- Browser-generated analyses start with `minimum_pairwise_n=10`.
- The frozen algorithmic hard minimum remains 3 for explicit advanced/reproducibility use.
- A run specifying `minimum_pairwise_n<10` receives a non-gating platform caution.
- Neither 3 nor 10 is a universal sample-size or power recommendation.
- Correlation results are explicitly described as **unadjusted marginal associations**.
- Confounding, batch effects, group structure, medication, demographic factors, and other common causes can generate marginal associations.
- Correlation does not establish an independent molecular relationship or causation.
- Pairwise-N distributions are summarized in the report.
- Existing frozen-oracle warnings continue to cover informative missingness/pairwise deletion, Spearman permutation-resolution limits, and BH dependence assumptions.

Future statistical additions such as Benjamini-Yekutieli adjustment or confidence intervals are new statistical methods and require their own specification, tests, literature review, and validation. They are not introduced by policy v1.0.
