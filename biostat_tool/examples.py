from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def example_root() -> Path:
    return Path(__file__).resolve().parent / "example_data"


def load_example_catalog() -> dict[str, Any]:
    return json.loads((example_root() / "catalog.json").read_text(encoding="utf-8"))


def example_choices() -> list[tuple[str, str]]:
    catalog = load_example_catalog()["examples"]
    def order(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        key, entry = item
        label = str(entry["label"])
        if label.startswith("Same-domain:"):
            group = 0
        elif label.startswith(("Cross-omics:", "Cross-domain:")):
            group = 1
        elif label.startswith("Teaching:"):
            group = 2
        elif label.startswith("Guardrail:"):
            group = 3
        else:
            group = 4
        return group, label
    return [(entry["label"], key) for key, entry in sorted(catalog.items(), key=order)]


def get_example(key: str) -> dict[str, Any]:
    catalog = load_example_catalog()
    examples = catalog["examples"]
    if key not in examples:
        raise KeyError(f"Unknown synthetic example: {key}")
    entry = dict(examples[key])
    root = example_root()
    entry["a"] = dict(entry["a"])
    entry["b"] = dict(entry["b"])
    entry["a"]["path"] = str(root / entry["a"].pop("file"))
    entry["b"]["path"] = str(root / entry["b"].pop("file"))
    entry["notice"] = catalog["notice"]
    entry["seed"] = catalog["seed"]
    return entry


def teaching_plot_presets() -> dict[tuple[str, str], dict[str, str]]:
    """Return curated synthetic teaching-pair labels keyed by (feature_a, feature_b).

    This metadata is used only to make the bundled teaching example easier to
    explore; it has no effect on statistical computation or user datasets.
    """
    truth_path = example_root() / "truth.json"
    if not truth_path.is_file():
        return {}
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    teaching = truth.get("pearson_spearman_teaching", {})
    presets = teaching.get("plot_presets", [])
    out: dict[tuple[str, str], dict[str, str]] = {}
    for item in presets:
        if not isinstance(item, dict):
            continue
        a = item.get("feature_a")
        b = item.get("feature_b")
        label = item.get("label")
        if isinstance(a, str) and isinstance(b, str) and isinstance(label, str):
            out[(a, b)] = {
                "label": label,
                "description": str(item.get("description", "")),
            }
    return out
