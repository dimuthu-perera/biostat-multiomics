from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from ..specs import AnalysisSpec


EXECUTION_BACKENDS = frozenset({"reference", "optimized", "auto"})


@dataclass(frozen=True)
class ExecutionOptions:
    """Runtime-only execution controls; these do not alter the scientific AnalysisSpec."""

    backend: str = "reference"
    verify_against_reference: bool = False

    def __post_init__(self) -> None:
        if self.backend not in EXECUTION_BACKENDS:
            raise ValueError(
                f"Unsupported execution backend {self.backend!r}; choose one of {sorted(EXECUTION_BACKENDS)}."
            )
        if not isinstance(self.verify_against_reference, bool):
            raise ValueError("verify_against_reference must be Boolean.")


@dataclass(frozen=True)
class EngineIdentity:
    """Identity of the validated statistical contract/oracle for one module."""

    name: str
    version: str


@dataclass(frozen=True)
class AnalysisSummary:
    """Standardized summary consumed by RunBundle/reporting infrastructure."""

    primary_table_id: str
    primary_table_path: str
    result_schema_path: str
    row_count: int
    testable_rows: int
    method: str
    family_metadata: Mapping[str, object]
    interpretation: Mapping[str, object]


@dataclass(frozen=True)
class PreparedAnalysis:
    """Module-independent representation of an inspected, not-yet-executed run."""

    analysis_type: str
    module_id: str
    module_version: str
    spec: AnalysisSpec
    module_state: object
    resolved_paths: dict[str, Path]
    requested_spec_sha256: str
    source_identity: dict[str, dict[str, object]]
    run_fingerprint: str
    blocked: bool
    warning_issue_ids: tuple[str, ...]
    inspection_document: Mapping[str, object]
    alignment_document: Mapping[str, object]
    statistical_policy_version: str
    policy_advisories: tuple[Mapping[str, str], ...]

    @property
    def inspected(self) -> object:
        """Compatibility alias for the accepted v0.3 correlation UI/CLI surface."""
        return self.module_state


@dataclass(frozen=True)
class CompletedAnalysis:
    """Module-independent completed analysis returned by the central runner."""

    analysis_type: str
    module_id: str
    module_version: str
    engine_identity: EngineIdentity
    requested_spec: AnalysisSpec
    effective_spec: AnalysisSpec
    module_result: object
    primary_results: pd.DataFrame
    result_schema: Mapping[str, object]
    summary: AnalysisSummary
    inspection_document: Mapping[str, object]
    alignment_document: Mapping[str, object]
    statistical_policy_version: str
    policy_advisories: tuple[Mapping[str, str], ...]
    module_provenance: Mapping[str, object]
    execution_metadata: Mapping[str, object]
    resolved_paths: dict[str, Path]
    requested_spec_sha256: str
    source_identity: dict[str, dict[str, object]]
    run_fingerprint: str

    @property
    def oracle_run(self) -> object:
        """Compatibility alias for the correlation module result object."""
        return self.module_result


class AnalysisModule(ABC):
    """Contract implemented by every statistical analysis module."""

    analysis_type: str
    module_id: str
    module_version: str

    @abstractmethod
    def validate_spec(self, spec: AnalysisSpec) -> None:
        """Validate module-specific semantics without executing inference."""

    @abstractmethod
    def inspect(
        self,
        spec: AnalysisSpec,
        *,
        base_dir: str | Path | None = None,
        path_overrides: Mapping[str, str | Path] | None = None,
    ) -> PreparedAnalysis:
        """Resolve/import exact inputs and perform mandatory pre-inference inspection."""

    @abstractmethod
    def run(
        self,
        prepared: PreparedAnalysis,
        *,
        acknowledge_warnings: bool = False,
        execution: ExecutionOptions | None = None,
    ) -> CompletedAnalysis:
        """Execute only a PreparedAnalysis produced by this module."""

    @abstractmethod
    def summarize(self, module_result: object, effective_spec: AnalysisSpec) -> AnalysisSummary:
        """Return standardized result metadata without rerunning inference."""

    @abstractmethod
    def result_schema(self, module_result: object) -> Mapping[str, object]:
        """Describe the primary result table in a machine-readable form."""
