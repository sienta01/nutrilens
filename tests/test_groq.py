"""Groq requests are mocked: these tests never spend provider quota."""
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


def response_body(value=None, finish="stop", **message):
    content = json.dumps(estimate() if value is None else value)
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": content, **message}}]}


def fake_provider(monkeypatch, body, status=200):
    """Patch httpx like the other provider suites; returns the captured requests."""
    real_client = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    return requests


def fake_sequence(monkeypatch, replies):
    """Reply with a different (status, body) per call, for the format downgrade."""
    real_client = httpx.AsyncClient
    requests = []

    def handle(request):
        status, body = replies[min(len(requests), len(replies) - 1)]
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    return requests


def settings(**overrides):
    return Settings(_env_file=None, ai_provider="groq", groq_api_key="fake-groq-secret", **overrides)


async def test_groq_image_schema_and_secret_in_header_only(monkeypatch):
    requests = fake_provider(monkeypatch, response_body())
    result = await vision.estimate_meal(b"normalized-jpeg", "half a plate", settings())
    assert result["name"] == "Nasi goreng"
    assert result["calories"] == 610
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.groq.com"
    assert request.url.path == "/openai/v1/chat/completions"
    assert not request.url.query
    assert request.headers["authorization"] == "Bearer fake-groq-secret"
    body = json.loads(request.content)
    assert body["model"] == "qwen/qwen3.8-27b"
    assert body["messages"][0]["role"] == "system"
    text, photo = body["messages"][1]["content"]
    assert "half a plate" in text["text"]
    assert photo["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert body["response_format"]["json_schema"]["schema"] == vision.MEAL_SCHEMA
    assert body["response_format"]["json_schema"]["strict"] is True
    # Without this the model wraps its answer in <think> tags and the JSON is unparseable.
    assert body["reasoning_format"] == "hidden"
    assert "fake-groq-secret" not in request.content.decode()


async def test_groq_text_request_carries_no_image(monkeypatch):
    requests = fake_provider(monkeypatch, response_body())
    await vision.estimate_text_meal("2 eggs, 2 slices of toast and a banana", settings())
    body = json.loads(requests[0].content)
    assert "image_url" not in str(body)
    assert len(body["messages"][1]["content"]) == 1
    assert "2 eggs" in body["messages"][1]["content"][0]["text"]
    assert "described" in body["messages"][0]["content"]


async def test_missing_selected_key_does_not_use_another_provider(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(vision.httpx, "AsyncClient", client)
    config = Settings(_env_file=None, ai_provider="groq", groq_api_key="",
                      gemini_api_key="unused-gemini", openai_api_key="unused-openai")
    assert not config.ai_configured
    with pytest.raises(vision.VisionError, match="Groq API key"):
        await vision.estimate_meal(b"jpeg", "", config)
    client.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 404, 413, 422, 429, 498, 500, 503])
async def test_groq_errors_are_safe_and_never_fall_back(monkeypatch, status):
    requests = fake_provider(monkeypatch, {"error": {"message": "fake-groq-secret private notes"}}, status)
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings(openai_api_key="unused", gemini_api_key="unused"))
    assert error.value.status_code in {502, 503}
    assert "fake-groq-secret" not in str(error.value)
    assert "private notes" not in str(error.value)
    assert all(request.url.host == "api.groq.com" for request in requests)


@pytest.mark.parametrize("status,expected", [
    (401, 503), (403, 503), (429, 503), (500, 503), (502, 503), (503, 503),
    (404, 502), (413, 502), (422, 502), (424, 502), (498, 502), (499, 502),
])
async def test_groq_status_codes_map_to_the_documented_buckets(monkeypatch, status, expected):
    fake_provider(monkeypatch, {"error": {"message": "nope", "type": "invalid_request_error"}}, status)
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings())
    assert error.value.status_code == expected


async def test_groq_downgrades_response_format_once_on_400(monkeypatch):
    """Groq's docs disagree on strict+image support, so a 400 renegotiates the format."""
    requests = fake_sequence(monkeypatch, [
        (400, {"error": {"message": "response_format not supported", "type": "invalid_request_error"}}),
        (200, response_body()),
    ])
    result = await vision.estimate_meal(b"jpeg", "", settings())
    assert result["calories"] == 610
    assert len(requests) == 2
    first, second = (json.loads(request.content) for request in requests)
    assert first["response_format"]["type"] == "json_schema"
    assert second["response_format"] == {"type": "json_object"}
    # Best-effort JSON mode enforces nothing, so the shape must be stated in the prompt.
    assert "is_food" in second["messages"][0]["content"]
    # A downgrade must stay on the same provider, model, and account.
    assert all(request.url.host == "api.groq.com" for request in requests)
    assert second["model"] == first["model"]


async def test_groq_gives_up_after_a_second_400(monkeypatch):
    requests = fake_provider(monkeypatch, {"error": {"message": "still bad"}}, 400)
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings())
    assert error.value.status_code == 502
    assert len(requests) == 2
    assert "still bad" not in str(error.value)


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [None]}, [],
    response_body(finish="length"),
    response_body(refusal="I cannot help with that."),
    {"choices": [{"finish_reason": "stop", "message": {"content": "bad JSON"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "<think>reasoning</think>{}"}}]},
    response_body(estimate(is_food=False)), response_body(estimate(calories=-1)),
    response_body(estimate(calories=float("nan"))), response_body(estimate(calories="100")),
    response_body(estimate(extra="unwanted")), response_body(estimate(confidence="certain")),
])
async def test_groq_rejects_refused_truncated_and_invalid_estimates(monkeypatch, body):
    fake_provider(monkeypatch, body)
    with pytest.raises(vision.VisionError):
        await vision.estimate_meal(b"jpeg", "", settings())


async def test_groq_network_error_is_sanitized(monkeypatch):
    real_client = httpx.AsyncClient

    def handle(request):
        raise httpx.ReadTimeout("fake-groq-secret", request=request)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", settings())
    assert error.value.status_code == 503
    assert "fake-groq-secret" not in str(error.value)


async def test_gpt_oss_model_omits_the_qwen_only_reasoning_parameter(monkeypatch):
    """reasoning_format is rejected outright by Groq's gpt-oss models."""
    requests = fake_provider(monkeypatch, response_body())
    await vision.estimate_text_meal("2 eggs", settings(groq_model="openai/gpt-oss-120b"))
    body = json.loads(requests[0].content)
    assert "reasoning_format" not in body
    assert body["model"] == "openai/gpt-oss-120b"


def test_provider_config_reports_groq_without_keys(app_factory):
    _, client = app_factory(ai_provider="groq", groq_api_key="private-groq-key",
                            gemini_api_key="private-google-key")
    response = client.get("/api/config")
    config = response.json()
    assert config["ai_configured"] is True
    assert config["ai_provider"] == "groq"
    assert config["ai_provider_label"] == "Groq"
    assert "Google" not in config["photo_privacy_notice"]
    assert "private-groq-key" not in response.text
    assert "private-google-key" not in response.text
    # A spare key for a different provider must not advertise analysis.
    _, client = app_factory(ai_provider="groq", groq_api_key="", openai_api_key="unused")
    assert client.get("/api/config").json()["ai_configured"] is False


@pytest.mark.parametrize("model", ["https://evil.test", "qwen?key=secret", "../qwen", "a/b/c", "/qwen", ""])
def test_groq_model_cannot_change_endpoint(model):
    with pytest.raises(ValidationError):
        settings(groq_model=model)


@pytest.mark.parametrize("model", ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"])
def test_real_groq_model_ids_are_accepted(model):
    assert settings(groq_model=model).groq_model == model


def test_groq_web_upload_stores_estimate_and_quota_failure_stores_nothing(app_factory, monkeypatch):
    app, client = app_factory(ai_provider="groq", groq_api_key="fake-groq-secret")
    registration = client.post("/api/auth/register", json={
        "email": "groq@example.com", "password": "long-test-password", "display_name": "Groq test",
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
