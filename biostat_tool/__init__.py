"""Local-first biostatistics research platform.

The platform wraps the frozen v0.2.4 correlation oracle through a
versioned analysis specification and a shared runner used by the CLI and web UI.
"""

__version__ = "1.0.0"

from .specs import AnalysisSpec, SpecError, load_analysis_spec, save_analysis_spec
from .runner import PreparedAnalysis, PlatformCompletedRun, prepare_analysis, execute_prepared
from .modules import AnalysisModule, AnalysisSummary, CompletedAnalysis, EngineIdentity, ExecutionOptions, get_analysis_module, registered_analysis_types
from .bundle import RunBundleVerification, verify_run_bundle, write_run_bundle

__all__ = [
    "AnalysisSpec",
    "SpecError",
    "load_analysis_spec",
    "save_analysis_spec",
    "PreparedAnalysis",
    "PlatformCompletedRun",
    "prepare_analysis",
    "execute_prepared",
    "RunBundleVerification",
    "verify_run_bundle",
    "write_run_bundle",
    "AnalysisModule",
    "AnalysisSummary",
    "CompletedAnalysis",
    "EngineIdentity",
    "ExecutionOptions",
    "get_analysis_module",
    "registered_analysis_types",
]
