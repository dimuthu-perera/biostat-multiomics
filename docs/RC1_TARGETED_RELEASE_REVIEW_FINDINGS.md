# v1.0.0-rc1 targeted release review findings

The independent rc1 product/release review reported **NEEDS TARGETED RELEASE FIXES** with two MEDIUM product/privacy defects and no statistical regression:

1. **Load Example preprocessing state:** programmatic example loading changed the data type and selected preprocessing value but did not keep Gradio's preprocessing choice domain consistent, causing registered `Blocks.process_api` inspection failures for examples such as Metabolomics × Proteomics, CLR/generic examples, and guardrail examples.
2. **Download-cache retention:** Biostat deleted its original temporary AnalysisSpec/RunBundle directories on invalidation, but Gradio postprocessing had copied those downloads to `/tmp/gradio/<hash>/...`; those framework-created copies were outside Biostat's session cleanup boundary and could persist after the probe process exited.

The same review reported that frozen statistics, accepted backends, synthetic examples, wheel contents, local-only defaults, and the 111-test maintained suite otherwise passed within its checked scope.

v1.0.0-rc2 is limited to closing these two release-layer findings. It does not change the frozen statistical oracle, optimized correlation backends, AnalysisSpec semantics, or RunBundle statistical content.
