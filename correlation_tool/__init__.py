"""Conservative, inspection-gated cross-omics correlation analysis."""

from .analysis import CorrelationConfig, benjamini_hochberg
from .inspection import DatasetDeclaration, InspectionReport, StudyDesignDeclaration, inspect_dataset
from .io import MatrixFormatError, align_samples, load_matrix, sha256_file
from .workflow import (
    AcknowledgementRequired,
    CompletedRun,
    InspectedRun,
    RunAcknowledgement,
    NoTestablePairsError,
    ValidationError,
    analyze_validated_run,
    create_acknowledgement,
    inspect_run,
)

__all__ = [
    "CorrelationConfig",
    "DatasetDeclaration",
    "StudyDesignDeclaration",
    "InspectionReport",
    "MatrixFormatError",
    "load_matrix",
    "sha256_file",
    "align_samples",
    "inspect_dataset",
    "inspect_run",
    "analyze_validated_run",
    "InspectedRun",
    "CompletedRun",
    "RunAcknowledgement",
    "create_acknowledgement",
    "ValidationError",
    "AcknowledgementRequired",
    "NoTestablePairsError",
    "benjamini_hochberg",
]

__version__ = "0.2.4"
