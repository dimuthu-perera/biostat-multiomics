from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable
import numpy as np
import pandas as pd
from scipy import stats

# Product-only visualization limits. They deliberately sit below computational
# analysis ceilings so a valid analysis cannot accidentally create an
# unreadable or memory-heavy figure.
SCATTER_MATRIX_MAX_VARIABLES = 9
HEATMAP_MAX_PER_AXIS = 60
CORRELOGRAM_MAX_PER_AXIS = 30
BUBBLE_MAX_POINTS = 600

_NEG = "#2166AC"
_NEUTRAL = "#F7F7F7"
_POS = "#B2182B"
_INK = "#172033"
_MUTED = "#667085"
_GRID = "#D9DEE8"
_POINT = "#335C81"
_ACCENT = "#1C7C7D"
_CORR_CMAP = LinearSegmentedColormap.from_list("biostat_corr", [_NEG, _NEUTRAL, _POS], N=256)


@dataclass(frozen=True)
class PairPlotData:
    feature_a: str
    feature_b: str
    x: np.ndarray
    y: np.ndarray
    n_pairwise: int
    missing_or_excluded: int


def _figure_style() -> dict[str, object]:
    return {
        "font.family": "DejaVu Sans",
        "font.size": 9.5,
        "axes.titlesize": 12,
        "axes.labelsize": 9.5,
        "axes.edgecolor": _GRID,
        "axes.linewidth": 0.8,
        "axes.labelcolor": _INK,
        "xtick.color": _MUTED,
        "ytick.color": _MUTED,
        "text.color": _INK,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    }




def _wrap_text_to_rendered_width(
    fig, text: str, *, max_width_px: float, fontsize: float, fontweight: str = "normal"
) -> str:
    """Wrap text using the active renderer rather than character-count heuristics."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    from matplotlib.font_manager import FontProperties

    props = FontProperties(size=fontsize, weight=fontweight)

    def width(value: str) -> float:
        if not value:
            return 0.0
        return float(renderer.get_text_width_height_descent(value, props, ismath=False)[0])

    def split_long_token(token: str) -> list[str]:
        pieces: list[str] = []
        remaining = token
        while remaining and width(remaining) > max_width_px:
            lo, hi = 1, len(remaining)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if width(remaining[:mid]) <= max_width_px:
                    lo = mid
                else:
                    hi = mid - 1
            cut = max(1, lo)
            pieces.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            pieces.append(remaining)
        return pieces

    tokens: list[str] = []
    for token in str(text).split():
        tokens.extend(split_long_token(token))
    if not tokens:
        return ""

    lines: list[str] = []
    current = tokens[0]
    for token in tokens[1:]:
        candidate = f"{current} {token}"
        if width(candidate) <= max_width_px:
            current = candidate
        else:
            lines.append(current)
            current = token
    lines.append(current)
    return "\n".join(lines)


def _add_figure_header(fig, title: str, subtitle: str, *, title_size: float = 12.5) -> float:
    """Add a measured figure header and return the safe axes-top fraction.

    Text is placed in figure coordinates and wrapped using actual rendered width,
    so very wide glyphs and unbroken identifiers remain inside the native canvas.
    """
    fig.canvas.draw()
    canvas_width = float(fig.bbox.width)
    max_title_width = canvas_width * 0.955
    wrapped = _wrap_text_to_rendered_width(
        fig, str(title), max_width_px=max_title_width, fontsize=title_size, fontweight="bold"
    )
    title_artist = fig.text(
        0.02, 0.965, wrapped, ha="left", va="top", fontsize=title_size,
        fontweight="bold", color=_INK, linespacing=1.18,
    )
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    title_box = title_artist.get_window_extent(renderer=renderer).transformed(fig.transFigure.inverted())
    subtitle_y = max(0.12, title_box.y0 - 0.018)
    subtitle_artist = fig.text(
        0.02, subtitle_y, str(subtitle), ha="left", va="top", fontsize=8.8,
        color=_MUTED, linespacing=1.2, wrap=True,
    )
    fig.canvas.draw()
    subtitle_box = subtitle_artist.get_window_extent(renderer=renderer).transformed(fig.transFigure.inverted())
    return max(0.40, subtitle_box.y0 - 0.04)


def _pair_axis_display_label(label: str, *, role: str, suffix: str = "") -> str:
    """Return a bounded display label while preserving the full identifier elsewhere.

    Pair-plot titles retain both complete feature identifiers.  Axis labels are
    therefore allowed to use a clearly identified display abbreviation when a
    source identifier is too long to fit safely, including a single unbroken
    token.  Bounding the longest rendered line is especially important for the
    rotated y-axis label: otherwise its vertical extent can cross the figure
    header even when the axes rectangle itself is below that header.
    """
    text = str(label)
    rendered = f"{text}{suffix}"
    if len(rendered) <= 56:
        return rendered

    width = 28
    max_content_lines = 3
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    ) or [text]
    truncated = len(lines) > max_content_lines
    shown = lines[:max_content_lines]
    if truncated:
        last = shown[-1]
        if len(last) >= width:
            last = last[: max(1, width - 1)]
        shown[-1] = f"{last.rstrip()}…"
    heading = f"{role} feature (display label)"
    if suffix:
        heading += suffix
    return heading + ":\n" + "\n".join(shown)


def _reserve_pair_label_bounds(fig, ax, *, header_gap: float = 0.018, edge_gap: float = 0.02) -> None:
    """Keep pair-axis labels inside the canvas and below the statistical header."""
    for _ in range(6):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        inv = fig.transFigure.inverted()
        x_box = ax.xaxis.label.get_window_extent(renderer=renderer).transformed(inv)
        y_box = ax.yaxis.label.get_window_extent(renderer=renderer).transformed(inv)
        subtitle_box = fig.texts[1].get_window_extent(renderer=renderer).transformed(inv)
        pos = ax.get_position()

        left = pos.x0
        bottom = pos.y0
        top = pos.y1
        changed = False

        if y_box.x0 < edge_gap:
            left += edge_gap - y_box.x0
            changed = True
        if y_box.y0 < edge_gap:
            # A rotated y-label can extend below the native canvas even when
            # the axes rectangle itself is in bounds. Raising the axes bottom
            # moves the label centre upward; repeated measured passes converge.
            bottom += min(0.08, 2.0 * (edge_gap - y_box.y0))
            changed = True
        if x_box.y0 < edge_gap:
            bottom += edge_gap - x_box.y0
            changed = True
        allowed_ymax = subtitle_box.y0 - header_gap
        if y_box.y1 > allowed_ymax:
            top -= y_box.y1 - allowed_ymax
            changed = True

        # Do not silently squeeze the plotting region into a non-usable band.
        # The bounded display labels above are chosen so normal figures remain
        # comfortably above this floor; reaching it indicates a layout bug.
        if top - bottom < 0.25:
            raise ValueError("Pair-plot labels leave insufficient room for the plotting area.")
        if not changed:
            return
        fig.subplots_adjust(left=left, bottom=bottom, top=top)

    fig.canvas.draw()

def _format_p(value: float) -> str:
    if not np.isfinite(value):
        return "NA"
    if value == 0:
        return "0"
    if value < 0.001:
        return f"{value:.2e}"
    return f"{value:.3g}"


def _checked_features(values: Sequence[str] | None, available: Iterable[str], *, label: str, maximum: int) -> list[str]:
    available_set = {str(x) for x in available}
    out = [] if values is None else [str(x) for x in values]
    if not out:
        raise ValueError(f"Select at least one {label} feature.")
    if len(out) > maximum:
        raise ValueError(f"{label} supports at most {maximum} selected features for this figure.")
    unknown = [x for x in out if x not in available_set]
    if unknown:
        raise KeyError(f"Unknown {label} feature(s): {', '.join(unknown[:5])}")
    if len(set(out)) != len(out):
        raise ValueError(f"Duplicate {label} feature selection.")
    return out


def _finite_numeric_scalar(value: object) -> bool:
    if pd.isna(value):
        return False
    try:
        return bool(np.isfinite(value))
    except TypeError:
        return False


def _exact_selected_array(series: pd.Series, mask: np.ndarray) -> np.ndarray:
    # Build from scalar values after pairwise selection instead of asking pandas
    # to materialize nullable Int64 data as float64. That preserves exact int64
    # identities above 2**53 for rank-space visualization.
    values = [value for value, keep in zip(series.array, mask, strict=True) if keep]
    return np.asarray(values)


def pairwise_complete_data(aligned_a: pd.DataFrame, aligned_b: pd.DataFrame, feature_a: str, feature_b: str) -> PairPlotData:
    if feature_a not in aligned_a.columns:
        raise KeyError(f"Unknown Dataset A feature: {feature_a}")
    if feature_b not in aligned_b.columns:
        raise KeyError(f"Unknown Dataset B feature: {feature_b}")
    sx = pd.to_numeric(aligned_a[feature_a], errors="coerce")
    sy = pd.to_numeric(aligned_b[feature_b], errors="coerce")
    mask = np.fromiter(
        (_finite_numeric_scalar(x) and _finite_numeric_scalar(y) for x, y in zip(sx.array, sy.array, strict=True)),
        dtype=bool, count=len(sx),
    )
    return PairPlotData(
        feature_a=str(feature_a), feature_b=str(feature_b),
        x=_exact_selected_array(sx, mask), y=_exact_selected_array(sy, mask),
        n_pairwise=int(mask.sum()), missing_or_excluded=int((~mask).sum()),
    )


def _float64_collapses_distinct_values(values: np.ndarray) -> bool:
    if len(values) < 2 or values.dtype.kind not in {"i", "u", "O"}:
        return False
    exact = list(dict.fromkeys(values.tolist()))
    if len(exact) < 2:
        return False
    try:
        narrowed = np.asarray(exact, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return True
    return len(np.unique(narrowed)) < len(exact)


def make_pair_figure(data: PairPlotData, *, method: str, estimate: float, p_value: float, q_value: float,
                     view: str = "raw"):
    if view not in {"raw", "ranks"}:
        raise ValueError("view must be 'raw' or 'ranks'.")
    if method != "spearman" and view == "ranks":
        raise ValueError("Rank-space view is available only for Spearman results.")
    x, y = data.x, data.y
    label_suffix = ""
    xlabel, ylabel = data.feature_a, data.feature_b
    if view == "raw" and (_float64_collapses_distinct_values(x) or _float64_collapses_distinct_values(y)):
        raise ValueError(
            "Raw plotting would collapse distinct integer coordinates during binary64 rendering. "
            "Use the rank-space view for Spearman results or rescale values upstream for a raw-coordinate figure."
        )
    if view == "ranks":
        x = stats.rankdata(x, method="average")
        y = stats.rankdata(y, method="average")
        label_suffix = " — average rank"
    symbol = "r" if method == "pearson" else "ρ"
    with plt.rc_context(_figure_style()):
        fig, ax = plt.subplots(figsize=(7.1, 5.45))
        pair_title = f"{data.feature_a} × {data.feature_b}"
        wrapped_title = _wrap_text_to_rendered_width(
            fig, pair_title, max_width_px=float(fig.bbox.width) * 0.955,
            fontsize=12.5, fontweight="bold",
        )
        title_lines = max(1, wrapped_title.count("\n") + 1)
        if title_lines > 5:
            # Preserve complete identifiers in the native browser canvas without
            # sacrificing the plotting band. Wide glyphs (for example a long
            # run of 'W') can require substantially more vertical header space.
            fig.set_size_inches(7.1, 5.45 + 0.32 * (title_lines - 5), forward=True)
        ax.scatter(x, y, s=32, alpha=0.78, color=_POINT, edgecolors="white", linewidths=0.45)
        if method == "pearson" and view == "raw" and len(x) >= 2 and np.ptp(x) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            xs = np.linspace(float(np.min(x)), float(np.max(x)), 100)
            ax.plot(xs, intercept + slope * xs, linewidth=1.8, color=_ACCENT, label="Least-squares fit")
            ax.legend(frameon=False, loc="best", fontsize=8.5)
        subtitle = f"{method.title()} {symbol} = {estimate:.3f}   ·   N = {data.n_pairwise}   ·   p = {_format_p(p_value)}   ·   BH q = {_format_p(q_value)}"
        axes_top = _add_figure_header(fig, pair_title, subtitle)
        ax.set_xlabel(_pair_axis_display_label(xlabel, role="Dataset A", suffix=label_suffix))
        ax.set_ylabel(_pair_axis_display_label(ylabel, role="Dataset B", suffix=label_suffix))
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(True, linewidth=0.55, alpha=0.45, color=_GRID)
        ax.set_axisbelow(True)
        fig.subplots_adjust(left=0.12, right=0.97, bottom=0.13, top=axes_top)
        _reserve_pair_label_bounds(fig, ax)
    return fig




def _keep_colorbar_inside_canvas(fig, cbar, *, pad_px: float = 14.0) -> None:
    """Shift a colorbar left if its label/ticks exceed the native figure canvas."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    artists = [cbar.ax]
    if cbar.ax.yaxis.label.get_text():
        artists.append(cbar.ax.yaxis.label)
    boxes = []
    for artist in artists:
        try:
            boxes.append(artist.get_window_extent(renderer=renderer))
        except Exception:
            continue
    for tick in cbar.ax.get_yticklabels():
        try:
            boxes.append(tick.get_window_extent(renderer=renderer))
        except Exception:
            pass
    if not boxes:
        return
    right = max(box.x1 for box in boxes)
    overflow = right - (fig.bbox.width - pad_px)
    if overflow <= 0:
        return
    pos = cbar.ax.get_position()
    shift = min(pos.x0 - 0.02, overflow / max(float(fig.bbox.width), 1.0) + 0.012)
    if shift > 0:
        cbar.ax.set_position([pos.x0 - shift, pos.y0, pos.width, pos.height])
        fig.canvas.draw()


def _correlogram_display_matrix(
    estimates: np.ndarray,
    a: Sequence[str],
    b: Sequence[str],
    *,
    same_variable_space: bool = False,
) -> tuple[np.ndarray, bool]:
    """Return a display matrix and whether a verified same-variable selection permits a half triangle.

    Matching labels and a numerically symmetric coefficient matrix are not enough to
    establish that Dataset A and Dataset B represent the same variables.  Callers must
    explicitly establish same-variable identity (for example, identical source bytes)
    before a triangular display is allowed.
    """
    display = np.asarray(estimates, dtype=float).copy()
    triangular = (
        bool(same_variable_space)
        and
        len(a) == len(b)
        and list(a) == list(b)
        and display.shape[0] == display.shape[1]
        and np.allclose(display, display.T, equal_nan=True, atol=1e-12, rtol=1e-12)
    )
    if triangular:
        display[np.triu_indices_from(display, k=1)] = np.nan
    return display, triangular

def _result_subset(results: pd.DataFrame, features_a: Sequence[str], features_b: Sequence[str]) -> pd.DataFrame:
    required = {"feature_a", "feature_b", "estimate", "q_value", "status"}
    missing = required - set(results.columns)
    if missing:
        raise ValueError(f"Results are missing required columns: {sorted(missing)}")
    valid = results.loc[results["status"].eq("ok")].copy()
    valid["feature_a"] = valid["feature_a"].astype(str)
    valid["feature_b"] = valid["feature_b"].astype(str)
    return valid.loc[valid["feature_a"].isin(features_a) & valid["feature_b"].isin(features_b)].copy()


def _coefficient_matrix(results: pd.DataFrame, features_a: Sequence[str], features_b: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    subset = _result_subset(results, features_a, features_b)
    estimates = subset.pivot(index="feature_a", columns="feature_b", values="estimate").reindex(index=features_a, columns=features_b)
    qvals = subset.pivot(index="feature_a", columns="feature_b", values="q_value").reindex(index=features_a, columns=features_b)
    return estimates.to_numpy(dtype=float), qvals.to_numpy(dtype=float)


def make_heatmap_figure(results: pd.DataFrame, features_a: Sequence[str], features_b: Sequence[str], *,
                        q_threshold: float = 0.05, emphasize_q: bool = True):
    a = _checked_features(features_a, results["feature_a"].astype(str).unique(), label="Dataset A", maximum=HEATMAP_MAX_PER_AXIS)
    b = _checked_features(features_b, results["feature_b"].astype(str).unique(), label="Dataset B", maximum=HEATMAP_MAX_PER_AXIS)
    estimates, qvals = _coefficient_matrix(results, a, b)
    if not np.isfinite(estimates).any():
        raise ValueError("No eligible associations are available for the selected feature subset.")
    rgba = _CORR_CMAP(Normalize(-1, 1)(np.nan_to_num(estimates, nan=0.0)))
    missing = ~np.isfinite(estimates)
    rgba[missing, 3] = 0.0
    if emphasize_q:
        weak = np.isfinite(estimates) & (~np.isfinite(qvals) | (qvals > q_threshold))
        rgba[weak, 3] = 0.28
    width = min(14.5, max(6.2, 2.8 + 0.34 * len(b)))
    height = min(14.5, max(5.0, 2.4 + 0.31 * len(a)))
    with plt.rc_context(_figure_style()):
        fig, ax = plt.subplots(figsize=(width, height))
        ax.imshow(rgba, aspect="auto", interpolation="nearest")
        ax.set_xticks(range(len(b)), b, rotation=50, ha="right")
        ax.set_yticks(range(len(a)), a)
        ax.set_xlabel("Dataset B features")
        ax.set_ylabel("Dataset A features")
        sub = "Color encodes correlation coefficient"
        if emphasize_q:
            sub += f"; associations with BH q > {q_threshold:g} are de-emphasized"
        axes_top = _add_figure_header(fig, "A×B correlation heatmap", sub)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.subplots_adjust(left=0.18, right=0.80, bottom=0.20, top=axes_top)
        sm = ScalarMappable(norm=Normalize(-1, 1), cmap=_CORR_CMAP)
        cax = fig.add_axes([0.83, 0.24, 0.025, 0.52])
        cbar = fig.colorbar(sm, cax=cax)
        cbar.set_label("Correlation coefficient")
        _keep_colorbar_inside_canvas(fig, cbar)
        if len(a) <= 12 and len(b) <= 12:
            for i in range(len(a)):
                for j in range(len(b)):
                    if np.isfinite(estimates[i, j]):
                        color = "white" if abs(estimates[i, j]) >= 0.55 else _INK
                        marker = "•" if np.isfinite(qvals[i, j]) and qvals[i, j] <= q_threshold else ""
                        ax.text(j, i, f"{estimates[i,j]:.2f}{marker}", ha="center", va="center", fontsize=7.6, color=color)
    return fig


def make_correlogram_figure(
    results: pd.DataFrame,
    features_a: Sequence[str],
    features_b: Sequence[str],
    *,
    q_threshold: float = 0.05,
    same_variable_space: bool = False,
):
    a = _checked_features(features_a, results["feature_a"].astype(str).unique(), label="Dataset A", maximum=CORRELOGRAM_MAX_PER_AXIS)
    b = _checked_features(features_b, results["feature_b"].astype(str).unique(), label="Dataset B", maximum=CORRELOGRAM_MAX_PER_AXIS)
    estimates, qvals = _coefficient_matrix(results, a, b)
    display, triangular = _correlogram_display_matrix(
        estimates, a, b, same_variable_space=same_variable_space
    )
    if not np.isfinite(display).any():
        raise ValueError("No eligible associations are available for the selected feature subset.")

    width = min(14.5, max(6.2, 3.1 + 0.39 * len(b)))
    height = min(14.5, max(5.1, 2.7 + 0.36 * len(a)))
    with plt.rc_context(_figure_style()):
        fig, ax = plt.subplots(figsize=(width, height))
        cmap = _CORR_CMAP.copy()
        cmap.set_bad((1, 1, 1, 0))
        image = ax.imshow(display, cmap=cmap, norm=Normalize(-1, 1), aspect="auto", interpolation="nearest")
        ax.set_xticks(range(len(b)), b, rotation=50, ha="right")
        ax.set_yticks(range(len(a)), a)
        ax.set_xlabel("Dataset B features")
        ax.set_ylabel("Dataset A features")
        mode_note = "Lower triangle shown because the selected matrix is symmetric" if triangular else "Full A×B matrix shown"
        values_note = "values printed in cells" if len(a) * len(b) <= 144 else "cell values hidden for readability"
        axes_top = _add_figure_header(
            fig, "Correlation correlogram",
            f"Color = correlation coefficient; * = BH q ≤ {q_threshold:g}; {mode_note}; {values_note}.",
        )
        ax.set_xticks(np.arange(-0.5, len(b), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(a), 1), minor=True)
        ax.grid(which="minor", color=_GRID, linewidth=0.55)
        ax.tick_params(which="both", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)

        if len(a) * len(b) <= 144:
            for i in range(len(a)):
                for j in range(len(b)):
                    value = display[i, j]
                    if not np.isfinite(value):
                        continue
                    q = qvals[i, j]
                    sig = "*" if np.isfinite(q) and q <= q_threshold else ""
                    text_color = "white" if abs(value) >= 0.58 else _INK
                    ax.text(j, i, f"{value:.2f}{sig}", ha="center", va="center", fontsize=7.8, color=text_color)

        fig.subplots_adjust(left=0.17, right=0.82, bottom=0.20, top=axes_top)
        cbar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.04)
        cbar.set_label("Correlation coefficient")
        _keep_colorbar_inside_canvas(fig, cbar)
    return fig


def make_bubble_figure(results: pd.DataFrame, features_a: Sequence[str], features_b: Sequence[str], *,
                       q_threshold: float = 0.05, size_by: str = "effect"):
    if size_by not in {"effect", "evidence"}:
        raise ValueError("Bubble size must be 'effect' or 'evidence'.")
    a = _checked_features(features_a, results["feature_a"].astype(str).unique(), label="Dataset A", maximum=HEATMAP_MAX_PER_AXIS)
    b = _checked_features(features_b, results["feature_b"].astype(str).unique(), label="Dataset B", maximum=HEATMAP_MAX_PER_AXIS)
    subset = _result_subset(results, a, b)
    subset["estimate"] = pd.to_numeric(subset["estimate"], errors="coerce")
    subset["q_value"] = pd.to_numeric(subset["q_value"], errors="coerce")
    subset = subset.loc[np.isfinite(subset["estimate"]) & np.isfinite(subset["q_value"])].copy()
    if len(subset) > BUBBLE_MAX_POINTS:
        raise ValueError(f"Bubble plot supports at most {BUBBLE_MAX_POINTS} eligible selected associations; narrow the feature subset.")
    if subset.empty:
        raise ValueError("No eligible associations are available for the selected feature subset.")

    est = subset["estimate"].to_numpy(float)
    q = subset["q_value"].to_numpy(float)
    if np.any(q < 0.0) or np.any(q > 1.0):
        raise ValueError("Bubble plot requires BH q values between 0 and 1.")

    # Preserve the mathematically correct -log10(q) ordinate for every positive
    # q-value.  Only q == 0 needs a finite display convention because its exact
    # ordinate is +infinity.  Zero values are placed one log10 unit above the
    # strongest positive q-value (with a floor of 12) and disclosed in the
    # subtitle.  Marker sizing remains independently capped for readability.
    positive = q > 0.0
    evidence = np.empty_like(q, dtype=float)
    evidence[positive] = -np.log10(q[positive])
    zero_display_cap: float | None = None
    if np.any(~positive):
        strongest_positive = float(np.nanmax(evidence[positive])) if np.any(positive) else 0.0
        zero_display_cap = max(12.0, float(np.ceil(strongest_positive) + 1.0))
        evidence[~positive] = zero_display_cap
    evidence_for_size = np.minimum(evidence, 12.0)
    if size_by == "effect":
        sizes = 42 + 430 * np.abs(est) ** 1.45
        size_note = "Bubble area emphasizes |correlation|"
    else:
        sizes = 42 + 36 * evidence_for_size
        size_note = "Bubble area emphasizes -log10(BH q), capped at 12"

    with plt.rc_context(_figure_style()):
        fig, ax = plt.subplots(figsize=(8.2, 5.6))
        scatter = ax.scatter(
            est, evidence, c=est, cmap=_CORR_CMAP, norm=Normalize(-1, 1),
            s=sizes, edgecolors=np.where(q <= q_threshold, _INK, "#B8C0CC"),
            linewidths=0.85, alpha=0.88,
        )
        ax.axvline(0.0, color=_GRID, linewidth=0.9, zorder=0)
        ax.axhline(-np.log10(q_threshold), color=_ACCENT, linewidth=1.1, linestyle="--", zorder=0)
        ax.set_xlim(-1.05, 1.05)
        ymax = max(1.0, float(np.nanmax(evidence)) * 1.10)
        ax.set_ylim(0.0, ymax)
        ax.set_xlabel("Correlation coefficient")
        ax.set_ylabel("Statistical evidence  -log10(BH q)")
        zero_note = ""
        if zero_display_cap is not None:
            zero_note = f"; BH q = 0 points are displayed at y = {zero_display_cap:g}"
        axes_top = _add_figure_header(
            fig, "Association bubble plot",
            f"Each point is one validated A×B association; {size_note}; dashed line = BH q {q_threshold:g}{zero_note}.",
        )
        ax.grid(True, color=_GRID, linewidth=0.5, alpha=0.55)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        fig.subplots_adjust(left=0.12, right=0.82, bottom=0.14, top=axes_top)
        cbar = fig.colorbar(scatter, ax=ax, fraction=0.04, pad=0.04)
        cbar.set_label("Correlation coefficient")
        _keep_colorbar_inside_canvas(fig, cbar)
    return fig


def make_scatter_matrix_figure(aligned_a: pd.DataFrame, aligned_b: pd.DataFrame, results: pd.DataFrame,
                               features_a: Sequence[str], features_b: Sequence[str]):
    a = _checked_features(features_a, aligned_a.columns, label="Dataset A", maximum=SCATTER_MATRIX_MAX_VARIABLES)
    b = _checked_features(features_b, aligned_b.columns, label="Dataset B", maximum=SCATTER_MATRIX_MAX_VARIABLES)
    if len(a) + len(b) > SCATTER_MATRIX_MAX_VARIABLES:
        raise ValueError(f"Scatter matrix supports at most {SCATTER_MATRIX_MAX_VARIABLES} variables total across both datasets.")
    selected: list[tuple[str,str,pd.Series]] = []
    selected.extend(("A", name, pd.to_numeric(aligned_a[name], errors="coerce")) for name in a)
    selected.extend(("B", name, pd.to_numeric(aligned_b[name], errors="coerce")) for name in b)
    n = len(selected)
    if n < 2:
        raise ValueError("Scatter matrix requires at least two selected variables.")
    lookup = _result_subset(results, a, b).set_index(["feature_a","feature_b"], drop=False)
    size = min(15.0, max(6.5, 1.55*n + 1.6))
    with plt.rc_context(_figure_style()):
        fig, axes = plt.subplots(n, n, figsize=(size, size), squeeze=False)
        axes_top = _add_figure_header(
            fig,
            "Selected-feature scatter matrix",
            "Lower triangle shows raw sample-level relationships; upper triangle reports statistics only for validated A×B result pairs.",
            title_size=13,
        )
        for i,(source_y,name_y,ser_y) in enumerate(selected):
            for j,(source_x,name_x,ser_x) in enumerate(selected):
                ax=axes[i,j]
                if i==j:
                    vals=ser_x.to_numpy(float); vals=vals[np.isfinite(vals)]
                    if len(vals): ax.hist(vals,bins=min(14,max(5,int(np.sqrt(len(vals))))),color="#A7B8CA",edgecolor="white",linewidth=0.5)
                    ax.text(0.05,0.9,f"{source_x} · {name_x}",transform=ax.transAxes,ha="left",va="top",fontsize=7.6,fontweight="bold")
                elif i>j:
                    x=ser_x.to_numpy(float); y=ser_y.to_numpy(float); mask=np.isfinite(x)&np.isfinite(y)
                    ax.scatter(x[mask],y[mask],s=8,alpha=0.5,color=_POINT,edgecolors="none")
                else:
                    # Only cross-dataset A×B inferential values already present in validated results are displayed.
                    key=None
                    if source_x=="A" and source_y=="B": key=(name_x,name_y)
                    elif source_x=="B" and source_y=="A": key=(name_y,name_x)
                    if key is not None and key in lookup.index:
                        r=lookup.loc[key]
                        if isinstance(r,pd.DataFrame): r=r.iloc[0]
                        est=float(r["estimate"]); q=float(r["q_value"]); nn=int(r["n_pairwise"])
                        ax.text(0.5,0.59,f"{est:+.2f}",transform=ax.transAxes,ha="center",va="center",fontsize=13,fontweight="bold",color=_POS if est>0 else _NEG if est<0 else _INK)
                        ax.text(0.5,0.39,f"N={nn}\nq={_format_p(q)}",transform=ax.transAxes,ha="center",va="center",fontsize=7.3,color=_MUTED)
                    else:
                        ax.text(0.5,0.5,"raw view\n(no added inference)",transform=ax.transAxes,ha="center",va="center",fontsize=7.1,color=_MUTED)
                    ax.set_xticks([]); ax.set_yticks([])
                if i<n-1: ax.set_xticklabels([])
                if j>0: ax.set_yticklabels([])
                ax.tick_params(labelsize=6,length=2)
                ax.spines[["top","right"]].set_visible(False)
                ax.grid(False)
        fig.subplots_adjust(left=0.07,right=0.99,bottom=0.06,top=axes_top,wspace=0.08,hspace=0.08)
    return fig


def export_figure(fig, root: Path, stem: str) -> tuple[str, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in stem)[:120]
    png = root / f"{safe}.png"; svg = root / f"{safe}.svg"; pdf = root / f"{safe}.pdf"
    # Export-related rcParams must remain active during savefig(), not only while
    # the figure object is constructed. In particular this preserves SVG text as
    # <text> elements instead of converting labels to paths.
    with plt.rc_context(_figure_style()):
        fig.savefig(png, dpi=300, bbox_inches="tight")
        fig.savefig(svg, bbox_inches="tight")
        fig.savefig(pdf, format="pdf", bbox_inches="tight")
    return str(png), str(svg), str(pdf)


def export_pair_figure(fig, root: Path, stem: str) -> tuple[str, str, str]:
    # Backward-compatible name used by RC3/RC4 tests and callers.
    return export_figure(fig, root, stem)
