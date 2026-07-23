"""Unit tests for capability_checks (#45)."""

from __future__ import annotations

from app.schemas.capability_warning import CapabilityCategory, CapabilitySeverity
from app.services.capability_checks import (
    missing_capability_warnings,
    warnings_fingerprint,
)
from app.services.integration_config_service import (
    ALLOWED_KEYS,
    IntegrationConfigService,
)


def _fresh_service(tmp_path) -> IntegrationConfigService:
    import os

    for key in ALLOWED_KEYS:
        os.environ.pop(key, None)
    return IntegrationConfigService(tmp_path / ".env")


def test_all_capabilities_missing_are_ordered_by_severity(tmp_path) -> None:
    warnings = missing_capability_warnings(_fresh_service(tmp_path))

    assert [w.capability_id for w in warnings] == [
        "fmp_vcp_screener",
        "alpha_vantage_enrichment",
        "email_alerts",
    ]
    assert [w.severity for w in warnings] == [
        CapabilitySeverity.CRITICAL,
        CapabilitySeverity.MODERATE,
        CapabilitySeverity.LOW,
    ]
    assert warnings[0].category is CapabilityCategory.ANALYTICAL_COVERAGE
    assert warnings[1].category is CapabilityCategory.ENRICHMENT
    assert warnings[2].category is CapabilityCategory.NOTIFICATION


def test_configuring_one_capability_removes_only_its_warning(tmp_path) -> None:
    service = _fresh_service(tmp_path)
    service.update({"FMP_API_KEY": "sk-123"})

    warnings = missing_capability_warnings(service)

    assert "fmp_vcp_screener" not in [w.capability_id for w in warnings]
    assert "alpha_vantage_enrichment" in [w.capability_id for w in warnings]


def test_email_capability_requires_all_three_keys(tmp_path) -> None:
    service = _fresh_service(tmp_path)
    service.update({"EMAIL_USER": "user@example.com", "EMAIL_PASSWORD": "pw"})

    warnings = missing_capability_warnings(service)

    assert "email_alerts" in [w.capability_id for w in warnings]


def test_fully_configured_service_has_no_warnings(tmp_path) -> None:
    service = _fresh_service(tmp_path)
    service.update(
        {
            "FMP_API_KEY": "sk-123",
            "ALPHA_VANTAGE_API_KEY": "av-123",
            "EMAIL_USER": "user@example.com",
            "EMAIL_PASSWORD": "pw",
            "EMAIL_TO": "alerts@example.com",
        }
    )

    assert missing_capability_warnings(service) == []


def test_fingerprint_is_stable_for_the_same_missing_set(tmp_path) -> None:
    service = _fresh_service(tmp_path)
    service.update({"FMP_API_KEY": "sk-123"})

    warnings_a = missing_capability_warnings(service)
    warnings_b = missing_capability_warnings(service)

    assert warnings_fingerprint(warnings_a) == warnings_fingerprint(warnings_b)


def test_fingerprint_changes_when_missing_set_changes(tmp_path) -> None:
    service = _fresh_service(tmp_path)
    before = warnings_fingerprint(missing_capability_warnings(service))

    service.update({"FMP_API_KEY": "sk-123"})
    after = warnings_fingerprint(missing_capability_warnings(service))

    assert before != after


def test_fingerprint_is_order_independent() -> None:
    from app.schemas.capability_warning import CapabilityWarning

    a = CapabilityWarning(
        capability_id="a",
        category=CapabilityCategory.ANALYTICAL_COVERAGE,
        severity=CapabilitySeverity.CRITICAL,
        title="A",
        impact="impact",
        required_env_keys=("A_KEY",),
    )
    b = CapabilityWarning(
        capability_id="b",
        category=CapabilityCategory.ENRICHMENT,
        severity=CapabilitySeverity.MODERATE,
        title="B",
        impact="impact",
        required_env_keys=("B_KEY",),
    )

    assert warnings_fingerprint([a, b]) == warnings_fingerprint([b, a])
