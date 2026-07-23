"""Route tests for the partial-refresh confirmation flow (#45)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.dependencies import (
    get_alerts_repository,
    get_integration_config_service,
    get_pipeline_service,
    get_portfolio_service,
    get_trader_service,
)
from app.services.capability_checks import (
    missing_capability_warnings,
    warnings_fingerprint,
)
from app.services.integration_config_service import (
    ALLOWED_KEYS,
    IntegrationConfigService,
)
from app.services.pipeline_service import PipelineRunResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_environ():
    saved = {key: os.environ.get(key) for key in ALLOWED_KEYS}
    for key in ALLOWED_KEYS:
        os.environ.pop(key, None)
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def wiring(tmp_path):
    config = IntegrationConfigService(tmp_path / ".env")
    trader = MagicMock()
    trader.get_portfolio.return_value = []
    portfolio = MagicMock()
    portfolio.load_analysis.return_value = []
    pipeline = MagicMock()
    pipeline.run_once.return_value = PipelineRunResult(success=True, details="done")
    alerts = MagicMock()
    alerts.has_watching.return_value = False
    alerts.last_alerted_at.return_value = None

    app.dependency_overrides[get_integration_config_service] = lambda: config
    app.dependency_overrides[get_trader_service] = lambda: trader
    app.dependency_overrides[get_portfolio_service] = lambda: portfolio
    app.dependency_overrides[get_pipeline_service] = lambda: pipeline
    app.dependency_overrides[get_alerts_repository] = lambda: alerts
    try:
        yield config, pipeline
    finally:
        app.dependency_overrides.clear()


def _post_refresh(**data):
    with patch.dict(os.environ, {"APP_AUTH_TOKEN": "s3cret"}):
        return client.post(
            "/refresh-data", data=data, headers={"X-Auth-Token": "s3cret"}
        )


def test_initial_post_with_missing_capabilities_shows_dialog_and_does_not_run(
    wiring,
) -> None:
    config, pipeline = wiring

    response = _post_refresh()

    assert response.status_code == 200
    assert 'id="pipelineConfirmationModal"' in response.text
    pipeline.run_once.assert_not_called()


def test_dialog_orders_warnings_by_severity(wiring) -> None:
    response = _post_refresh()
    markup = response.text

    fmp_pos = markup.find("FMP API key")
    av_pos = markup.find("Alpha Vantage API key")
    email_pos = markup.find("Email alert settings")
    assert -1 < fmp_pos < av_pos < email_pos


def test_dialog_response_has_no_store(wiring) -> None:
    response = _post_refresh()
    assert response.headers["cache-control"] == "no-store"


def test_dialog_never_includes_configured_secret_values(wiring) -> None:
    config, _ = wiring
    config.update(
        {"EMAIL_USER": "user@example.com", "EMAIL_PASSWORD": "sk-super-secret"}
    )

    response = _post_refresh()

    assert "sk-super-secret" not in response.text


def test_explicit_confirmation_with_matching_fingerprint_runs_pipeline(wiring) -> None:
    config, pipeline = wiring
    _post_refresh()
    fingerprint = warnings_fingerprint(missing_capability_warnings(config))

    response = _post_refresh(confirm_missing="true", confirmed_fingerprint=fingerprint)

    assert response.status_code == 200
    assert 'id="pipelineConfirmationModal"' not in response.text
    pipeline.run_once.assert_called_once()


def test_stale_fingerprint_is_rejected_and_redialogs_without_running(wiring) -> None:
    config, pipeline = wiring
    config.update({"FMP_API_KEY": "sk-123"})
    stale_fingerprint = warnings_fingerprint(missing_capability_warnings(config))
    # A brand-new critical warning appears after the dialog was rendered
    # (simulated here by clearing FMP_API_KEY again before confirming).
    config.update({}, clear_keys=["FMP_API_KEY"])

    response = _post_refresh(
        confirm_missing="true", confirmed_fingerprint=stale_fingerprint
    )

    assert response.status_code == 200
    assert 'id="pipelineConfirmationModal"' in response.text
    pipeline.run_once.assert_not_called()


def test_forged_fingerprint_matching_empty_state_does_not_bypass_real_warnings(
    wiring,
) -> None:
    config, pipeline = wiring
    forged = warnings_fingerprint([])  # fingerprint for "nothing missing"

    response = _post_refresh(confirm_missing="true", confirmed_fingerprint=forged)

    assert 'id="pipelineConfirmationModal"' in response.text
    pipeline.run_once.assert_not_called()


def test_all_capabilities_configured_while_dialog_open_proceeds_without_reconfirmation(
    wiring,
) -> None:
    config, pipeline = wiring
    stale_fingerprint = warnings_fingerprint(missing_capability_warnings(config))
    config.update(
        {
            "FMP_API_KEY": "sk-123",
            "ALPHA_VANTAGE_API_KEY": "av-123",
            "EMAIL_USER": "user@example.com",
            "EMAIL_PASSWORD": "pw",
            "EMAIL_TO": "alerts@example.com",
        }
    )

    response = _post_refresh(
        confirm_missing="true", confirmed_fingerprint=stale_fingerprint
    )

    assert 'id="pipelineConfirmationModal"' not in response.text
    pipeline.run_once.assert_called_once()


def test_fully_configured_service_skips_dialog_on_first_post(wiring) -> None:
    config, pipeline = wiring
    config.update(
        {
            "FMP_API_KEY": "sk-123",
            "ALPHA_VANTAGE_API_KEY": "av-123",
            "EMAIL_USER": "user@example.com",
            "EMAIL_PASSWORD": "pw",
            "EMAIL_TO": "alerts@example.com",
        }
    )

    response = _post_refresh()

    assert 'id="pipelineConfirmationModal"' not in response.text
    pipeline.run_once.assert_called_once()
