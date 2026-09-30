from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd


def render_html_report(
    run_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    verify_bundle: bool = True,
) -> Path:
    """Render a compact static HTML report from an existing completed RunBundle.

    This function never reruns statistics. Public calls verify the RunBundle before
    reading results; bundle construction can opt out while the manifest inventory is
    still being finalized.
    """
    run_dir = Path(run_dir)
    if verify_bundle:
        from .bundle import verify_run_bundle

        verify_run_bundle(run_dir, verify_hashes=True).require_valid()

    manifest_path = run_dir / "manifest.json"
    provenance_path = run_dir / "provenance.json"
    if not manifest_path.is_file() or not provenance_path.is_file():
        raise FileNotFoundError("RunBundle must contain manifest.json and provenance.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    result_meta = manifest.get("results", {})
    primary_rel = result_meta.get("primary_table")
    schema_rel = result_meta.get("schema")
    if not isinstance(primary_rel, str) or not isinstance(schema_rel, str):
        raise ValueError("RunBundle manifest does not declare a primary result table and result schema.")
    results_path = run_dir / primary_rel
    schema_path = run_dir / schema_rel
    if not results_path.is_file() or not schema_path.is_file():
        raise FileNotFoundError("RunBundle primary result table or result schema is missing.")
    result_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    oracle_manifest = provenance.get("oracle", {}).get("manifest", {})

    # CSV is a transport representation. Reconstruct column types from the bundled
    # result schema rather than allowing pandas to reinterpret scientific identifiers
    # such as "001", "NA", or exponent-looking strings.
    columns = result_schema.get("columns", [])
    string_columns = {c.get("name") for c in columns if c.get("storage_type") == "string"}
    numeric_columns = {c.get("name") for c in columns if c.get("storage_type") in {"number", "integer"}}
    boolean_columns = {c.get("name") for c in columns if c.get("storage_type") == "boolean"}
    dtype_map = {name: "string" for name in string_columns if isinstance(name, str)}
    results = pd.read_csv(results_path, dtype=dtype_map, keep_default_na=False)
    for name in numeric_columns:
        if isinstance(name, str) and name in results.columns:
            results[name] = pd.to_numeric(results[name], errors="coerce")
    for name in boolean_columns:
        if isinstance(name, str) and name in results.columns:
            results[name] = results[name].map({"True": True, "False": False, "": pd.NA}).astype("boolean")
    if "status" in results.columns:
        ranked = results[results["status"].isin(["ok", "ok_with_warning"])].copy()
    else:
        ranked = results.copy()
    if "q_value" in ranked.columns and "p_value" in ranked.columns:
        ranked = ranked.sort_values(["q_value", "p_value"], na_position="last").head(50)
    else:
        ranked = ranked.head(50)

    def pre(obj: object) -> str:
        return "<pre>" + html.escape(json.dumps(obj, indent=2, ensure_ascii=False)) + "</pre>"

    table = ranked.to_html(index=False, escape=True, border=0) if not ranked.empty else "<p>No testable rows.</p>"
    pairwise_n_summary: dict[str, object] = {}
    if "n_pairwise" in results.columns:
        n_values = pd.to_numeric(results["n_pairwise"], errors="coerce").dropna()
        if not n_values.empty:
            pairwise_n_summary = {
                "minimum": int(n_values.min()),
                "median": float(n_values.median()),
                "maximum": int(n_values.max()),
                "pairs_below_10": int((n_values < 10).sum()),
                "total_pairs": int(len(n_values)),
            }
    title = "Biostat Research Tool — Correlation Run Report"
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{border:1px solid #ddd;padding:.35rem;text-align:left}}pre{{background:#f5f5f5;padding:1rem;overflow:auto}}</style></head>
<body><h1>{html.escape(title)}</h1>
<p>This report is rendered from an existing completed RunBundle; report generation does not rerun the statistical analysis.</p>
<h2>Run summary</h2>{pre({
        'bundle_schema_version': manifest.get('bundle_schema_version'),
        'platform_version': manifest.get('platform', {}).get('version'),
        'created_utc': manifest.get('created_utc'),
        'analysis_spec_sha256': manifest.get('analysis', {}).get('effective_spec_sha256'),
        'oracle_engine_version': manifest.get('oracle_engine', {}).get('version'),
    })}
<h2>Top testable associations</h2>{table}
<h2>FDR family</h2>{pre(oracle_manifest.get('fdr_family', {}))}
<h2>Pairwise sample-size summary</h2>{pre(pairwise_n_summary)}
<h2>Study design</h2>{pre(oracle_manifest.get('study_design', {}))}
<h2>Statistical policy</h2>{pre(provenance.get('statistical_policy', {}))}
<h2>Interpretation notes</h2>{pre(oracle_manifest.get('interpretation', {}))}
</body></html>"""
    canonical = (run_dir / "report" / "report.html").resolve()
    if output_path is None:
        # A completed RunBundle is immutable. The bundled report already exists;
        # public report commands return it instead of rewriting bundle contents.
        if canonical.is_file():
            return canonical
        out = canonical
    else:
        out = Path(output_path).resolve()
        try:
            inside_bundle = out.is_relative_to(run_dir.resolve())
        except AttributeError:  # pragma: no cover - Python 3.13 baseline has is_relative_to
            inside_bundle = str(out).startswith(str(run_dir.resolve()) + str(Path('/')))
        if inside_bundle and out != canonical:
            raise ValueError("Rendered report output must be outside the immutable RunBundle, or exactly report/report.html during bundle construction.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out
