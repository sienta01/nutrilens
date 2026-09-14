"""Gemini requests are mocked: these tests never spend provider quota."""
import base64
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app import vision
from app.config import Settings


def estimate(**changes):
    return {"is_food": True, "name": "Nasi goreng", "calories": 610, "protein": 22,
            "carbs": 85, "fat": 20, "confidence": "medium", "notes": "One plate; oil is uncertain.", **changes}


def response_body(value=None, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"thought": True, "text": "Not part of the JSON answer."},
        {"text": json.dumps(estimate() if value is None else value)},
    ]}}]}


def fake_provider(monkeypatch, body, status=200):
    real_client = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    return requests


def settings(**overrides):
    return Settings(_env_file=None, ai_provider="gemini", gemini_api_key="fake-gemini-secret", **overrides)


async def test_gemini_image_schema_and_secret_in_header_only(monkeypatch):
    requests = fake_provider(monkeypatch, response_body())
    result = await vision.estimate_meal(b"normalized-jpeg", "half a plate", settings())
    assert result["name"] == "Nasi goreng"
    assert result["calories"] == 610
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path.endswith("gemini-flash-latest:generateContent")
    assert not request.url.query
    assert request.headers["x-goog-api-key"] == "fake-gemini-secret"
    body = json.loads(request.content)
    photo = body["contents"][0]["parts"][1]["inlineData"]
    assert photo["mimeType"] == "image/jpeg"
    assert base64.b64decode(photo["data"]) == b"normalized-jpeg"
    assert "half a plate" in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"]["responseJsonSchema"] == vision.MEAL_SCHEMA
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "fake-gemini-secret" not in request.content.decode()


async def test_missing_selected_key_does_not_use_openai(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(vision.httpx, "AsyncClient", client)
    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key="", openai_api_key="unused-secret")
    assert not config.ai_configured
    with pytest.raises(vision.VisionError, match="Gemini API key"):
        await vision.estimate_meal(b"jpeg", "", config)
    client.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_gemini_errors_are_safe_and_never_fall_back(monkeypatch, status):
    requests = fake_provider(monkeypatch, {"error": {"message": "fake-gemini-secret private notes"}}, status)
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings(openai_api_key="unused"))
    assert error.value.status_code in {502, 503}
    assert "fake-gemini-secret" not in str(error.value)
    assert "private notes" not in str(error.value)
    assert len(requests) == 1
    assert requests[0].url.host == "generativelanguage.googleapis.com"


@pytest.mark.parametrize("body", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    response_body(finish="MAX_TOKENS"), response_body(finish="SAFETY"),
    {}, {"candidates": []}, {"candidates": [None]}, [],
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "bad JSON"}]}}]},
    response_body(estimate(is_food=False)), response_body(estimate(calories=-1)),
    response_body(estimate(calories=float("nan"))), response_body(estimate(calories="100")),
    response_body(estimate(extra="unwanted")),
])
async def test_gemini_rejects_blocked_incomplete_and_invalid_estimates(monkeypatch, body):
    fake_provider(monkeypatch, body)
    with pytest.raises(vision.VisionError):
        await vision.estimate_meal(b"jpeg", "", settings())


async def test_gemini_network_error_is_sanitized(monkeypatch):
    real_client = httpx.AsyncClient

    def handle(request):
        raise httpx.ReadTimeout("fake-gemini-secret", request=request)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings())
    assert error.value.status_code == 503
    assert "fake-gemini-secret" not in str(error.value)


def test_provider_config_reports_selected_provider_without_keys(app_factory):
    _, client = app_factory(gemini_api_key="private-google-key", openai_api_key="private-openai-key")
    response = client.get("/api/config")
    config = response.json()
    assert config["ai_configured"] is True
    assert config["ai_provider"] == "gemini"
    assert config["ai_provider_label"] == "Google Gemini"
    assert "free tier" in config["photo_privacy_notice"]
    assert "private-google-key" not in response.text
    assert "private-openai-key" not in response.text
    _, client = app_factory(ai_provider="openai", gemini_api_key="unused", openai_api_key="")
    config = client.get("/api/config").json()
    assert not config["ai_configured"]
    assert config["ai_provider_label"] == "OpenAI"
    assert "Google" not in config["photo_privacy_notice"]


@pytest.mark.parametrize("model", ["https://evil.test", "gemini-x?key=secret", "../gemini-test"])
def test_model_cannot_change_endpoint(model):
    with pytest.raises(ValidationError):
        settings(gemini_model=model)


def test_gemini_web_upload_stores_estimate_and_quota_failure_stores_nothing(app_factory, monkeypatch):
    app, client = app_factory(gemini_api_key="fake-gemini-secret")
    registration = client.post("/api/auth/register", json={
        "email": "gemini@example.com", "password": "long-test-password", "display_name": "Gemini test",
    })
    assert registration.status_code == 201
    photo = io.BytesIO()
    Image.new("RGB", (60, 40), "orange").save(photo, "PNG")
    fake_provider(monkeypatch, response_body())
    saved = client.post("/api/meals/photo", files={"file": ("food.png", photo.getvalue(), "image/png")})
    assert saved.status_code == 201, saved.text
    assert saved.json()["calories"] == 610
    assert saved.json()["estimated"] is True
    assert len(list(app.state.settings.upload_dir.iterdir())) == 1
    # Reset the patch so its next transport doesn't wrap the previous mock.
    monkeypatch.undo()
    fake_provider(monkeypatch, {"error": {"message": "Quota exhausted"}}, 429)
    failed = client.post("/api/meals/photo", files={"file": ("food.png", photo.getvalue(), "image/png")})
    assert failed.status_code == 503
    assert len(client.get("/api/meals").json()["meals"]) == 1
    assert len(list(app.state.settings.upload_dir.iterdir())) == 1
