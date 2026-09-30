from __future__ import annotations

from dataclasses import dataclass

from .specs import AnalysisSpec

STATISTICAL_POLICY_VERSION = "1.0"
RECOMMENDED_CORRELATION_MIN_PAIRWISE_N = 10


@dataclass(frozen=True)
class PolicyAdvisory:
    code: str
    level: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "level": self.level, "message": self.message}


def correlation_policy_advisories(spec: AnalysisSpec) -> tuple[PolicyAdvisory, ...]:
    """Return non-gating platform policy advisories for correlation.

    These advisories do not modify the frozen oracle or its warning-
    acknowledgement fingerprint.  They communicate interpretation/default
    policy at the platform layer and are recorded in provenance.
    """

    advisories: list[PolicyAdvisory] = [
        PolicyAdvisory(
            code="unadjusted_marginal_association",
            level="INFO",
            message=(
                "Correlation results are unadjusted marginal associations. They may reflect measured or unmeasured "
                "covariates, group structure, batch effects, medication, demographic factors, or other common causes; "
                "they do not establish an independent molecular relationship or causation."
            ),
        )
    ]
    if spec.correlation.minimum_pairwise_n < RECOMMENDED_CORRELATION_MIN_PAIRWISE_N:
        advisories.append(
            PolicyAdvisory(
                code="minimum_pairwise_n_below_platform_recommended_default",
                level="CAUTION",
                message=(
                    f"minimum_pairwise_n={spec.correlation.minimum_pairwise_n} is below the platform's recommended "
                    f"starting default of {RECOMMENDED_CORRELATION_MIN_PAIRWISE_N}. The hard minimum of 3 is retained "
                    "for reproducibility and explicit advanced use; neither threshold is a universal sample-size or power requirement."
                ),
            )
        )
    return tuple(advisories)
