"""Tests for GET /partials/realised-pnl (#177).

Regression-guards AC2 against the #147/#169 empty-string ``portfolio_id``
422 bug class, and smoke-tests the no-portfolios / zero-round-trips states.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.dependencies import get_realised_pnl_service, get_trader_service
from app.schemas import Portfolio, RealisedPnlSummary

client = TestClient(app)


@pytest.fixture
def mocked():
    mock_trader = MagicMock()
    mock_trader.list_portfolios.return_value = [
        Portfolio(id=1, name="SIPP", created_at="2024-01-01"),
    ]
    mock_realised_pnl = MagicMock()
    mock_realised_pnl.compute_summary.return_value = RealisedPnlSummary(
        portfolio_id=1,
        round_trips={},
        total_realised_pnl_gbp=0.0,
        round_trip_count=0,
    )
    app.dependency_overrides[get_trader_service] = lambda: mock_trader
    app.dependency_overrides[get_realised_pnl_service] = lambda: mock_realised_pnl
    try:
        yield mock_trader, mock_realised_pnl
    finally:
        app.dependency_overrides.clear()


def test_blank_portfolio_id_does_not_422(mocked):
    resp = client.get("/partials/realised-pnl", params={"portfolio_id": ""})
    assert resp.status_code == 200


def test_omitted_portfolio_id_does_not_422(mocked):
    resp = client.get("/partials/realised-pnl")
    assert resp.status_code == 200


def test_unknown_portfolio_id_falls_back_to_first_portfolio(mocked):
    _, mock_realised_pnl = mocked
    resp = client.get("/partials/realised-pnl", params={"portfolio_id": "999"})
    assert resp.status_code == 200
    mock_realised_pnl.compute_summary.assert_called_once_with(1)


def test_valid_portfolio_id_used_directly(mocked):
    _, mock_realised_pnl = mocked
    resp = client.get("/partials/realised-pnl", params={"portfolio_id": "1"})
    assert resp.status_code == 200
    mock_realised_pnl.compute_summary.assert_called_once_with(1)


def test_no_portfolios_renders_empty_state_without_calling_service(mocked):
    mock_trader, mock_realised_pnl = mocked
    mock_trader.list_portfolios.return_value = []
    resp = client.get("/partials/realised-pnl")
    assert resp.status_code == 200
    mock_realised_pnl.compute_summary.assert_not_called()


def test_zero_round_trips_shows_empty_state_copy(mocked):
    resp = client.get("/partials/realised-pnl", params={"portfolio_id": "1"})
    assert resp.status_code == 200
    assert "No Round-trips yet for this account." in resp.text
