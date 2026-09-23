import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url="sqlite://",
        data_dir=tmp_path,
        agentrouter_api_key="test-key",
        elevenlabs_api_key="test-key",
        discord_webhook_url="",
    )


@pytest.fixture
def client(settings):
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
