from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from correlation_tool import inspect_dataset, load_matrix, sha256_file
from correlation_tool.inspection import DatasetDeclaration

from . import __version__
from .bundle import default_run_directory, verify_run_bundle, write_run_bundle
from .reporting import render_html_report
from .runner import execute_prepared, prepare_analysis
from .specs import AnalysisSpec, DatasetSpec, SpecError, load_analysis_spec


def _print_json(obj: object) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _inspection_summary(prepared) -> dict[str, object]:
    doc = dict(prepared.inspection_document)
    return {
        "analysis_type": prepared.analysis_type,
        "module": {"id": prepared.module_id, "version": prepared.module_version},
        "run_fingerprint": prepared.run_fingerprint,
        "blocked": prepared.blocked,
        "warnings": list(prepared.warning_issue_ids),
        "alignment": dict(prepared.alignment_document),
        "issues": list(doc.get("issues", [])),
        "statistical_policy": {
            "version": prepared.statistical_policy_version,
            "advisories": list(prepared.policy_advisories),
        },
    }


def cmd_validate(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).resolve()
    spec = load_analysis_spec(spec_path)
    prepared = prepare_analysis(
        spec,
        base_dir=spec_path.parent,
        path_overrides={k: v for k, v in {"dataset_a": args.dataset_a, "dataset_b": args.dataset_b}.items() if v},
    )
    summary = _inspection_summary(prepared)
    if args.json:
        _print_json(summary)
    else:
        state = "BLOCKED" if prepared.blocked else ("WARNING" if prepared.warning_issue_ids else "PASS")
        print(f"Inspection: {state}")
        print(f"Run fingerprint: {prepared.run_fingerprint}")
        alignment = prepared.alignment_document
        if alignment.get("n_common") is not None:
            print(f"Matched samples: {alignment['n_common']}")
        for issue in prepared.inspection_document.get("issues", []):
            print(f"[{issue['severity']}] {issue['issue_id']}: {issue['message']}")
        for advisory in prepared.policy_advisories:
            print(f"[{advisory['level']}] policy:{advisory['code']}: {advisory['message']}")
    return 2 if prepared.blocked else 0


def cmd_run(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).resolve()
    spec = load_analysis_spec(spec_path)
    prepared = prepare_analysis(
        spec,
        base_dir=spec_path.parent,
        path_overrides={k: v for k, v in {"dataset_a": args.dataset_a, "dataset_b": args.dataset_b}.items() if v},
    )
    completed = execute_prepared(
        prepared,
        acknowledge_warnings=args.acknowledge_warnings,
        backend=args.backend,
        verify_against_reference=args.verify_against_reference,
    )
    root = Path(args.output_root or spec.outputs.root)
    if not root.is_absolute():
        root = (spec_path.parent / root).resolve()
    destination = Path(args.output).resolve() if args.output else default_run_directory(root, prepared.run_fingerprint)
    run_dir = write_run_bundle(completed, destination)
    print(run_dir)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.data).resolve()
    df = load_matrix(path, args.orientation, missing_tokens=tuple(args.missing_token))
    decl = DatasetDeclaration(args.data_type, args.preprocessing, args.name, args.preprocessing_details or "")
    report = inspect_dataset(df, decl)
    _print_json(
        {
            "path": str(path),
            "sha256": sha256_file(path),
            "shape_samples_by_features": list(df.shape),
            "metrics": report.metrics,
            "status": report.status.value,
            "issues": [{"severity": x.severity.value, "code": x.code, "message": x.message} for x in report.issues],
        }
    )
    return 2 if report.is_blocked else 0


def cmd_report(args: argparse.Namespace) -> int:
    out = render_html_report(args.run_dir, args.output)
    print(out)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import launch

    launch(server_name=args.host, server_port=args.port, inbrowser=not args.no_browser)
    return 0



def cmd_verify(args: argparse.Namespace) -> int:
    report = verify_run_bundle(args.run_dir, verify_hashes=not args.no_hashes)
    payload = {
        "valid": report.valid,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "bundle_schema_version": None if report.manifest is None else report.manifest.get("bundle_schema_version"),
        "run_fingerprint": None if report.manifest is None else report.manifest.get("analysis", {}).get("run_fingerprint"),
    }
    if args.json:
        _print_json(payload)
    else:
        print("RunBundle: " + ("VALID" if report.valid else "INVALID"))
        for warning in report.warnings:
            print(f"[warning] {warning}")
        for error in report.errors:
            print(f"[error] {error}")
    return 0 if report.valid else 2


def cmd_bundle_schema(args: argparse.Namespace) -> int:
    from importlib.resources import files
    schema_path = files("biostat_tool").joinpath("schemas/run-bundle-manifest-v1.schema.json")
    print(schema_path.read_text(encoding="utf-8"), end="")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    from importlib.resources import files
    schema_path = files("biostat_tool").joinpath("schemas/analysis-spec-v1.schema.json")
    print(schema_path.read_text(encoding="utf-8"), end="")
    return 0



def cmd_modules(args: argparse.Namespace) -> int:
    from .modules.registry import registered_analysis_types, get_analysis_module

    payload = []
    for analysis_type in registered_analysis_types():
        module = get_analysis_module(analysis_type)
        payload.append({
            "analysis_type": analysis_type,
            "module_id": module.module_id,
            "module_version": module.module_version,
        })
    if args.json:
        _print_json(payload)
    else:
        for item in payload:
            print(f"{item['analysis_type']}\t{item['module_id']}\t{item['module_version']}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="biostat", description="Local-first biostatistics research tool")
    p.add_argument("--version", action="version", version=f"biostat {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="Validate and inspect an AnalysisSpec without running inference")
    v.add_argument("spec")
    v.add_argument("--json", action="store_true")
    v.add_argument("--dataset-a", help="Runtime path override for dataset A; SHA-256 must still match the specification")
    v.add_argument("--dataset-b", help="Runtime path override for dataset B; SHA-256 must still match the specification")
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="Execute an AnalysisSpec using the shared validated runner")
    r.add_argument("spec")
    r.add_argument("--acknowledge-warnings", action="store_true", help="Acknowledge all current warnings for this exact inspected fingerprint")
    r.add_argument("--dataset-a", help="Runtime path override for dataset A; SHA-256 must still match the specification")
    r.add_argument("--dataset-b", help="Runtime path override for dataset B; SHA-256 must still match the specification")
    r.add_argument("--output", help="Exact RunBundle directory; must not already exist")
    r.add_argument("--output-root", help="Override outputs.root from the specification")
    r.add_argument(
        "--backend",
        choices=["reference", "optimized", "auto"],
        default="auto",
        help="Runtime execution backend. Default auto uses independently accepted optimized Pearson/Spearman paths when eligible and transparently falls back to the frozen reference backend otherwise.",
    )
    r.add_argument(
        "--verify-against-reference",
        action="store_true",
        help="For an optimized run, also execute the frozen scalar oracle and require the explicit equivalence contract to pass.",
    )
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("inspect", help="Inspect one dataset without running an analysis")
    i.add_argument("data")
    i.add_argument("--orientation", choices=["samples_rows", "samples_columns"], required=True)
    i.add_argument("--data-type", required=True)
    i.add_argument("--preprocessing", required=True)
    i.add_argument("--preprocessing-details", default="")
    i.add_argument("--name", default="dataset")
    i.add_argument("--missing-token", action="append", default=["", "NA", "N/A", "NaN", "nan"])
    i.set_defaults(func=cmd_inspect)

    rep = sub.add_parser("report", help="Render HTML from an existing completed RunBundle; does not rerun analysis")
    rep.add_argument("run_dir")
    rep.add_argument("--output")
    rep.set_defaults(func=cmd_report)

    sch = sub.add_parser("schema", help="Print the canonical AnalysisSpec v1 JSON Schema")
    sch.set_defaults(func=cmd_schema)

    ver = sub.add_parser("verify", help="Verify a completed RunBundle structure and integrity hashes")
    ver.add_argument("run_dir")
    ver.add_argument("--json", action="store_true")
    ver.add_argument("--no-hashes", action="store_true", help="Skip content SHA-256 checks; structural checks still run")
    ver.set_defaults(func=cmd_verify)

    bsch = sub.add_parser("bundle-schema", help="Print the RunBundle manifest v1 JSON Schema")
    bsch.set_defaults(func=cmd_bundle_schema)

    mods = sub.add_parser("modules", help="List registered AnalysisModule implementations")
    mods.add_argument("--json", action="store_true")
    mods.set_defaults(func=cmd_modules)

    s = sub.add_parser("serve", help="Launch the local browser interface")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7860)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SpecError, ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
