from app.api.templating import templates
from types import SimpleNamespace


def _render(cash_balance, positions=None) -> str:
    context = {
        "positions": [] if positions is None else positions,
        "cash_balance": cash_balance,
        "cash_flows": [],
        "positions_with_value": [],
        "chart_points": 0,
        "portfolio_id": None,
        "portfolios": [],
        "active_portfolio": None,
        "chart_labels": "[]",
        "chart_values": "[]",
        "chart_costs": "[]",
        "chart_cash": "[]",
        "chart_buys": "[]",
        "chart_sells": "[]",
        "chart_buy_tips": "[]",
        "chart_sell_tips": "[]",
        "total_cost_gbp": 0,
        "total_value_gbp": 0,
        "total_pnl_gbp": 0,
        "total_cost_gbp_valued": 0,
        "prices_as_of": None,
        "gbpusd_rate": None,
        "error_message": None,
    }
    return templates.get_template("_portfolio.html").render(**context)


def test_zero_cash_is_visible_with_positions() -> None:
    position = SimpleNamespace(
        ticker="AAPL",
        shares=1,
        avg_cost=100,
        price_currency="GBP",
        total_cost=100,
        current_price=100,
        current_value=100,
        unrealised_pnl=0,
        unrealised_pnl_pct=0,
        entry_price=None,
        entry_date=None,
        stop_loss=None,
        profit_target_20=None,
        profit_target_25=None,
        next_pivot=None,
        exit_signal=None,
    )
    html = _render(0.0, positions=[position])
    assert "CASH" in html
    assert "£0.00" in html


def test_zero_cash_is_visible_for_cash_only_portfolio() -> None:
    html = _render(0.0)
    assert "CASH" in html
    assert "£0.00" in html
    assert "No open positions yet" not in html


def test_negative_cash_is_not_hidden() -> None:
    assert "CASH" in _render(-150.5)


def test_missing_cash_still_shows_empty_state() -> None:
    html = _render(None)
    assert "CASH" not in html
    assert "No open positions yet" in html
