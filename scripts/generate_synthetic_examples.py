from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260917
N = 80
TEACHING_SEED = SEED + 404


def _teaching_data(samples: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Create deterministic pedagogic pairs with visibly distinct scatter structures."""
    rng = np.random.default_rng(TEACHING_SEED)

    linear_x = np.linspace(-2.5, 2.5, N) + rng.normal(0.0, 0.04, N)
    linear_y = 1.7 * linear_x + rng.normal(0.0, 0.25, N)

    negative_x = np.linspace(-2.5, 2.5, N) + rng.normal(0.0, 0.04, N)
    negative_y = -1.6 * negative_x + rng.normal(0.0, 0.25, N)

    nonlinear_x = np.linspace(-2.0, 2.0, N) + rng.normal(0.0, 0.03, N)
    nonlinear_y = np.exp(0.9 * nonlinear_x) + rng.normal(0.0, 0.08, N)

    outlier_x = rng.normal(size=N)
    outlier_y = outlier_x + rng.normal(0.0, 0.25, N)
    outlier_index = int(np.argmax(outlier_x))
    outlier_x[outlier_index] = 8.0
    outlier_y[outlier_index] = -8.0

    null_x = rng.normal(size=N)
    null_y = rng.normal(size=N)

    missing_x = rng.normal(size=N)
    missing_y = 0.9 * missing_x + rng.normal(0.0, 0.35, N)
    missing_y[::5] = np.nan

    a = pd.DataFrame(
        {
            "linear_signal": linear_x,
            "negative_driver": negative_x,
            "monotonic_driver": nonlinear_x,
            "outlier_driver": outlier_x,
            "null_a": null_x,
            "missing_driver": missing_x,
            "constant_a": np.ones(N),
        },
        index=samples,
    )
    b = pd.DataFrame(
        {
            "linear_partner": linear_y,
            "negative_partner": negative_y,
            "monotonic_nonlinear": nonlinear_y,
            "outlier_partner": outlier_y,
            "null_b": null_y,
            "missing_partner": missing_y,
            "constant_b": np.full(N, 3.0),
        },
        index=samples,
    )

    truth = {
        "note": "Synthetic pedagogic structure only; not a biological simulation.",
        "linear_pair": ["linear_signal", "linear_partner"],
        "negative_linear_pair": ["negative_driver", "negative_partner"],
        "monotonic_nonlinear_pair": ["monotonic_driver", "monotonic_nonlinear"],
        "outlier_sensitive_pair": ["outlier_driver", "outlier_partner"],
        "null_pair": ["null_a", "null_b"],
        "missing_pair": ["missing_driver", "missing_partner"],
        "constant_features": ["constant_a", "constant_b"],
        "plot_presets": [
            {
                "label": "Strong positive linear",
                "feature_a": "linear_signal",
                "feature_b": "linear_partner",
                "description": "Tight positive linear association; Pearson and Spearman are both very high.",
            },
            {
                "label": "Strong negative linear",
                "feature_a": "negative_driver",
                "feature_b": "negative_partner",
                "description": "Tight negative linear association with both Pearson and Spearman strongly negative.",
            },
            {
                "label": "Monotonic nonlinear",
                "feature_a": "monotonic_driver",
                "feature_b": "monotonic_nonlinear",
                "description": "Curved monotonic relationship where Spearman is stronger than Pearson.",
            },
            {
                "label": "Outlier-sensitive",
                "feature_a": "outlier_driver",
                "feature_b": "outlier_partner",
                "description": "A strong monotonic trend with one extreme discordant point; Pearson is heavily attenuated while Spearman remains high.",
            },
            {
                "label": "Null cloud",
                "feature_a": "null_a",
                "feature_b": "null_b",
                "description": "Independent noise with no planted association.",
            },
            {
                "label": "Missing pair",
                "feature_a": "missing_driver",
                "feature_b": "missing_partner",
                "description": "Positive relationship with deterministic missing values so pairwise N is lower than the matched sample count.",
            },
        ],
    }
    return a, b, truth


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "biostat_tool" / "example_data"
    guard = out / "guardrails"
    out.mkdir(parents=True, exist_ok=True)
    guard.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    samples = [f"S{i:03d}" for i in range(1, N + 1)]
    latent = rng.normal(size=N)
    latent2 = rng.normal(size=N)

    met = pd.DataFrame(index=samples)
    met["Met_001"] = latent + rng.normal(scale=0.45, size=N)
    met["Met_002"] = -0.7 * latent2 + rng.normal(scale=0.65, size=N)
    for j in range(3, 17):
        met[f"Met_{j:03d}"] = rng.normal(size=N)
    met.loc[["S007", "S029"], "Met_004"] = np.nan
    met.loc[["S015"], "Met_011"] = np.nan
    met.to_csv(out / "metabolomics_quantitative.csv", index_label="id")

    rna = pd.DataFrame(index=samples)
    rna["Gene_001"] = 8 + 1.1 * latent + rng.normal(scale=0.45, size=N)
    rna["Gene_002"] = 8 - 0.9 * latent2 + rng.normal(scale=0.55, size=N)
    for j in range(3, 21):
        rna[f"Gene_{j:03d}"] = rng.normal(loc=8, scale=1.8, size=N)
    rna.to_csv(out / "rnaseq_vst.csv", index_label="id")

    prot = pd.DataFrame(index=samples)
    prot["Prot_001"] = 10 + 0.85 * latent + rng.normal(scale=0.55, size=N)
    prot["Prot_002"] = 10 + 0.65 * latent2 + rng.normal(scale=0.65, size=N)
    for j in range(3, 15):
        prot[f"Prot_{j:03d}"] = rng.normal(loc=10, scale=1.4, size=N)
    prot.to_csv(out / "proteomics_quantitative.csv", index_label="id")

    alpha = np.linspace(0.8, 2.0, 12)
    comps = rng.dirichlet(alpha, size=N)
    comps[:, 0] *= np.exp(0.35 * latent)
    comps /= comps.sum(axis=1, keepdims=True)
    clr = np.log(comps) - np.log(comps).mean(axis=1, keepdims=True)
    meta = pd.DataFrame(clr, index=samples, columns=[f"Species_{i:03d}" for i in range(1, 13)])
    meta.to_csv(out / "metagenomics_clr.csv", index_label="id")

    alpha16 = np.linspace(1.0, 2.2, 10)
    comps16 = rng.dirichlet(alpha16, size=N)
    comps16[:, 1] *= np.exp(-0.30 * latent2)
    comps16 /= comps16.sum(axis=1, keepdims=True)
    clr16 = np.log(comps16) - np.log(comps16).mean(axis=1, keepdims=True)
    amp = pd.DataFrame(clr16, index=samples, columns=[f"ASV_{i:03d}" for i in range(1, 11)])
    amp.to_csv(out / "16s_clr.csv", index_label="id")

    generic = pd.DataFrame(index=samples)
    generic["Marker_001"] = 0.7 * latent + rng.normal(scale=0.7, size=N)
    generic["Marker_002"] = np.tanh(latent2) + rng.normal(scale=0.25, size=N)
    for j in range(3, 11):
        generic[f"Marker_{j:03d}"] = rng.normal(size=N)
    generic.to_csv(out / "generic_numeric.csv", index_label="id")

    raw = pd.DataFrame(
        rng.negative_binomial(n=12, p=0.40, size=(N, 20)),
        index=samples,
        columns=[f"Gene_{i:03d}" for i in range(1, 21)],
    )
    raw.to_csv(guard / "rnaseq_raw_counts_BLOCKED.csv", index_label="id")
    pd.DataFrame(comps, index=samples, columns=meta.columns).to_csv(
        guard / "metagenomics_relative_abundance_BLOCKED.csv", index_label="id"
    )
    pd.DataFrame(comps16, index=samples, columns=amp.columns).to_csv(
        guard / "16s_relative_abundance_BLOCKED.csv", index_label="id"
    )
    dup = met.reset_index(names="id").copy()
    dup.loc[1, "id"] = dup.loc[0, "id"]
    dup.to_csv(guard / "duplicate_sample_ids_BLOCKED.csv", index=False)

    teaching_a, teaching_b, teaching_truth = _teaching_data(samples)
    teaching_a.to_csv(out / "teaching_correlation_a.csv", index_label="sample_id")
    teaching_b.to_csv(out / "teaching_correlation_b.csv", index_label="sample_id")

    catalog = {
        "schema_version": "1.0",
        "seed": SEED,
        "notice": "All bundled examples are completely synthetic and are not derived from real participants.",
        "examples": {
            "metabolomics_rnaseq": {
                "label": "Metabolomics × RNA-seq (VST)",
                "description": "Processed quantitative metabolomics paired with transformed RNA-seq expression; includes planted positive and negative cross-omics associations.",
                "a": {"file": "metabolomics_quantitative.csv", "data_type": "metabolomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative metabolomics values."},
                "b": {"file": "rnaseq_vst.csv", "data_type": "rna_seq", "preprocessing": "vst", "details": "Synthetic continuous VST-like expression values; not raw counts."},
                "method": "spearman",
                "design": "independent",
            },
            "metabolomics_proteomics": {
                "label": "Metabolomics × Proteomics",
                "description": "Processed quantitative metabolomics and proteomics with shared latent synthetic signals.",
                "a": {"file": "metabolomics_quantitative.csv", "data_type": "metabolomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative metabolomics values."},
                "b": {"file": "proteomics_quantitative.csv", "data_type": "proteomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative protein abundances."},
                "method": "pearson",
                "design": "independent",
            },
            "metabolomics_metagenomics": {
                "label": "Metabolomics × Metagenomics (CLR)",
                "description": "Processed metabolomics paired with synthetic CLR coordinates derived from strictly positive compositions.",
                "a": {"file": "metabolomics_quantitative.csv", "data_type": "metabolomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative metabolomics values."},
                "b": {"file": "metagenomics_clr.csv", "data_type": "metagenomics", "preprocessing": "clr", "details": "Synthetic strictly positive composition; no zero replacement required; CLR uses all 12 retained species as the geometric-mean reference set."},
                "method": "spearman",
                "design": "independent",
            },
            "16s_generic": {
                "label": "16S CLR × Generic biomarkers",
                "description": "Synthetic 16S CLR coordinates paired with a generic quantitative biomarker panel.",
                "a": {"file": "16s_clr.csv", "data_type": "16s", "preprocessing": "clr", "details": "Synthetic strictly positive composition; no zero replacement required; CLR uses all 10 retained ASVs as the geometric-mean reference set."},
                "b": {"file": "generic_numeric.csv", "data_type": "generic", "preprocessing": "declared_numeric", "details": "Synthetic continuous biomarker measurements."},
                "method": "spearman",
                "design": "independent",
            },
            "pearson_spearman_teaching": {
                "label": "Teaching: Pearson vs Spearman",
                "description": "Visually distinct synthetic patterns: positive linear, negative linear, monotonic nonlinear, outlier-sensitive, null, missingness, and constant-feature cases.",
                "a": {"file": "teaching_correlation_a.csv", "data_type": "generic", "preprocessing": "declared_numeric", "details": "Synthetic quantitative teaching drivers with deliberately different scatter structures."},
                "b": {"file": "teaching_correlation_b.csv", "data_type": "generic", "preprocessing": "declared_numeric", "details": "Synthetic paired teaching outcomes for Pearson/Spearman comparison."},
                "method": "spearman",
                "design": "independent",
            },
            "rnaseq_raw_blocked": {
                "label": "Guardrail: raw RNA-seq counts (BLOCKED)",
                "description": "Demonstrates the raw-count guardrail. Dataset A is intentionally unsuitable for ordinary Pearson/Spearman correlation.",
                "a": {"file": "guardrails/rnaseq_raw_counts_BLOCKED.csv", "data_type": "rna_seq", "preprocessing": "raw_counts", "details": "Synthetic raw integer counts; intentionally blocked."},
                "b": {"file": "metabolomics_quantitative.csv", "data_type": "metabolomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative metabolomics values."},
                "method": "spearman",
                "design": "independent",
            },
            "microbiome_relative_blocked": {
                "label": "Guardrail: metagenomics relative abundance (BLOCKED)",
                "description": "Demonstrates the compositional-data guardrail for relative abundance input.",
                "a": {"file": "guardrails/metagenomics_relative_abundance_BLOCKED.csv", "data_type": "metagenomics", "preprocessing": "relative_abundance", "details": "Synthetic relative-abundance composition; intentionally blocked."},
                "b": {"file": "metabolomics_quantitative.csv", "data_type": "metabolomics", "preprocessing": "quantitative", "details": "Synthetic processed quantitative metabolomics values."},
                "method": "spearman",
                "design": "independent",
            },
        },
    }
    (out / "catalog.json").write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    truth = {
        "schema_version": "1.0",
        "seed": SEED,
        "n_samples": N,
        "purpose": "Software demonstration and regression support; not a biological simulator.",
        "pearson_spearman_teaching": teaching_truth,
        "planted_relationships": [
            {"feature_a": "Met_001", "feature_b": "Gene_001", "relationship": "shared latent linear positive"},
            {"feature_a": "Met_002", "feature_b": "Gene_002", "relationship": "shared latent relationship"},
            {"feature_a": "Met_001", "feature_b": "Prot_001", "relationship": "shared latent linear positive"},
            {"feature_a": "Met_002", "feature_b": "Prot_002", "relationship": "shared latent relationship"},
        ],
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "README.md").write_text(
        "# Synthetic example library\n\n"
        "All files in this directory are completely synthetic and are not derived from real participants. "
        "They demonstrate supported matrix structures and software safeguards; they are not claimed to reproduce the full biological distribution of a real assay.\n\n"
        "`catalog.json` powers the browser Load Example workflow. `truth.json` records planted relationships and curated teaching plot presets for regression support. "
        "Regenerate with `python scripts/generate_synthetic_examples.py`.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
