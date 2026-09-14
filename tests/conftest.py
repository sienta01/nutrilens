from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app_factory(tmp_path):
    """Give every test a real, isolated database and no network credentials."""
    with ExitStack() as stack:
        counter = 0

        def build(**overrides):
            nonlocal counter
            counter += 1
            settings_values = {
                "database_url": f"sqlite:///{(tmp_path / f'app-{counter}.sqlite3').as_posix()}",
                "upload_dir": tmp_path / f"uploads-{counter}",
                "demo_enabled": True,
                "telegram_polling": False,
                "cookie_secure": False,
                "log_file": "",
                "openai_api_key": "",
                "gemini_api_key": "",
                "groq_api_key": "",
                "ai_provider": "gemini",
                "telegram_bot_token": "",
            }
            settings_values.update(overrides)
            # _env_file=None: a developer's real .env (AI_n_* lines especially) must never
            # decide what a test sees. Every value a test depends on is set above.
            application = create_app(Settings(_env_file=None, **settings_values))
            client = stack.enter_context(
                TestClient(application, headers={"X-Requested-With": "NutriLens"})
            )
            return application, client

        yield build


@pytest.fixture
def app_and_client(app_factory):
    return app_factory()


@pytest.fixture
def app(app_and_client):
    return app_and_client[0]


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
def second_client(app):
    # The primary client owns the application's lifespan; this client has its
    # own browser cookie jar without starting another background worker.
    client = TestClient(app, headers={"X-Requested-With": "NutriLens"})
    try:
        yield client
    finally:
        client.close()
