from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.backtest.strategy_job import StrategyJobStatus
from app.services.backtest.worker import main


@dataclass
class Result:
    status: StrategyJobStatus


class Engine:
    def __init__(self, status: StrategyJobStatus) -> None:
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def run(self, job_id: str, claim_token: str):
        self.calls.append((job_id, claim_token))
        return Result(self.status)


def test_worker_dispatches_exact_claim_and_returns_success_for_complete() -> None:
    engine = Engine(StrategyJobStatus.COMPLETE)

    exit_code = main(
        ["--job-id", "job-1", "--claim-token", "claim-1"],
        engine_factory=lambda _job_id: engine,
    )

    assert exit_code == 0
    assert engine.calls == [("job-1", "claim-1")]


def test_worker_returns_failure_for_failed_authoritative_state() -> None:
    engine = Engine(StrategyJobStatus.FAILED)
    assert (
        main(
            ["--job-id", "job-1", "--claim-token", "claim-1"],
            engine_factory=lambda _job_id: engine,
        )
        == 1
    )


def test_worker_rejects_unknown_arguments() -> None:
    with pytest.raises(SystemExit):
        main(["--job-id", "job-1", "--claim-token", "claim-1", "--extra"])
