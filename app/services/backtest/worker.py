"""Claimed Strategy Manager worker module entry point."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Protocol

from app.core import config
from app.repositories import db
from app.repositories.backtest_repo import BacktestRepository
from app.repositories.historical_price_repo import HistoricalPriceRepository
from app.services.backtest.historical_initialization_engine import (
    CanonicalSnapshotMonthProcessor,
    HistoricalInitializationEngine,
)
from app.services.backtest.historical_data_qualification import (
    current_source_versions_json,
)
from app.services.backtest.reconstruction_roster import CapturedRosterV1
from app.services.backtest.strategy_job import StrategyJobStatus


class WorkerResult(Protocol):
    @property
    def status(self) -> StrategyJobStatus: ...


class WorkerEngine(Protocol):
    def run(self, job_id: str, claim_token: str) -> WorkerResult: ...


def build_initialization_engine(job_id: str) -> HistoricalInitializationEngine:
    """Build independent schema-ready repositories for one claimed child."""
    backtest = BacktestRepository(db.make_connect(lambda: str(config.BACKTEST_DB)))
    backtest.ensure_schema()
    prices = HistoricalPriceRepository(
        db.make_connect(lambda: str(config.HISTORICAL_PRICE_CACHE))
    )
    prices.ensure_schema()
    initialization = backtest.initialization_run(job_id)
    profile = backtest.snapshot_profile(initialization.profile_hash)
    if profile is None:
        raise RuntimeError("Pinned snapshot profile is unavailable")
    roster_json = backtest.roster_manifest_json(profile.roster_digest)
    if roster_json is None:
        raise RuntimeError("Pinned reconstruction roster is unavailable")
    roster = CapturedRosterV1.from_json(profile.roster_digest, roster_json)
    processor = CanonicalSnapshotMonthProcessor(
        job_id=job_id,
        profile=profile,
        roster=roster,
        backtest_repository=backtest,
        price_repository=prices,
    )

    def qualified() -> bool:
        result = backtest.latest_recorded_qualification()
        return (
            result is not None
            and result.passed
            and result.source_versions_json == current_source_versions_json()
        )

    def profile_is_current(profile_hash: str) -> bool:
        try:
            return backtest.snapshot_profile(profile_hash) is not None
        except Exception:
            return False

    return HistoricalInitializationEngine(
        backtest,
        processor,
        qualification_check=qualified,
        profile_check=profile_is_current,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    engine_factory: Callable[[str], WorkerEngine] = build_initialization_engine,
) -> int:
    parser = argparse.ArgumentParser(description="Run one claimed Strategy job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--claim-token", required=True)
    args = parser.parse_args(argv)
    engine = engine_factory(args.job_id)
    result = engine.run(args.job_id, args.claim_token)
    return (
        0
        if result.status
        in {
            StrategyJobStatus.COMPLETE,
            StrategyJobStatus.CANCELLED,
        }
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
