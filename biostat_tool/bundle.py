from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd


from . import __version__ as PLATFORM_VERSION
from .modules.base import CompletedAnalysis

BUNDLE_SCHEMA_VERSION = "1.0"
BUNDLE_TYPE = "biostat_run"
BASE_REQUIRED_FILES = frozenset(
    {
        "analysis.json",
        "analysis.requested.json",
        "inspection.json",
        "alignment.json",
        "provenance.json",
        "report/report.html",
        "logs/run.log",
    }
)


class RunBundleError(RuntimeError):
    """Raised when a RunBundle is incomplete or fails integrity validation."""


@dataclass(frozen=True)
class RunBundleVerification:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest: dict[str, Any] | None = None

    def require_valid(self) -> "RunBundleVerification":
        if not self.valid:
            raise RunBundleError("RunBundle verification failed: " + "; ".join(self.errors))
        return self


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        fv = float(value)
        return fv if math.isfinite(fv) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _write_json(path: Path, obj: object) -> None:
    path.write_text(
        json.dumps(_json_safe(obj), indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_relpath(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        return None
    return p.as_posix()


def default_run_directory(root: str | Path, fingerprint: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(root) / f"run_{stamp}_{fingerprint[:10]}"


def _input_identity(completed: CompletedAnalysis, key: str) -> dict[str, object]:
    ds = completed.effective_spec.dataset_a if key == "dataset_a" else completed.effective_spec.dataset_b
    identity = completed.source_identity[key]
    return {
        "logical_path": ds.path,
        "sha256": str(identity["sha256"]),
        "bytes": int(identity["bytes"]),
        "orientation": ds.orientation,
        "data_type": ds.data_type,
        "preprocessing": ds.preprocessing,
        "included_in_bundle": False,
    }


def _provenance(completed: CompletedAnalysis) -> dict[str, object]:
    provenance: dict[str, object] = {
        "schema_version": "1.0",
        "analysis_type": completed.analysis_type,
        "platform": {"name": "biostat-research-tool", "version": PLATFORM_VERSION},
        "module": {"id": completed.module_id, "version": completed.module_version},
        "execution": {
            "requested_analysis_spec_sha256": completed.requested_spec_sha256,
            "effective_analysis_spec_sha256": completed.effective_spec.sha256(),
            "run_fingerprint": completed.run_fingerprint,
            "backend": _json_safe(dict(completed.execution_metadata)),
        },
        "reproducibility": {
            "input_identity": "SHA-256 of original input bytes",
            "absolute_input_paths_recorded": False,
            "raw_input_data_copied_into_bundle": False,
            "report_reruns_analysis": False,
        },
        "statistical_policy": {
            "version": completed.statistical_policy_version,
            "advisories": list(completed.policy_advisories),
        },
    }
    # Module-specific provenance is namespaced by the module and supplied only
    # after validated execution.  Correlation currently contributes the frozen
    # oracle manifest under the historical `oracle` key for RunBundle v1.
    provenance.update(dict(completed.module_provenance))
    return provenance


def _content_inventory(staging: Path, completed: CompletedAnalysis) -> list[dict[str, object]]:
    roles = {
        "analysis.json": ("analysis_spec_effective", "application/json", True),
        "analysis.requested.json": ("analysis_spec_requested", "application/json", True),
        "inspection.json": ("inspection_report", "application/json", True),
        "alignment.json": ("sample_alignment", "application/json", True),
        "provenance.json": ("provenance", "application/json", True),
        "report/report.html": ("human_readable_report", "text/html", True),
        "logs/run.log": ("execution_log", "text/plain", True),
    }
    roles[completed.summary.primary_table_path] = ("primary_result_table", "text/csv", True)
    roles[completed.summary.result_schema_path] = ("result_table_schema", "application/json", True)
    entries: list[dict[str, object]] = []
    for path in sorted(p for p in staging.rglob("*") if p.is_file() and p.name != "manifest.json"):
        rel = path.relative_to(staging).as_posix()
        role, media_type, required = roles.get(rel, ("extension", "application/octet-stream", False))
        entries.append(
            {
                "path": rel,
                "role": role,
                "media_type": media_type,
                "required": required,
                "sha256": _sha256(path),
                "bytes": int(path.stat().st_size),
            }
        )
    return entries


def _manifest(completed: CompletedAnalysis, created_utc: str, content: list[dict[str, object]]) -> dict[str, object]:
    summary = completed.summary
    return {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_type": BUNDLE_TYPE,
        "status": "complete",
        "created_utc": created_utc,
        "analysis_type": completed.analysis_type,
        "platform": {"name": "biostat-research-tool", "version": PLATFORM_VERSION},
        "oracle_engine": {
            "name": completed.engine_identity.name,
            "version": completed.engine_identity.version,
        },
        "analysis": {
            "requested_spec_sha256": completed.requested_spec_sha256,
            "effective_spec_sha256": completed.effective_spec.sha256(),
            "run_fingerprint": completed.run_fingerprint,
        },
        "inputs": {
            "dataset_a": _input_identity(completed, "dataset_a"),
            "dataset_b": _input_identity(completed, "dataset_b"),
        },
        "privacy": {
            "raw_input_data_included": False,
            "absolute_input_paths_recorded": False,
            "input_identity_uses_sha256": True,
        },
        "execution_backend": _json_safe(dict(completed.execution_metadata)),
        "results": {
            "primary_table": summary.primary_table_path,
            "schema": summary.result_schema_path,
            "rows": summary.row_count,
            "testable_rows": summary.testable_rows,
            "method": summary.method,
            "fdr_family": dict(summary.family_metadata),
        },
        "provenance": "provenance.json",
        "content": content,
    }

def write_run_bundle(completed: CompletedAnalysis, destination: str | Path) -> Path:
    """Atomically write and self-verify the standardized v1 RunBundle directory."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"RunBundle destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    created_utc = datetime.now(timezone.utc).isoformat()
    try:
        (staging / "results").mkdir()
        (staging / "report").mkdir()
        (staging / "logs").mkdir()

        (staging / "analysis.json").write_text(completed.effective_spec.canonical_json(), encoding="utf-8")
        (staging / "analysis.requested.json").write_text(completed.requested_spec.canonical_json(), encoding="utf-8")

        _write_json(staging / "inspection.json", completed.inspection_document)
        _write_json(staging / "alignment.json", completed.alignment_document)
        result_path = staging / completed.summary.primary_table_path
        schema_path = staging / completed.summary.result_schema_path
        result_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        completed.primary_results.to_csv(result_path, index=False, lineterminator="\n")
        _write_json(schema_path, completed.result_schema)
        _write_json(staging / "provenance.json", _provenance(completed))
        (staging / "logs" / "run.log").write_text(
            "\n".join(
                [
                    f"bundle_schema_version={BUNDLE_SCHEMA_VERSION}",
                    f"platform_version={PLATFORM_VERSION}",
                    f"analysis_module={completed.module_id}",
                    f"analysis_module_version={completed.module_version}",
                    f"oracle_engine_version={completed.engine_identity.version}",
                    f"requested_backend={completed.execution_metadata.get('requested_backend', '')}",
                    f"actual_backend={completed.execution_metadata.get('actual_backend', '')}",
                    f"requested_spec_sha256={completed.requested_spec_sha256}",
                    f"effective_spec_sha256={completed.effective_spec.sha256()}",
                    f"run_fingerprint={completed.run_fingerprint}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        # Render from scientific outputs without rerunning inference. The provisional
        # manifest contains all top-level metadata needed by the report; content hashes
        # are filled only after report generation.
        _write_json(staging / "manifest.json", _manifest(completed, created_utc, []))
        from .reporting import render_html_report

        render_html_report(staging, verify_bundle=False)
        final_manifest = _manifest(completed, created_utc, _content_inventory(staging, completed))
        _write_json(staging / "manifest.json", final_manifest)

        verify_run_bundle(staging, verify_hashes=True).require_valid()
        os.replace(staging, destination)
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_run_bundle(run_dir: str | Path, *, verify_hashes: bool = True) -> RunBundleVerification:
    """Verify RunBundle v1 structure, inventory, hashes, and core cross-file identities."""
    root = Path(run_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest: dict[str, Any] | None = None
    if not root.is_dir():
        return RunBundleVerification(False, (f"RunBundle directory does not exist: {root}",), (), None)

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return RunBundleVerification(False, ("Missing required manifest.json.",), (), None)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return RunBundleVerification(False, (f"manifest.json is not valid JSON: {exc}",), (), None)
    if not isinstance(raw, dict):
        return RunBundleVerification(False, ("manifest.json must contain a JSON object.",), (), None)
    manifest = raw

    if manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        errors.append(f"Unsupported bundle_schema_version {manifest.get('bundle_schema_version')!r}.")
    if manifest.get("bundle_type") != BUNDLE_TYPE:
        errors.append(f"Unsupported bundle_type {manifest.get('bundle_type')!r}.")
    if manifest.get("status") != "complete":
        errors.append("RunBundle status must be 'complete'.")

    content = manifest.get("content")
    if not isinstance(content, list):
        errors.append("manifest.content must be a list.")
        content = []
    listed: dict[str, dict[str, Any]] = {}
    for idx, entry in enumerate(content):
        if not isinstance(entry, dict):
            errors.append(f"manifest.content[{idx}] must be an object.")
            continue
        rel = _safe_relpath(entry.get("path"))
        if rel is None:
            errors.append(f"manifest.content[{idx}].path is not a safe relative POSIX path.")
            continue
        if rel == "manifest.json":
            errors.append("manifest.json must not list/hash itself in manifest.content.")
            continue
        if rel in listed:
            errors.append(f"Duplicate manifest content path: {rel}")
            continue
        listed[rel] = entry

    disk_files = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() != "manifest.json"
    }
    required_files = set(BASE_REQUIRED_FILES)
    result_meta = manifest.get("results", {}) if isinstance(manifest.get("results"), dict) else {}
    primary_rel = _safe_relpath(result_meta.get("primary_table"))
    schema_rel = _safe_relpath(result_meta.get("schema"))
    if primary_rel is None:
        errors.append("manifest.results.primary_table is not a safe relative POSIX path.")
    else:
        required_files.add(primary_rel)
    if schema_rel is None:
        errors.append("manifest.results.schema is not a safe relative POSIX path.")
    else:
        required_files.add(schema_rel)
    for rel in sorted(required_files - disk_files):
        errors.append(f"Missing required RunBundle file: {rel}")
    for rel in sorted(disk_files - set(listed)):
        errors.append(f"File is present but not inventoried in manifest.content: {rel}")
    for rel in sorted(set(listed) - disk_files):
        errors.append(f"Manifest inventories a missing file: {rel}")

    for rel, entry in listed.items():
        path = root / rel
        if not path.is_file():
            continue
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            errors.append(f"Invalid byte count for {rel}.")
        elif path.stat().st_size != expected_bytes:
            errors.append(f"Byte-count mismatch for {rel}: expected {expected_bytes}, observed {path.stat().st_size}.")
        if verify_hashes:
            expected_hash = entry.get("sha256")
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                errors.append(f"Invalid SHA-256 metadata for {rel}.")
            else:
                observed = _sha256(path)
                if observed.lower() != expected_hash.lower():
                    errors.append(f"SHA-256 mismatch for {rel}.")

    # Cross-file identity checks.
    try:
        effective = json.loads((root / "analysis.json").read_text(encoding="utf-8"))
        requested = json.loads((root / "analysis.requested.json").read_text(encoding="utf-8"))
        effective_text = json.dumps(effective, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        requested_text = json.dumps(requested, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        effective_hash = hashlib.sha256(effective_text.encode("utf-8")).hexdigest()
        requested_hash = hashlib.sha256(requested_text.encode("utf-8")).hexdigest()
        analysis_meta = manifest.get("analysis", {})
        if analysis_meta.get("effective_spec_sha256") != effective_hash:
            errors.append("Effective AnalysisSpec SHA-256 does not match manifest.analysis.effective_spec_sha256.")
        if analysis_meta.get("requested_spec_sha256") != requested_hash:
            errors.append("Requested AnalysisSpec SHA-256 does not match manifest.analysis.requested_spec_sha256.")
        for key in ("dataset_a", "dataset_b"):
            input_spec = effective.get("inputs", {}).get(key, {})
            identity = manifest.get("inputs", {}).get(key, {})
            if input_spec.get("sha256", "").lower() != str(identity.get("sha256", "")).lower():
                errors.append(f"Input identity SHA-256 mismatch for {key} between analysis.json and manifest.json.")
            logical = input_spec.get("path")
            if _safe_relpath(logical) is None:
                errors.append(f"analysis.json contains a non-portable input path for {key}.")
    except Exception as exc:
        errors.append(f"Unable to cross-check AnalysisSpec identities: {exc}")

    try:
        provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        run_fp = manifest.get("analysis", {}).get("run_fingerprint")
        prov_fp = provenance.get("execution", {}).get("run_fingerprint")
        if run_fp != prov_fp:
            errors.append("Run fingerprint differs between manifest.json and provenance.json.")

        manifest_backend = manifest.get("execution_backend")
        provenance_backend = provenance.get("execution", {}).get("backend")
        platform_version = str(manifest.get("platform", {}).get("version", ""))
        try:
            platform_tuple = tuple(int(part) for part in platform_version.split(".")[:3])
        except ValueError:
            platform_tuple = ()
        backend_required = bool(platform_tuple and platform_tuple >= (0, 4, 0))
        if manifest_backend is None and provenance_backend is None and not backend_required:
            pass  # Backward-compatible verification of pre-v0.4 RunBundle v1.
        elif not isinstance(manifest_backend, dict) or not isinstance(provenance_backend, dict):
            errors.append("RunBundle is missing required execution-backend provenance.")
        elif manifest_backend != provenance_backend:
            errors.append("Execution-backend metadata differs between manifest.json and provenance.json.")
        else:
            requested_backend = manifest_backend.get("requested_backend")
            actual_backend = manifest_backend.get("actual_backend")
            if requested_backend not in {"reference", "optimized", "auto"}:
                errors.append("Execution backend requested_backend is invalid.")
            if actual_backend not in {
                "reference_scalar_v0.2.4",
                "optimized_complete_pearson_v0.4.0",
                "optimized_pearson_v0.4.1",
                "optimized_spearman_v0.4.2",
            }:
                errors.append("Execution backend actual_backend is invalid.")
            verification = manifest_backend.get("reference_verification")
            if not isinstance(verification, dict) or not isinstance(verification.get("status"), str):
                errors.append("Execution backend reference_verification metadata is invalid.")

        # RunBundle v1 currently contains the correlation module's frozen-oracle
        # manifest.  Use it as the executed-run semantic authority, not merely
        # as another hashed file.  This detects internally self-consistent hashes
        # around inspection/alignment metadata that do not describe the data that
        # actually reached inference.
        oracle = provenance.get("oracle")
        if not isinstance(oracle, dict):
            errors.append("provenance.json is missing required executed frozen-oracle metadata.")
            oracle_manifest = None
        else:
            oracle_manifest = oracle.get("manifest")
            if not isinstance(oracle_manifest, dict):
                errors.append("provenance.json oracle.manifest must contain the executed frozen-oracle manifest.")
                oracle_manifest = None

        if isinstance(oracle_manifest, dict):
            oracle_fp = oracle_manifest.get("run_fingerprint")
            if oracle_fp != run_fp:
                errors.append("Frozen-oracle run fingerprint differs from manifest.json.")

            inspection = json.loads((root / "inspection.json").read_text(encoding="utf-8"))
            if inspection.get("run_fingerprint") != oracle_fp:
                errors.append("inspection.json run_fingerprint does not match the executed frozen-oracle run.")
            if inspection.get("metrics") != oracle_manifest.get("inspection_metrics"):
                errors.append("inspection.json metrics do not match the executed frozen-oracle inspection.")
            if inspection.get("issues") != oracle_manifest.get("issues"):
                errors.append("inspection.json issues do not match the executed frozen-oracle inspection.")
            expected_blocked = any(
                isinstance(issue, dict) and issue.get("severity") == "BLOCKED"
                for issue in oracle_manifest.get("issues", [])
            )
            if inspection.get("blocked") is not expected_blocked:
                errors.append("inspection.json blocked status does not match the executed frozen-oracle inspection.")

            alignment = json.loads((root / "alignment.json").read_text(encoding="utf-8"))
            alignment_payload = {k: v for k, v in alignment.items() if k != "schema_version"}
            if alignment_payload != oracle_manifest.get("alignment"):
                errors.append("alignment.json does not match the executed frozen-oracle alignment.")

            source_hashes = oracle_manifest.get("source_hashes")
            if isinstance(source_hashes, dict):
                for key in ("dataset_a", "dataset_b"):
                    manifest_hash = manifest.get("inputs", {}).get(key, {}).get("sha256")
                    oracle_hash = source_hashes.get(f"{key}_sha256")
                    if str(oracle_hash or "").lower() != str(manifest_hash or "").lower():
                        errors.append(f"Executed frozen-oracle source hash differs from manifest input identity for {key}.")

            oracle_family = oracle_manifest.get("fdr_family")
            manifest_family = manifest.get("results", {}).get("fdr_family")
            if oracle_family != manifest_family:
                errors.append("manifest.results.fdr_family does not match the executed frozen-oracle family metadata.")
    except Exception as exc:
        errors.append(f"Unable to validate provenance.json and executed-run metadata: {exc}")

    try:
        result_meta = manifest.get("results", {})
        primary_rel = _safe_relpath(result_meta.get("primary_table"))
        schema_rel = _safe_relpath(result_meta.get("schema"))
        if primary_rel is None or schema_rel is None:
            raise ValueError("manifest result paths are invalid")
        result_schema = json.loads((root / schema_rel).read_text(encoding="utf-8"))
        dtype_map = {
            c.get("name"): "string"
            for c in result_schema.get("columns", [])
            if isinstance(c, dict) and c.get("storage_type") == "string" and isinstance(c.get("name"), str)
        }
        results = pd.read_csv(root / primary_rel, dtype=dtype_map, keep_default_na=False)
        if int(result_schema.get("row_count", -1)) != len(results):
            errors.append(f"{schema_rel} row_count does not match {primary_rel}.")
        if int(result_meta.get("rows", -1)) != len(results):
            errors.append(f"manifest.results.rows does not match {primary_rel}.")
        schema_names = [x.get("name") for x in result_schema.get("columns", []) if isinstance(x, dict)]
        if schema_names != list(results.columns):
            errors.append(f"{schema_rel} column order does not match {primary_rel}.")
    except Exception as exc:
        errors.append(f"Unable to validate primary result table/schema: {exc}")

    privacy = manifest.get("privacy", {})
    if privacy.get("raw_input_data_included") is not False:
        warnings.append("Bundle does not declare raw_input_data_included=false.")
    if privacy.get("absolute_input_paths_recorded") is not False:
        warnings.append("Bundle does not declare absolute_input_paths_recorded=false.")

    return RunBundleVerification(not errors, tuple(errors), tuple(warnings), manifest)


def zip_run_bundle(run_dir: str | Path, output_path: str | Path | None = None) -> Path:
    run_dir = Path(run_dir).resolve()
    verify_run_bundle(run_dir, verify_hashes=True).require_valid()
    output = Path(output_path).resolve() if output_path is not None else run_dir.with_suffix(".zip")
    if output.exists():
        raise FileExistsError(output)
    tmp = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
                zf.write(path, arcname=f"{run_dir.name}/{path.relative_to(run_dir).as_posix()}")
        os.replace(tmp, output)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return output
