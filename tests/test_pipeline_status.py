"""Contract tests for durable, cross-process pipeline status."""

from datetime import datetime, timedelta, timezone
import json

from app.repositories.pipeline_status_repo import PipelineStatusRepository
from app.schemas.pipeline_status import PipelineStage, PipelineState, StageState


def test_repository_round_trip_preserves_order_and_timing(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    repo = PipelineStatusRepository(path)

    status = repo.start(run_id="run-123")
    repo.transition(PipelineStage.SOURCES, StageState.RUNNING)
    repo.transition(PipelineStage.SOURCES, StageState.COMPLETE)
    repo.transition(PipelineStage.MARKET_DATA, StageState.RUNNING)
    repo.update_counts(scanned=14)
    loaded = repo.load()

    assert status.run_id == "run-123"
    assert loaded.state is PipelineState.RUNNING
    assert loaded.current_stage is PipelineStage.MARKET_DATA
    assert [stage.stage for stage in loaded.stages] == list(PipelineStage)
    assert loaded.stages[0].state is StageState.COMPLETE
    assert loaded.stages[0].duration_seconds is not None
    assert loaded.scanned == 14
    assert json.loads(path.read_text())["schema_version"] == 1


def test_repository_uses_replace_for_atomic_writes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "pipeline_status.json"
    replaced: list[tuple[object, object]] = []

    import app.repositories.pipeline_status_repo as repo_module

    real_replace = repo_module.os.replace

    def recording_replace(source, destination):
        replaced.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(repo_module.os, "replace", recording_replace)
    PipelineStatusRepository(path).start(run_id="atomic")

    assert len(replaced) == 1
    assert replaced[0][1] == path
    assert path.exists()


def test_missing_corrupt_and_unknown_schema_return_idle(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    repo = PipelineStatusRepository(path)

    assert repo.load().state is PipelineState.IDLE
    path.write_text("not-json", encoding="utf-8")
    assert repo.load().state is PipelineState.IDLE
    path.write_text('{"schema_version": 999}', encoding="utf-8")
    assert repo.load().state is PipelineState.IDLE


def test_stale_running_status_is_recovered_as_failed(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    repo = PipelineStatusRepository(path, stale_after_seconds=60)
    repo.start(run_id="abandoned")
    repo.transition(PipelineStage.SOURCES, StageState.RUNNING)
    payload = json.loads(path.read_text())
    old = datetime.now(timezone.utc) - timedelta(seconds=61)
    payload["updated_at"] = old.isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")

    recovered = repo.load()

    assert recovered.state is PipelineState.FAILED
    assert recovered.current_stage is PipelineStage.SOURCES
    assert recovered.stages[0].state is StageState.FAILED
    assert "interrupted" in (recovered.error_summary or "").lower()


def test_finish_retains_stage_durations_and_terminal_counts(tmp_path) -> None:
    repo = PipelineStatusRepository(tmp_path / "pipeline_status.json")
    repo.start(run_id="done")
    repo.transition(PipelineStage.SOURCES, StageState.RUNNING)
    repo.transition(PipelineStage.SOURCES, StageState.COMPLETE)

    finished = repo.finish(
        PipelineState.COMPLETE, scanned=10, analysed=8, actionable=2
    )

    assert finished.completed_at is not None
    assert finished.elapsed_seconds >= 0
    assert finished.scanned == 10
    assert finished.analysed == 8
    assert finished.actionable == 2
    assert all(stage.state is not StageState.PENDING for stage in finished.stages)


def test_failure_between_transitions_is_attributed_to_latest_stage(tmp_path) -> None:
    repo = PipelineStatusRepository(tmp_path / "pipeline_status.json")
    repo.start(run_id="failed-between-stages")
    repo.transition(PipelineStage.SOURCES, StageState.RUNNING)
    repo.transition(PipelineStage.SOURCES, StageState.COMPLETE)

    failed = repo.finish(PipelineState.FAILED, error_summary="assembly failed")

    assert failed.stage(PipelineStage.SOURCES).state is StageState.FAILED
