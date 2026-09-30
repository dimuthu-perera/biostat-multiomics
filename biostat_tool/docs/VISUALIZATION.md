# Scientific visualization system

Biostat Research Tool v1.0.0 separates **summary result views** from **sample-level data views**. Visualization never changes the AnalysisSpec, the hypothesis family, the stored coefficient, p-value, or BH q-value.

## Shared feature selection

After a successful run, the browser proposes features from the strongest validated result rows. Researchers can change the Dataset A and Dataset B selections once and reuse that subset across the visualization workspace. The association explorer also supports two-stage Dataset A → Dataset B selection so large result families do not have to be searched through one long pair list. A separate quick-search dropdown contains only the first 5,000 ranked pairs for browser responsiveness; the two-stage selectors can reach every eligible analyzed pair.

## Summary result views

These figures consume only rows already present in `results/correlations.csv`:

- **Heatmap** — signed correlation coefficient encoded on a fixed -1 to +1 scale. Associations above the chosen visual q threshold can be de-emphasized without being removed from the analyzed family. Small matrices may display coefficient values in cells.
- **Correlogram** — a true color-cell correlation matrix rather than a circle-marker plot. Small matrices print coefficient values in the cells and significant cells may be marked with `*`. A lower triangle is used only when the two inputs have verified identical source bytes, the selected feature names match, and the coefficient matrix is symmetric; ordinary cross-dataset selections remain rectangular even when labels and coefficients happen to match. Values are omitted automatically when the matrix is too dense for legible annotation.
- **Bubble plot** — a scatter-style association map. X is the signed correlation coefficient and Y is the exact `-log10(BH q)` for every positive q-value. Point size can emphasize either absolute effect magnitude or statistical evidence, and point color encodes the signed coefficient. Evidence-based marker sizing is capped for readability without changing the Y coordinate. Because `q=0` has an infinite mathematical ordinate, zero-valued q points use an explicitly disclosed finite display position above the strongest positive-q point. The visual q threshold is shown as a horizontal reference line. At most 600 selected eligible associations are rendered.

These display controls do **not** recompute FDR and do not define a new hypothesis family.

## Sample-level data views

- **Association plot** — exact pairwise-complete observations used by the stored result. Pearson can show the least-squares line. Spearman can show raw values or average-rank space. If distinct supported integer coordinates would collapse when narrowed to binary64 for plotting, the raw-coordinate view is refused rather than displaying a misleading collapse; Spearman rank-space remains available. Exceptionally long feature identifiers are retained in full in the figure title while the X/Y axes use explicitly marked bounded display labels. Pair titles wrap from measured rendered width, and pathological wide identifiers expand the native pair-figure height so both the Gradio browser preview and exported figures retain the complete title without crossing the statistical header or canvas edges.
- **Scatterplot matrix** — 2 to 9 selected variables across Dataset A and B. Diagonal panels show univariate distributions and the lower triangle shows raw relationships. The upper triangle prints coefficient/N/q only for validated A×B result pairs. Within-dataset panels are labeled as raw exploratory views and add no new inferential correlation tests. The UI shows a live selection counter because an N-variable matrix creates N² panels.

Because these views reveal sample-level coordinates, their exports should be handled according to the sensitivity of the originating matrices.

## Association batch report

The browser can generate a combined PDF for the top 10, 25, or 50 validated associations using an explicit ranking rule: lowest q-value, largest absolute effect, strongest positive, strongest negative, or q≤0.05 only. The report includes the ranking rule and analysis fingerprint. An optional ZIP contains individual 300-dpi pair figures plus a CSV index. This report is a presentation of the already validated result family; it does not recompute or redefine inference.

## Publication exports

Every formal figure is exported from the same Matplotlib figure object as:

- PNG at 300 dpi;
- SVG with vector text/shapes where supported;
- PDF with vector text/shapes where supported.

Colorbars are laid out against their rendered bounds so labels remain within the native canvas and exported page. The browser UI can use light, dark, or system appearance while publication figures retain the publication-oriented figure theme.

Exported figures are local session artifacts and are not automatically inserted into the canonical RunBundle.

## Visualization limits

Visualization limits are deliberately lower than the computational analysis ceiling so the browser does not attempt unreadable or memory-heavy plots:

- heatmap: at most **60** features per axis;
- correlogram: at most **30** features per axis;
- bubble plot: at most **600** selected eligible A×B associations;
- scatterplot matrix: at most **9** total variables.

For dense correlograms, cell text is suppressed rather than squeezed into unreadable cells. For larger feature families, use feature filtering/subsetting and the complete result CSV. The complete analyzed result family remains available even when a requested visual subset exceeds a rendering limit.
