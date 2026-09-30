# Privacy and Local-First Operation

The default browser server binds to `127.0.0.1`, Gradio sharing is disabled, and Gradio analytics are disabled by default. Statistical computation is local to the machine running the tool.

A RunBundle intentionally does **not** copy the original research matrices. However, a RunBundle may contain sample identifiers, feature identifiers, alignment information, study declarations, statistical results, warnings, and provenance. Those artifacts can still be sensitive. Handle RunBundles according to the sensitivity and governance requirements of the identifiers and results they contain.

## Browser temporary storage

With the default configuration, Biostat creates a **private Gradio cache directory for the current Python process**. Browser uploads, packaged-example copies, AnalysisSpec downloads, and RunBundle downloads remain on the local machine.

Biostat-generated downloadable AnalysisSpec/RunBundle artifacts are created directly inside session-tracked directories within that cache. Because those paths are already inside Gradio's cache, Gradio serves them in place rather than creating an additional hash-cache copy. The session-tracked generated artifacts are removed when inputs are invalidated or a new inspection begins. Visualization callbacks also recheck session generation before and after export and at UI publication; superseded in-flight exports are suppressed and any stale artifact directory recreated during export is removed.

With the default cache configuration, Biostat also registers normal-process-exit cleanup for the private cache directory. **Abnormal termination** (for example, forced process kill or machine failure) cannot guarantee that cleanup code runs; local operating-system temporary-file cleanup and institutional storage policy therefore remain relevant.

Uploaded source files are managed by the same local Gradio cache. They are not copied into RunBundles, but they may remain in the private cache while the browser process is running.

If an operator explicitly sets `GRADIO_TEMP_DIR`, Biostat uses that external directory and does not assume ownership of its full lifecycle. The operator is then responsible for retention and cleanup of that cache.

Synthetic examples bundled with the software are completely synthetic and are not derived from real participants.

## Correlation figure exports (v1.0.0)

The association explorer renders only the feature pair explicitly selected by the researcher. PNG, SVG, and PDF exports contain the plotted pairwise-complete sample-level coordinate values and can therefore disclose more source-level information than the summary correlation table. Treat exported figures according to the sensitivity of the originating data. PNG, SVG, and PDF figure files are session-tracked local artifacts and are removed on browser invalidation/normal process-cache cleanup under the default cache configuration. They are not automatically included in the canonical RunBundle.

## Visualization privacy boundary (v1.0.0)

The visualization workspace distinguishes **summary result views** from **sample-level data views**. Heatmaps, correlograms, and bubble plots are generated from stored correlation-result rows and do not require exporting raw sample coordinates. Pair association plots and scatterplot matrices display actual pairwise/sample-level measurements and therefore may reveal substantially more of the originating research matrix.

All figure types can be exported as PNG, SVG, or PDF. Exported figures remain local session artifacts and are not automatically copied into the canonical RunBundle. Treat pair plots and scatter matrices according to the sensitivity of the source data.
