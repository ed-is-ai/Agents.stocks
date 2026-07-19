from fastapi.testclient import TestClient

from app.api.app import app
from app.repositories.pipeline_status_repo import PipelineStatusRepository
from app.schemas.pipeline_status import PipelineStage, PipelineState, StageState
import app.services.pipeline_service as pipeline_service_module


client = TestClient(app)


def test_pipeline_status_renders_stages_progress_and_active_polling(
    monkeypatch, tmp_path
) -> None:
    repo = PipelineStatusRepository(tmp_path / "status.json")
    monkeypatch.setattr(pipeline_service_module, "_status_repository", repo)
    repo.start(run_id="web-run")
    repo.transition(PipelineStage.SOURCES, StageState.RUNNING)
    repo.transition(PipelineStage.SOURCES, StageState.COMPLETE)
    repo.transition(PipelineStage.ANALYSIS, StageState.RUNNING, current=3, total=9)

    response = client.get("/pipeline-status")

    assert response.status_code == 200
    assert "Sources" in response.text
    assert "Analysis" in response.text
    assert "3/9" in response.text
    assert 'hx-trigger="every 2s"' in response.text


def test_pipeline_status_terminal_state_stops_polling(monkeypatch, tmp_path) -> None:
    repo = PipelineStatusRepository(tmp_path / "status.json")
    monkeypatch.setattr(pipeline_service_module, "_status_repository", repo)
    repo.start(run_id="web-run")
    repo.finish(PipelineState.PARTIAL, error_summary="One source failed")

    response = client.get("/pipeline-status")

    assert "Pipeline partially complete" in response.text
    assert 'hx-trigger="every 2s"' not in response.text
    assert "One source failed" in response.text
