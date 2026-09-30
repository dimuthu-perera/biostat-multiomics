from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .modules.base import CompletedAnalysis, ExecutionOptions, PreparedAnalysis
from .modules.registry import get_analysis_module
from .specs import AnalysisSpec

PlatformCompletedRun = CompletedAnalysis


def prepare_analysis(
    spec: AnalysisSpec,
    *,
    base_dir: str | Path | None = None,
    path_overrides: Mapping[str, str | Path] | None = None,
) -> PreparedAnalysis:
    """Dispatch mandatory inspection to the AnalysisModule named by the spec."""
    module = get_analysis_module(spec.analysis_type)
    module.validate_spec(spec)
    return module.inspect(spec, base_dir=base_dir, path_overrides=path_overrides)


def execute_prepared(
    prepared: PreparedAnalysis,
    *,
    acknowledge_warnings: bool = False,
    backend: str = "reference",
    verify_against_reference: bool = False,
) -> CompletedAnalysis:
    """Execute through exactly the module that inspected the request.

    Backend selection is runtime-only.  It is deliberately outside AnalysisSpec
    because execution strategy must not change the requested scientific method.
    """
    module = get_analysis_module(prepared.analysis_type)
    if prepared.module_id != module.module_id or prepared.module_version != module.module_version:
        raise RuntimeError(
            "Prepared analysis module identity does not match the active registered module; inspect again before execution."
        )
    execution = ExecutionOptions(backend=backend, verify_against_reference=verify_against_reference)
    return module.run(prepared, acknowledge_warnings=acknowledge_warnings, execution=execution)
