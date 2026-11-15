from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.content.seed_topics import TOPICS
from app.main import app
from app.schemas.learning import ProgressUpdate


def test_health_without_database() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "milestone": "M2"}


def test_docs_and_openapi_available() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/v1/topics" in paths
        assert "/api/v1/progress/{topic_id}" in paths


def test_progress_can_update_reading_without_marking_complete() -> None:
    body = ProgressUpdate(reading_position=1.0)
    assert body.reading_position == 1.0
    assert body.completed is None


@pytest.mark.parametrize("position", [-0.01, 1.01])
def test_progress_out_of_range_rejected(position: float) -> None:
    with pytest.raises(ValidationError):
        ProgressUpdate(reading_position=position)


def test_empty_progress_update_rejected() -> None:
    with pytest.raises(ValidationError):
        ProgressUpdate()


def test_topic_seed_is_unique_and_complete() -> None:
    assert len(TOPICS) == 8
    assert len({row["id"] for row in TOPICS}) == len(TOPICS)
    for topic in TOPICS:
        assert topic["content_md"].startswith("# ")
        assert "思考题" in topic["content_md"]
