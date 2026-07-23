"""Typed capability warnings for the pipeline preflight/confirmation flow.

Replaces the untyped ``{"name": ..., "impact": ...}`` dicts previously
returned by ``PipelineService.missing_configuration()`` (#45). Warnings are
derived from ``IntegrationConfigService`` — the same source of truth the
Settings UI (#47) uses — so "configured" can never drift between the two.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class CapabilityCategory(StrEnum):
    """What kind of pipeline behavior a missing capability affects."""

    ANALYTICAL_COVERAGE = "analytical_coverage"
    ENRICHMENT = "enrichment"
    NOTIFICATION = "notification"
    SECURITY = "security"

    @property
    def label(self) -> str:
        """Return the human-readable display name for this category."""
        return {
            self.ANALYTICAL_COVERAGE: "Analytical coverage",
            self.ENRICHMENT: "Enrichment",
            self.NOTIFICATION: "Notification",
            self.SECURITY: "Security",
        }[self]


class CapabilitySeverity(StrEnum):
    """How much a missing capability should weigh on the user's decision."""

    CRITICAL = "critical"
    MODERATE = "moderate"
    LOW = "low"


# Dialog ordering (#45): missing analytical coverage first, then enrichment,
# then notification/security last.
_SEVERITY_ORDER: dict[CapabilitySeverity, int] = {
    CapabilitySeverity.CRITICAL: 0,
    CapabilitySeverity.MODERATE: 1,
    CapabilitySeverity.LOW: 2,
}


def severity_sort_key(severity: CapabilitySeverity) -> int:
    """Return the sort key used to order warnings most-severe first."""
    return _SEVERITY_ORDER[severity]


class CapabilityWarning(BaseModel):
    """A single missing/degraded pipeline capability, safe to display."""

    capability_id: str
    category: CapabilityCategory
    severity: CapabilitySeverity
    title: str
    impact: str
    required_env_keys: tuple[str, ...]
    setup_target: str = "/partials/settings"
