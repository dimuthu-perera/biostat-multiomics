from __future__ import annotations

import base64
import io

import gradio as gr
import matplotlib.pyplot as plt
import numpy as np
import pytest
from PIL import Image

from biostat_tool.visualization import PairPlotData, make_pair_figure


@pytest.mark.parametrize("glyph", ["X", "W"])
def test_gradio_pair_preview_contains_complete_long_identifier_bounds(glyph: str) -> None:
    identifier = glyph * 240
    fig = make_pair_figure(
        PairPlotData(
            identifier,
            identifier,
            np.arange(5.0),
            np.arange(5.0),
            5,
            0,
        ),
        method="pearson",
        estimate=1.0,
        p_value=0.1,
        q_value=0.1,
    )
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        canvas = fig.get_window_extent(renderer=renderer)
        ax = fig.axes[0]
        artists = [fig.texts[0], fig.texts[1], ax.xaxis.label, ax.yaxis.label]

        for artist in artists:
            bounds = artist.get_window_extent(renderer=renderer)
            assert bounds.x0 >= canvas.x0
            assert bounds.y0 >= canvas.y0
            assert bounds.x1 <= canvas.x1
            assert bounds.y1 <= canvas.y1

        # Full source identifiers remain present in the title; only the axis
        # display labels may be abbreviated.
        assert identifier in fig.texts[0].get_text().replace("\n", "").replace(" ", "")

        payload = gr.Plot().postprocess(fig)
        assert payload.type == "matplotlib"
        assert payload.plot.startswith("data:image/webp;base64,")
        raw = base64.b64decode(payload.plot.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as preview:
            assert preview.size == fig.canvas.get_width_height()
    finally:
        plt.close(fig)
