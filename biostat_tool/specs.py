from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"
ANALYSIS_TYPE = "cross_omics_correlation"
MULTIPLE_TESTING_METHOD = "benjamini_hochberg"
MULTIPLE_TESTING_FAMILY = "all_eligible_cross_dataset_pairs"
DEFAULT_MISSING_TOKENS = ("", "NA", "N/A", "NaN", "nan")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SpecError(ValueError):
    """Raised when an AnalysisSpec is malformed or unsupported."""


def _expect_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(f"{name} must be an object/mapping.")
    return value


def _check_keys(mapping: Mapping[str, Any], allowed: set[str], required: set[str], name: str) -> None:
    unknown = set(mapping) - allowed
    missing = required - set(mapping)
    if unknown:
        raise SpecError(f"{name} contains unknown field(s): {', '.join(sorted(unknown))}.")
    if missing:
        raise SpecError(f"{name} is missing required field(s): {', '.join(sorted(missing))}.")


def _require_nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{name} must be a non-empty string.")
    return value




def _require_portable_relative_path(value: object, name: str) -> str:
    text = _require_nonempty_string(value, name)
    if "\\" in text:
        raise SpecError(f"{name} must use a portable relative POSIX path; backslashes are not allowed.")
    # Reject Windows drive/UNC forms even when validation runs on POSIX.
    if re.match(r"^[A-Za-z]:", text) or text.startswith("//"):
        raise SpecError(f"{name} must be a portable relative path, not an absolute machine path.")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SpecError(f"{name} must be a portable relative path without '.' or '..' segments.")
    return path.as_posix()

def _optional_string(value: object, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SpecError(f"{name} must be a string.")
    return value


@dataclass(frozen=True)
class DatasetSpec:
    path: str
    sha256: str
    orientation: str
    data_type: str
    preprocessing: str
    preprocessing_details: str = ""
    missing_tokens: tuple[str, ...] = DEFAULT_MISSING_TOKENS

    def __post_init__(self) -> None:
        _require_portable_relative_path(self.path, "dataset.path")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise SpecError("dataset.sha256 must be a 64-character hexadecimal SHA-256 digest.")
        if self.orientation not in {"samples_rows", "samples_columns"}:
            raise SpecError("dataset.orientation must be 'samples_rows' or 'samples_columns'.")
        _require_nonempty_string(self.data_type, "dataset.data_type")
        _require_nonempty_string(self.preprocessing, "dataset.preprocessing")
        if not isinstance(self.preprocessing_details, str):
            raise SpecError("dataset.preprocessing_details must be a string.")
        if not isinstance(self.missing_tokens, tuple) or not all(isinstance(x, str) for x in self.missing_tokens):
            raise SpecError("dataset.missing_tokens must be a tuple/list of strings.")
        if len(set(self.missing_tokens)) != len(self.missing_tokens):
            raise SpecError("dataset.missing_tokens must not contain duplicates.")


@dataclass(frozen=True)
class StudyDesignSpec:
    observation_structure: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.observation_structure not in {"unknown", "independent", "dependent_or_clustered"}:
            raise SpecError("study_design.observation_structure is unsupported.")
        if not isinstance(self.notes, str):
            raise SpecError("study_design.notes must be a string.")


@dataclass(frozen=True)
class CorrelationSpec:
    minimum_pairwise_n: int = 3
    spearman_permutations: int = 9_999
    random_seed: int = 20_260_915

    def __post_init__(self) -> None:
        for name in ("minimum_pairwise_n", "spearman_permutations", "random_seed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise SpecError(f"correlation.{name} must be an integer.")
        if self.minimum_pairwise_n < 3:
            raise SpecError("correlation.minimum_pairwise_n must be >= 3.")
        if not 99 <= self.spearman_permutations <= 100_000:
            raise SpecError("correlation.spearman_permutations must be between 99 and 100,000.")
        if self.random_seed < 0:
            raise SpecError("correlation.random_seed must be >= 0.")


@dataclass(frozen=True)
class ReviewSpec:
    inspected_run_fingerprint: str = ""
    acknowledged_warning_issue_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.inspected_run_fingerprint, str):
            raise SpecError("review.inspected_run_fingerprint must be a string.")
        if self.inspected_run_fingerprint and not _SHA256_RE.fullmatch(self.inspected_run_fingerprint):
            raise SpecError("review.inspected_run_fingerprint must be a SHA-256 digest when present.")
        if not isinstance(self.acknowledged_warning_issue_ids, tuple) or not all(
            isinstance(x, str) and x for x in self.acknowledged_warning_issue_ids
        ):
            raise SpecError("review.acknowledged_warning_issue_ids must contain non-empty strings.")
        if len(set(self.acknowledged_warning_issue_ids)) != len(self.acknowledged_warning_issue_ids):
            raise SpecError("review.acknowledged_warning_issue_ids must not contain duplicates.")
        if self.acknowledged_warning_issue_ids and not self.inspected_run_fingerprint:
            raise SpecError("review warning acknowledgements require inspected_run_fingerprint.")


@dataclass(frozen=True)
class OutputSpec:
    root: str = "runs"

    def __post_init__(self) -> None:
        _require_portable_relative_path(self.root, "outputs.root")


@dataclass(frozen=True)
class AnalysisSpec:
    schema_version: str
    method: str
    dataset_a: DatasetSpec
    dataset_b: DatasetSpec
    study_design: StudyDesignSpec
    correlation: CorrelationSpec = field(default_factory=CorrelationSpec)
    review: ReviewSpec = field(default_factory=ReviewSpec)
    outputs: OutputSpec = field(default_factory=OutputSpec)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SpecError(f"Unsupported schema_version {self.schema_version!r}; supported version is {SCHEMA_VERSION!r}.")
        if self.method not in {"pearson", "spearman"}:
            raise SpecError("analysis.method must be 'pearson' or 'spearman'.")

    @property
    def analysis_type(self) -> str:
        """Stable dispatch key consumed by the AnalysisModule registry."""
        return ANALYSIS_TYPE

    def to_dict(self) -> dict[str, Any]:
        def dataset_dict(d: DatasetSpec) -> dict[str, Any]:
            return {
                "path": d.path,
                "sha256": d.sha256.lower(),
                "orientation": d.orientation,
                "data_type": d.data_type,
                "preprocessing": d.preprocessing,
                "preprocessing_details": d.preprocessing_details,
                "missing_tokens": list(d.missing_tokens),
            }

        return {
            "schema_version": self.schema_version,
            "analysis": {"type": ANALYSIS_TYPE, "method": self.method},
            "inputs": {"dataset_a": dataset_dict(self.dataset_a), "dataset_b": dataset_dict(self.dataset_b)},
            "study_design": asdict(self.study_design),
            "correlation": asdict(self.correlation),
            "multiple_testing": {
                "method": MULTIPLE_TESTING_METHOD,
                "family": MULTIPLE_TESTING_FAMILY,
            },
            "review": {
                "inspected_run_fingerprint": self.review.inspected_run_fingerprint,
                "acknowledged_warning_issue_ids": list(self.review.acknowledged_warning_issue_ids),
            },
            "outputs": asdict(self.outputs),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def with_review(self, fingerprint: str, warning_issue_ids: Sequence[str]) -> "AnalysisSpec":
        review = ReviewSpec(
            inspected_run_fingerprint=fingerprint,
            acknowledged_warning_issue_ids=tuple(sorted(set(warning_issue_ids))),
        )
        return replace(self, review=review)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AnalysisSpec":
        raw = _expect_mapping(raw, "spec")
        _check_keys(
            raw,
            {"schema_version", "analysis", "inputs", "study_design", "correlation", "multiple_testing", "review", "outputs"},
            {"schema_version", "analysis", "inputs", "study_design", "correlation", "multiple_testing"},
            "spec",
        )
        schema_version = _require_nonempty_string(raw["schema_version"], "schema_version")

        analysis = _expect_mapping(raw["analysis"], "analysis")
        _check_keys(analysis, {"type", "method"}, {"type", "method"}, "analysis")
        if analysis["type"] != ANALYSIS_TYPE:
            raise SpecError(f"Unsupported analysis.type {analysis['type']!r}.")
        method = _require_nonempty_string(analysis["method"], "analysis.method")

        inputs = _expect_mapping(raw["inputs"], "inputs")
        _check_keys(inputs, {"dataset_a", "dataset_b"}, {"dataset_a", "dataset_b"}, "inputs")

        def parse_dataset(value: object, name: str) -> DatasetSpec:
            d = _expect_mapping(value, name)
            _check_keys(
                d,
                {"path", "sha256", "orientation", "data_type", "preprocessing", "preprocessing_details", "missing_tokens"},
                {"path", "sha256", "orientation", "data_type", "preprocessing"},
                name,
            )
            tokens = d.get("missing_tokens", list(DEFAULT_MISSING_TOKENS))
            if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes)):
                raise SpecError(f"{name}.missing_tokens must be a list of strings.")
            return DatasetSpec(
                path=_require_portable_relative_path(d["path"], f"{name}.path"),
                sha256=_require_nonempty_string(d["sha256"], f"{name}.sha256"),
                orientation=_require_nonempty_string(d["orientation"], f"{name}.orientation"),
                data_type=_require_nonempty_string(d["data_type"], f"{name}.data_type"),
                preprocessing=_require_nonempty_string(d["preprocessing"], f"{name}.preprocessing"),
                preprocessing_details=_optional_string(d.get("preprocessing_details", ""), f"{name}.preprocessing_details"),
                missing_tokens=tuple(tokens),
            )

        dataset_a = parse_dataset(inputs["dataset_a"], "inputs.dataset_a")
        dataset_b = parse_dataset(inputs["dataset_b"], "inputs.dataset_b")

        sd = _expect_mapping(raw["study_design"], "study_design")
        _check_keys(sd, {"observation_structure", "notes"}, {"observation_structure"}, "study_design")
        study_design = StudyDesignSpec(
            observation_structure=_require_nonempty_string(sd["observation_structure"], "study_design.observation_structure"),
            notes=_optional_string(sd.get("notes", ""), "study_design.notes"),
        )

        corr = _expect_mapping(raw["correlation"], "correlation")
        _check_keys(corr, {"minimum_pairwise_n", "spearman_permutations", "random_seed"}, set(), "correlation")
        correlation = CorrelationSpec(
            minimum_pairwise_n=corr.get("minimum_pairwise_n", 3),
            spearman_permutations=corr.get("spearman_permutations", 9_999),
            random_seed=corr.get("random_seed", 20_260_915),
        )

        mt = _expect_mapping(raw["multiple_testing"], "multiple_testing")
        _check_keys(mt, {"method", "family"}, {"method", "family"}, "multiple_testing")
        if mt["method"] != MULTIPLE_TESTING_METHOD or mt["family"] != MULTIPLE_TESTING_FAMILY:
            raise SpecError(
                "AnalysisSpec v1 supports only Benjamini-Hochberg across the full eligible cross-dataset pair family."
            )

        review_raw = _expect_mapping(raw.get("review", {}), "review")
        _check_keys(review_raw, {"inspected_run_fingerprint", "acknowledged_warning_issue_ids"}, set(), "review")
        issue_ids = review_raw.get("acknowledged_warning_issue_ids", [])
        if not isinstance(issue_ids, Sequence) or isinstance(issue_ids, (str, bytes)):
            raise SpecError("review.acknowledged_warning_issue_ids must be a list of strings.")
        review = ReviewSpec(
            inspected_run_fingerprint=review_raw.get("inspected_run_fingerprint", ""),
            acknowledged_warning_issue_ids=tuple(issue_ids),
        )

        out_raw = _expect_mapping(raw.get("outputs", {}), "outputs")
        _check_keys(out_raw, {"root"}, set(), "outputs")
        outputs = OutputSpec(root=out_raw.get("root", "runs"))

        return cls(
            schema_version=schema_version,
            method=method,
            dataset_a=dataset_a,
            dataset_b=dataset_b,
            study_design=study_design,
            correlation=correlation,
            review=review,
            outputs=outputs,
        )



def _unique_json_object(pairs: list[tuple[object, object]]) -> dict[object, object]:
    out: dict[object, object] = {}
    for key, value in pairs:
        if key in out:
            raise SpecError(f"Duplicate specification field {key!r} is not allowed.")
        out[key] = value
    return out


def _load_yaml_unique(text: str, yaml_module) -> object:
    class UniqueKeyLoader(yaml_module.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        pairs = loader.construct_pairs(node, deep=deep)
        out = {}
        for key, value in pairs:
            if key in out:
                raise SpecError(f"Duplicate specification field {key!r} is not allowed.")
            out[key] = value
        return out

    UniqueKeyLoader.add_constructor(
        yaml_module.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    return yaml_module.load(text, Loader=UniqueKeyLoader)

def load_analysis_spec(path: str | Path) -> AnalysisSpec:
    path = Path(path)
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        try:
            raw = json.loads(text, object_pairs_hook=_unique_json_object)
        except SpecError:
            raise
        except json.JSONDecodeError as exc:
            raise SpecError(f"Invalid JSON analysis specification: {exc}") from exc
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SpecError("YAML support is optional. Install the 'yaml' extra or use canonical JSON.") from exc
        try:
            raw = _load_yaml_unique(text, yaml)
        except SpecError:
            raise
        except Exception as exc:
            raise SpecError(f"Invalid YAML analysis specification: {exc}") from exc
    else:
        raise SpecError("Analysis specifications must use .json, .yaml, or .yml.")
    return AnalysisSpec.from_dict(_expect_mapping(raw, "spec"))


def save_analysis_spec(spec: AnalysisSpec, path: str | Path) -> None:
    path = Path(path)
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        path.write_text(spec.canonical_json(), encoding="utf-8")
        return
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SpecError("YAML support is optional. Install the 'yaml' extra or save canonical JSON.") from exc
        path.write_text(yaml.safe_dump(spec.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return
    raise SpecError("Analysis specifications must use .json, .yaml, or .yml.")
