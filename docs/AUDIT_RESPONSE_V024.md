# Response to independent v0.2.3 focused audit

The v0.2.3 focused audit found one remaining HIGH-severity import-boundary defect (H1) and one LOW test-maintenance defect. Statistical algorithms were independently rechecked and were not changed.

v0.2.4 closes H1 by resolving the workbook's actual sheet relationship before openpyxl construction and applying a strict supported-path contract: the single referenced worksheet must resolve to `xl/worksheets/*.xml`. The exact referenced part is then raw-XML preflighted for formulas, merges, and coordinate/cell limits. A relationship target outside this validated set is rejected before `load_workbook` can execute.

Regression fixtures cover the audit's relationship-target routing pattern in both sample orientations and assert pre-parser rejection. The stale Spearman error-message assertion was also updated. The statistical algorithms, method policy, deterministic Monte Carlo recipe, BH family behavior, and Gradio generation logic are unchanged.
