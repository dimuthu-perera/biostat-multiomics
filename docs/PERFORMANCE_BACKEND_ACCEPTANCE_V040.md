# Independent acceptance summary — v0.4.0 performance backend

**Verdict received:** PERFORMANCE BACKEND ACCEPTED — READY FOR NEXT OPTIMIZATION STAGE.

The independent focused review reported no reproducible correctness, equivalence, or provenance defect within the complete-data Pearson optimization boundary.

Verified items reported by the reviewer included:

- frozen oracle source hashes: 5/5 passed;
- default API/CLI execution remained `reference`;
- static Spearman CSV matched the accepted SHA-256;
- Spearman, aligned missingness, exact integers above `2**53`, injected stabilization failures, and vectorized numerical warnings retained reference behavior;
- numerical equivalence across random, nearly collinear, large-offset, subnormal, huge-finite, constant, and N=3 complete-data Pearson cases;
- vectorized SciPy retained the beta-null Pearson p-value calculation;
- status, pairwise N, feature order, inference labels, and family metadata matched reference;
- one frozen BH call was observed after multiple forced vectorization blocks;
- deliberate coefficient perturbation by `1e-6` caused `BackendEquivalenceError` and prevented completion;
- backend selection remained outside AnalysisSpec;
- backend provenance was recorded and inconsistent records were rejected;
- maintained suite: 87 passed, 0 failed, 0 skipped;
- independent 120-case sweep maximum coefficient difference: `5.55e-16`; p-values and q-values matched exactly.

The reviewer noted one performance-only limitation: complete optimized execution repeated feature stabilization during eligibility/kernel work. This did not affect acceptance or scientific results. v0.4.1 removes stabilization from eligibility and performs it only where required by the selected optimized kernel.

The independent review used Python 3.12.14. The project additionally validates the candidate in its declared Python 3.13 reference environment.
