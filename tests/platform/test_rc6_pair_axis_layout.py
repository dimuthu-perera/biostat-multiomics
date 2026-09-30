from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from biostat_tool.visualization import PairPlotData, export_figure, make_pair_figure


def _assert_pair_label_layout(fig, full_identifier: str) -> None:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    title_box = fig.texts[0].get_window_extent(renderer=renderer)
    subtitle_box = fig.texts[1].get_window_extent(renderer=renderer)
    ax = fig.axes[0]
    x_box = ax.xaxis.label.get_window_extent(renderer=renderer)
    y_box = ax.yaxis.label.get_window_extent(renderer=renderer)
    axes_box = ax.get_window_extent(renderer=renderer)
    canvas_box = fig.get_window_extent(renderer=renderer)

    # Header order and a usable plotting band.
    assert title_box.y0 > subtitle_box.y1
    assert subtitle_box.y0 > axes_box.y1
    assert axes_box.height / canvas_box.height >= 0.25

    # Axis labels must remain below the statistical header and inside the canvas.
    assert y_box.y1 < subtitle_box.y0
    assert x_box.y1 < subtitle_box.y0
    assert y_box.x0 >= canvas_box.x0
    assert y_box.y0 >= canvas_box.y0
    assert x_box.x0 >= canvas_box.x0
    assert x_box.y0 >= canvas_box.y0
    assert y_box.x1 <= canvas_box.x1
    assert x_box.x1 <= canvas_box.x1

    # Complete identifiers remain available in the figure title even if the axes
    # use bounded display labels.
    assert "".join(full_identifier.split()) in "".join(fig.texts[0].get_text().split())
    assert "display label" in ax.get_xlabel()
    assert "display label" in ax.get_ylabel()


def _pair(identifier: str, *, method: str = "pearson", view: str = "raw"):
    data = PairPlotData(
        feature_a=identifier,
        feature_b=identifier,
        x=np.arange(5, dtype=float),
        y=np.arange(5, dtype=float) * 1.25 + 0.5,
        n_pairwise=5,
        missing_or_excluded=0,
    )
    return make_pair_figure(
        data,
        method=method,
        estimate=0.93,
        p_value=0.007,
        q_value=0.014,
        view=view,
    )


def _assert_exports(fig, tmp_path: Path, stem: str) -> None:
    png, svg, pdf = export_figure(fig, tmp_path, stem)
    for path in (Path(png), Path(svg), Path(pdf)):
        assert path.is_file()
        assert path.stat().st_size > 0
    assert Path(png).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert Path(pdf).read_bytes().startswith(b"%PDF-")
    svg_text = Path(svg).read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert "<text" in svg_text


def test_pair_layout_bounds_repeated_long_identifier_and_exports(tmp_path):
    identifier = " ".join(["long identifier"] * 16)
    fig = _pair(identifier)
    try:
        _assert_pair_label_layout(fig, identifier)
        _assert_exports(fig, tmp_path, "repeated_long_identifier")
    finally:
        plt.close(fig)


def test_pair_layout_bounds_unbroken_240_character_identifier_and_exports(tmp_path):
    identifier = "X" * 240
    fig = _pair(identifier)
    try:
        _assert_pair_label_layout(fig, identifier)
        _assert_exports(fig, tmp_path, "unbroken_240_identifier")
    finally:
        plt.close(fig)


def test_long_spearman_axis_display_labels_preserve_average_rank_semantics():
    identifier = "X" * 240
    fig = _pair(identifier, method="spearman", view="ranks")
    try:
        ax = fig.axes[0]
        assert "average rank" in ax.get_xlabel()
        assert "average rank" in ax.get_ylabel()
        assert "".join(identifier.split()) in "".join(fig.texts[0].get_text().split())
    finally:
        plt.close(fig)
