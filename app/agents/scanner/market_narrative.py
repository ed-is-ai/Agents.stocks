"""Deterministic market-narrative blurb — the Phase 1 evergreen fallback.

Builds a plain-English ``MarketNarrative`` from sector-allocation deltas,
portfolio sector weights, and the static FOMC market-cycle context — no LLM
and no network involved. A later phase can build the *same* ``MarketNarrative``
shape from a Claude-generated summary using these same structured inputs;
callers (``AlertAgent.send_summary_email``, the watchlist banner) only ever
render a ``MarketNarrative`` and don't need to change when the source does.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.agents.scanner.market_cycle import (
    PHASE_MID_CYCLE,
    PHASE_POST_FOMC,
    PHASE_PRE_FOMC_BLACKOUT,
)
from app.core.config import MARKET_NARRATIVE_JSON
from app.schemas.market_cycle import MarketCycleContext
from app.schemas.market_narrative import MarketNarrative
from app.schemas.sector_allocation import (
    PortfolioSectorWeight,
    SectorAllocationSnapshot,
)

NOT_ADVICE_NOTE = (
    "Informational only, not financial advice. Sector prevalence reflects "
    "scanner candidates, not a recommendation to buy or sell."
)

_PHASE_LABELS = {
    PHASE_PRE_FOMC_BLACKOUT: "in the pre-FOMC blackout window",
    PHASE_POST_FOMC: "just past an FOMC decision",
    PHASE_MID_CYCLE: "mid-cycle between FOMC meetings",
}

_TOP_N = 3


def _pct(share: float) -> str:
    """Format a 0..1 fraction as a whole-number percentage string."""
    return f"{share * 100:.0f}%"


def _prevalence_bullet(snapshot: SectorAllocationSnapshot) -> str | None:
    """Return the "most-prevalent sectors" bullet, or None if no candidates."""
    top_shares = snapshot.shares[:_TOP_N]
    if not top_shares:
        return None
    leaders = ", ".join(f"{s.sector} ({_pct(s.count_share)})" for s in top_shares)
    return f"Most-prevalent scan sectors this run: {leaders}."


def _delta_bullets(snapshot: SectorAllocationSnapshot) -> list[str]:
    """Return gaining/losing-prevalence bullets, or a first-run note."""
    if not snapshot.deltas:
        return [
            "No prior run to compare against yet — this is the first "
            "sector-prevalence snapshot."
        ]
    bullets: list[str] = []
    gainers = [d for d in snapshot.deltas if d.delta > 0][:_TOP_N]
    losers = [d for d in snapshot.deltas if d.delta < 0][:_TOP_N]
    if gainers:
        bullets.append(
            "Gaining prevalence vs. the prior run: "
            + ", ".join(f"{d.sector} (+{_pct(d.delta)})" for d in gainers)
            + "."
        )
    if losers:
        bullets.append(
            "Losing prevalence vs. the prior run: "
            + ", ".join(f"{d.sector} ({_pct(d.delta)})" for d in losers)
            + "."
        )
    return bullets


def _portfolio_bullet(weights: list[PortfolioSectorWeight]) -> str | None:
    """Return the "current holdings concentrated in" bullet, or None if empty."""
    top_holdings = weights[:_TOP_N]
    if not top_holdings:
        return None
    return (
        "Current holdings concentrated in: "
        + ", ".join(f"{w.sector} ({_pct(w.value_share)})" for w in top_holdings)
        + "."
    )


def _cycle_bullet(cycle: MarketCycleContext) -> str:
    """Return the FOMC market-cycle context bullet."""
    phase_label = _PHASE_LABELS.get(cycle.phase, cycle.phase)
    bits = [f"Market is {phase_label}"]
    if cycle.days_since_last_decision is not None:
        bits.append(f"{cycle.days_since_last_decision}d since the last FOMC decision")
    if cycle.days_to_next_meeting is not None:
        bits.append(f"{cycle.days_to_next_meeting}d to the next meeting")
    return ", ".join(bits) + "."


def build_deterministic_narrative(
    scan_snapshot: SectorAllocationSnapshot,
    portfolio_weights: list[PortfolioSectorWeight],
    cycle: MarketCycleContext,
) -> MarketNarrative:
    """Build the deterministic sector-allocation + market-cycle blurb.

    Fully rule-based: no API keys, no network, no LLM. This is the evergreen
    fallback rendered whenever a later, Claude-generated narrative isn't
    available.
    """
    bullets: list[str] = []
    prevalence = _prevalence_bullet(scan_snapshot)
    if prevalence:
        bullets.append(prevalence)
    bullets.extend(_delta_bullets(scan_snapshot))
    portfolio_bullet = _portfolio_bullet(portfolio_weights)
    if portfolio_bullet:
        bullets.append(portfolio_bullet)
    bullets.append(_cycle_bullet(cycle))

    headline = (
        f"Scanner sector mix: {scan_snapshot.shares[0].sector} leads"
        if scan_snapshot.shares
        else "Sector-allocation snapshot"
    )

    return MarketNarrative(
        headline=headline,
        bullets=bullets,
        sources=[],
        not_advice=NOT_ADVICE_NOTE,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def save_market_narrative(narrative: MarketNarrative) -> None:
    """Persist *narrative* so the web banner and digest re-renders can reuse it.

    A simple whole-file overwrite is enough — only the latest run's narrative
    is ever needed (unlike the sector/scan history, which tracks deltas
    across runs).
    """
    MARKET_NARRATIVE_JSON.write_text(
        json.dumps(narrative.model_dump(mode="json"), indent=2), encoding="utf-8"
    )


def load_market_narrative() -> MarketNarrative | None:
    """Return the persisted narrative from the latest run, or None if absent."""
    try:
        payload = json.loads(MARKET_NARRATIVE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return MarketNarrative.model_validate(payload)
    except Exception:
        return None
