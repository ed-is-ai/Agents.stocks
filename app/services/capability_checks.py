"""Builds pipeline capability warnings from the shared integration config.

Both the refresh preflight (#45) and the Settings UI (#47) read
configured/missing state from ``IntegrationConfigService`` — this module is
the one place that maps that state onto the pipeline capabilities it
affects, so the two surfaces cannot report conflicting answers.
"""

from __future__ import annotations

import hashlib

from app.schemas.capability_warning import (
    CapabilityCategory,
    CapabilitySeverity,
    CapabilityWarning,
    severity_sort_key,
)
from app.services.integration_config_service import IntegrationConfigService

# Ordered by severity by construction; `missing_capability_warnings` re-sorts
# defensively so callers never depend on this list's literal order.
_CAPABILITIES: tuple[CapabilityWarning, ...] = (
    CapabilityWarning(
        capability_id="fmp_vcp_screener",
        category=CapabilityCategory.ANALYTICAL_COVERAGE,
        severity=CapabilitySeverity.CRITICAL,
        title="FMP API key",
        impact="The S&P 500 VCP screener will be skipped, reducing analytical coverage.",
        required_env_keys=("FMP_API_KEY",),
    ),
    CapabilityWarning(
        capability_id="alpha_vantage_enrichment",
        category=CapabilityCategory.ENRICHMENT,
        severity=CapabilitySeverity.MODERATE,
        title="Alpha Vantage API key",
        impact="Missing Yahoo fundamental fields will not be backfilled.",
        required_env_keys=("ALPHA_VANTAGE_API_KEY",),
    ),
    CapabilityWarning(
        capability_id="email_alerts",
        category=CapabilityCategory.NOTIFICATION,
        severity=CapabilitySeverity.LOW,
        title="Email alert settings",
        impact="Summary emails and alert delivery are disabled.",
        required_env_keys=("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO"),
    ),
)


def missing_capability_warnings(
    config: IntegrationConfigService,
) -> list[CapabilityWarning]:
    """Return warnings for capabilities with at least one unconfigured key.

    Ordered severity-first (analytical coverage, then enrichment, then
    notification/security) so the dialog leads with what matters most.
    """
    status = config.status()
    missing = [
        capability
        for capability in _CAPABILITIES
        if not all(
            status.get(key, {}).get("configured")
            for key in capability.required_env_keys
        )
    ]
    return sorted(
        missing, key=lambda capability: severity_sort_key(capability.severity)
    )


def warnings_fingerprint(warnings: list[CapabilityWarning]) -> str:
    """Return a stable fingerprint of which capabilities are missing.

    A confirmation the client posts back is only honored if this matches
    the fingerprint computed fresh from server-side state at confirmation
    time — the client cannot carry a stale or forged snapshot past a
    capability change (#45's fingerprint-validation requirement). This is a
    consistency check, not a secret: the algorithm and inputs are
    unauthenticated and safe to be fully known to the client.
    """
    ids = sorted(warning.capability_id for warning in warnings)
    return hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()
