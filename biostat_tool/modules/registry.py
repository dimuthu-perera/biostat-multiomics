from __future__ import annotations

from .base import AnalysisModule
from .correlation import CORRELATION_MODULE

_MODULES: dict[str, AnalysisModule] = {
    CORRELATION_MODULE.analysis_type: CORRELATION_MODULE,
}


def get_analysis_module(analysis_type: str) -> AnalysisModule:
    try:
        return _MODULES[analysis_type]
    except KeyError as exc:
        supported = ", ".join(sorted(_MODULES))
        raise ValueError(f"Unsupported analysis type {analysis_type!r}. Registered types: {supported}.") from exc


def registered_analysis_types() -> tuple[str, ...]:
    return tuple(sorted(_MODULES))
