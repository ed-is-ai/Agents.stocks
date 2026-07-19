"""Contract tests for durable, cross-process pipeline status."""

from datetime import datetime, timedelta, timezone
import json

from app.repositories.pipeline_status_repo import PipelineStatusRepository
from app.schemas.pipeline_status import PipelineStage, PipelineState, StageState


def test_repository_round_trip_preserves_order_and_timing(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    repo = PipelineStatusRepository(path)

    status = repo.start(run_id="run-123")
    repo.transition(
        PipelineStage.SOURCES, StageState.RUNNING, expected_run_id="run-123"
    )
    repo.transition(
        PipelineStage.SOURCES, StageState.COMPLETE, expected_run_id="run-123"
    )
    repo.transition(
        PipelineStage.MARKET_DATA,
        StageState.RUNNING,
        expected_run_id="run-123",
    )
    repo.update_counts(scanned=14, expected_run_id="run-123")
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
    path.write_text("[]", encoding="utf-8")
    assert repo.load().state is PipelineState.IDLE


def test_structurally_incomplete_stage_list_returns_full_idle_model(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    payload = PipelineStatusRepository(path).start(run_id="incomplete").model_dump(
        mode="json"
    )
    payload["stages"] = payload["stages"][:-1]
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = PipelineStatusRepository(path).load()

    assert loaded.state is PipelineState.IDLE
    assert loaded.run_id is None
    assert [stage.stage for stage in loaded.stages] == list(PipelineStage)


def test_older_writer_cannot_mutate_or_finish_newer_run(tmp_path) -> None:
    repo = PipelineStatusRepository(tmp_path / "pipeline_status.json")
    repo.start(run_id="run-a")
    repo.transition(
        PipelineStage.SOURCES,
        StageState.RUNNING,
        expected_run_id="run-a",
    )
    repo.start(run_id="run-b")

    attached = repo.start(run_id="run-a", expected_run_id="run-a")
    repo.transition(
        PipelineStage.SOURCES,
        StageState.COMPLETE,
        expected_run_id="run-a",
    )
    repo.update_counts(scanned=99, expected_run_id="run-a")
    repo.finish(PipelineState.FAILED, expected_run_id="run-a")

    retained = repo.load()
    assert attached.run_id == "run-b"
    assert retained.run_id == "run-b"
    assert retained.state is PipelineState.RUNNING
    assert retained.scanned == 0
    assert retained.stage(PipelineStage.SOURCES).state is StageState.PENDING

    repo.transition(
        PipelineStage.SOURCES,
        StageState.RUNNING,
        expected_run_id="run-b",
    )
    assert repo.load().stage(PipelineStage.SOURCES).state is StageState.RUNNING


def test_stale_running_status_is_recovered_as_failed(tmp_path) -> None:
    path = tmp_path / "pipeline_status.json"
    repo = PipelineStatusRepository(path, stale_after_seconds=60)
    repo.start(run_id="abandoned")
    repo.transition(
        PipelineStage.SOURCES, StageState.RUNNING, expected_run_id="abandoned"
    )
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
    repo.transition(
        PipelineStage.SOURCES, StageState.RUNNING, expected_run_id="done"
    )
    repo.transition(
        PipelineStage.SOURCES, StageState.COMPLETE, expected_run_id="done"
    )

    finished = repo.finish(
        PipelineState.COMPLETE,
        expected_run_id="done",
        scanned=10,
        analysed=8,
        actionable=2,
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
    repo.transition(
        PipelineStage.SOURCES,
        StageState.RUNNING,
        expected_run_id="failed-between-stages",
    )
    repo.transition(
        PipelineStage.SOURCES,
        StageState.COMPLETE,
        expected_run_id="failed-between-stages",
    )

    failed = repo.finish(
        PipelineState.FAILED,
        expected_run_id="failed-between-stages",
        error_summary="assembly failed",
    )

    assert failed.stage(PipelineStage.SOURCES).state is StageState.FAILED
