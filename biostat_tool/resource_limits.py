from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

from correlation_tool.analysis import CorrelationConfig
from correlation_tool.io import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_MATRIX_CELLS

# Browser/rendering limits are product limits, separate from scientific/statistical policy.
RESULT_PREVIEW_ROWS = 500
PLOT_EXPORT_BATCH_LIMIT = 50
HEATMAP_MAX_FEATURES_PER_AXIS = 60
CORRELOGRAM_MAX_FEATURES_PER_AXIS = 30
SCATTER_MATRIX_MAX_VARIABLES = 9
BUBBLE_MAX_POINTS = 600
RESOURCE_WARNING_FRACTION = 0.80


@dataclass(frozen=True)
class ResourceAssessment:
    samples: int
    features_a: int
    features_b: int
    planned_pairs: int
    cells_a: int
    cells_b: int
    file_bytes_a: int
    file_bytes_b: int
    pair_limit: int
    sample_limit: int
    cell_limit: int
    file_limit_bytes: int
    status: str
    messages: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_resources(*, samples: int, features_a: int, features_b: int, file_a: str | Path, file_b: str | Path,
                     config: CorrelationConfig | None = None) -> ResourceAssessment:
    cfg = config or CorrelationConfig()
    fa, fb = Path(file_a), Path(file_b)
    file_bytes_a = fa.stat().st_size
    file_bytes_b = fb.stat().st_size
    planned = int(features_a) * int(features_b)
    cells_a = int(samples) * int(features_a)
    cells_b = int(samples) * int(features_b)
    blocks: list[str] = []
    warnings: list[str] = []

    if samples > cfg.max_samples:
        blocks.append(f"Matched samples {samples:,} exceed the validated limit of {cfg.max_samples:,}.")
    if planned > cfg.max_planned_tests:
        blocks.append(f"Planned feature-pair tests {planned:,} exceed the validated limit of {cfg.max_planned_tests:,}.")
    if cells_a > cfg.max_input_cells_per_dataset or cells_b > cfg.max_input_cells_per_dataset:
        blocks.append(
            f"At least one aligned matrix exceeds the validated {cfg.max_input_cells_per_dataset:,}-cell analysis limit."
        )
    if file_bytes_a > DEFAULT_MAX_FILE_BYTES or file_bytes_b > DEFAULT_MAX_FILE_BYTES:
        blocks.append(
            f"At least one input exceeds the {DEFAULT_MAX_FILE_BYTES / (1024**2):.0f} MiB import limit."
        )

    if not blocks:
        if planned >= int(cfg.max_planned_tests * RESOURCE_WARNING_FRACTION):
            warnings.append(
                f"Planned feature-pair tests use {100 * planned / cfg.max_planned_tests:.1f}% of the validated pair limit."
            )
        if samples >= int(cfg.max_samples * RESOURCE_WARNING_FRACTION):
            warnings.append(f"Matched samples use {100 * samples / cfg.max_samples:.1f}% of the validated sample limit.")
        if max(cells_a, cells_b) >= int(cfg.max_input_cells_per_dataset * RESOURCE_WARNING_FRACTION):
            warnings.append("At least one aligned matrix is near the validated cell-count ceiling.")
        if max(file_bytes_a, file_bytes_b) >= int(DEFAULT_MAX_FILE_BYTES * RESOURCE_WARNING_FRACTION):
            warnings.append("At least one source file is near the validated import-size ceiling.")

    status = "BLOCKED" if blocks else ("WARNING" if warnings else "PASS")
    return ResourceAssessment(
        samples=samples, features_a=features_a, features_b=features_b, planned_pairs=planned,
        cells_a=cells_a, cells_b=cells_b, file_bytes_a=file_bytes_a, file_bytes_b=file_bytes_b,
        pair_limit=cfg.max_planned_tests, sample_limit=cfg.max_samples,
        cell_limit=cfg.max_input_cells_per_dataset, file_limit_bytes=DEFAULT_MAX_FILE_BYTES,
        status=status, messages=tuple(blocks + warnings),
    )


def resource_markdown(a: ResourceAssessment, *, method: str, permutations: int) -> str:
    pair_pct = 100 * a.planned_pairs / a.pair_limit if a.pair_limit else 0.0
    lines = [
        f"### Compute readiness: {a.status}",
        f"- Matched samples: **{a.samples:,} / {a.sample_limit:,}**",
        f"- Features: **{a.features_a:,} × {a.features_b:,}**",
        f"- Planned correlations: **{a.planned_pairs:,} / {a.pair_limit:,}** ({pair_pct:.1f}%)",
        f"- Aligned cells: **{a.cells_a:,}** and **{a.cells_b:,}** / {a.cell_limit:,} per dataset",
        f"- Source sizes: **{a.file_bytes_a / (1024**2):.1f} MiB** and **{a.file_bytes_b / (1024**2):.1f} MiB** / {a.file_limit_bytes / (1024**2):.0f} MiB per file",
    ]
    if method == "spearman":
        lines.append(f"- Spearman Monte Carlo budget when applicable: **{permutations:,} pairings per null group**")
    lines.extend(f"- {m}" for m in a.messages)
    lines.append("\n**Supported analysis limits** are engineering and validation safeguards, not biological sample-size recommendations. Analyses outside them are blocked before inference.")
    return "\n".join(lines)
