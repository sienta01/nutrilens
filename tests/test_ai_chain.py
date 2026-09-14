"""Ordered AI failover lines. Every provider call here is mocked."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app import vision
from app.config import Settings


def estimate(**changes):
    return {"is_food": True, "name": "Nasi goreng", "calories": 610, "protein": 22,
            "carbs": 85, "fat": 20, "confidence": "medium", "notes": "One plate.", **changes}


def gemini_ok(value=None):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps(estimate() if value is None else value)}]}}]}


def groq_ok(value=None):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": json.dumps(estimate() if value is None else value)}}]}


def openai_ok(value=None):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(estimate() if value is None else value)}]}]}


def route(monkeypatch, by_host):
    """Reply per hostname so a chain crossing providers can be asserted end to end."""
    real_client = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request)
        status, body = by_host[request.url.host]
        return httpx.Response(status, json=body)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    return calls


GOOGLE = "generativelanguage.googleapis.com"
GROQ = "api.groq.com"
OPENAI = "api.openai.com"


def chain_settings(**overrides):
    values = {
        "ai_1_provider": "gemini", "ai_1_api_key": "key-one",
        "ai_2_provider": "groq", "ai_2_api_key": "key-two",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_chain_is_built_in_order_with_per_line_models():
    config = chain_settings(ai_3_provider="openai", ai_3_api_key="key-three",
                            ai_2_model="openai/gpt-oss-120b")
    chain = config.ai_chain
    assert [(line.provider, line.api_key, line.model) for line in chain] == [
        ("gemini", "key-one", "gemini-flash-latest"),
        ("groq", "key-two", "openai/gpt-oss-120b"),
        ("openai", "key-three", "gpt-4.1-mini"),
    ]
    assert config.ai_configured is True
    assert config.ai_primary_provider == "gemini"
    assert config.ai_provider_labels == ["Google Gemini", "Groq", "OpenAI"]


def test_two_lines_may_be_the_same_provider_with_different_keys():
    config = chain_settings(ai_2_provider="gemini", ai_2_api_key="second-google-key")
    assert [(line.provider, line.api_key) for line in config.ai_chain] == [
        ("gemini", "key-one"), ("gemini", "second-google-key")]
    # Distinct labels for display, but both keys are really tried.
    assert config.ai_provider_labels == ["Google Gemini"]


def test_lines_replace_the_single_provider_settings_entirely():
    config = chain_settings(ai_provider="openai", openai_api_key="legacy-key")
    assert [line.provider for line in config.ai_chain] == ["gemini", "groq"]
    assert "legacy-key" not in [line.api_key for line in config.ai_chain]


def test_without_lines_the_legacy_single_provider_is_the_whole_chain():
    config = Settings(_env_file=None, ai_provider="groq", groq_api_key="only-key")
    assert [(line.provider, line.api_key) for line in config.ai_chain] == [("groq", "only-key")]
    assert Settings(_env_file=None, ai_provider="groq", groq_api_key="").ai_chain == []


async def test_failover_moves_to_the_next_line_when_a_line_is_out_of_quota(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (429, {"error": {"message": "quota exhausted"}}),
                                GROQ: (200, groq_ok())})
    result = await vision.estimate_meal(b"jpeg", "half a plate", chain_settings())
    assert result["calories"] == 610
    assert [call.url.host for call in calls] == [GOOGLE, GROQ]
    # Each line must use its own credential, never the previous line's.
    assert calls[0].headers["x-goog-api-key"] == "key-one"
    assert calls[1].headers["authorization"] == "Bearer key-two"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_every_provider_failure_class_fails_over(monkeypatch, status):
    calls = route(monkeypatch, {GOOGLE: (status, {"error": {"message": "nope"}}), GROQ: (200, groq_ok())})
    assert (await vision.estimate_meal(b"jpeg", "", chain_settings()))["calories"] == 610
    assert [call.url.host for call in calls] == [GOOGLE, GROQ]


async def test_a_non_food_answer_is_final_and_never_asks_another_provider(monkeypatch):
    """A 422 is a real answer; re-asking would spend a second quota and could invent a meal."""
    calls = route(monkeypatch, {GOOGLE: (200, gemini_ok(estimate(is_food=False))), GROQ: (200, groq_ok())})
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", chain_settings())
    assert error.value.status_code == 422
    assert [call.url.host for call in calls] == [GOOGLE]


async def test_a_blocked_or_refused_submission_is_also_final(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (200, {"promptFeedback": {"blockReason": "SAFETY"}}),
                                GROQ: (200, groq_ok())})
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", chain_settings())
    assert error.value.status_code == 422
    assert [call.url.host for call in calls] == [GOOGLE]


async def test_the_last_line_error_surfaces_when_every_line_fails(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (429, {"error": {}}), GROQ: (429, {"error": {}})})
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(b"jpeg", "", chain_settings())
    assert error.value.status_code == 503
    assert "Groq" in str(error.value)
    assert [call.url.host for call in calls] == [GOOGLE, GROQ]


async def test_failover_never_contacts_a_provider_that_is_not_on_the_chain(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (429, {"error": {}}), GROQ: (429, {"error": {}})})
    config = chain_settings(openai_api_key="unused-openai-key")
    with pytest.raises(vision.VisionError):
        await vision.estimate_meal(b"jpeg", "", config)
    assert OPENAI not in {call.url.host for call in calls}


async def test_a_three_line_chain_walks_all_the_way_to_the_third(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (429, {"error": {}}), GROQ: (500, {"error": {}}),
                                OPENAI: (200, openai_ok())})
    config = chain_settings(ai_3_provider="openai", ai_3_api_key="key-three")
    assert (await vision.estimate_meal(b"jpeg", "", config))["calories"] == 610
    assert [call.url.host for call in calls] == [GOOGLE, GROQ, OPENAI]


async def test_text_estimates_use_the_same_chain(monkeypatch):
    calls = route(monkeypatch, {GOOGLE: (429, {"error": {}}), GROQ: (200, groq_ok())})
    result = await vision.estimate_text_meal("2 eggs and toast", chain_settings())
    assert result["calories"] == 610
    assert [call.url.host for call in calls] == [GOOGLE, GROQ]
    assert "inlineData" not in calls[0].content.decode()
    assert "image_url" not in calls[1].content.decode()


async def test_an_empty_chain_never_opens_a_connection(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(vision.httpx, "AsyncClient", client)
    with pytest.raises(vision.VisionError, match="isn't configured"):
        await vision.estimate_meal(b"jpeg", "", Settings(_env_file=None, gemini_api_key=""))
    client.assert_not_called()


async def test_failover_logs_the_provider_but_never_the_key(monkeypatch, caplog):
    route(monkeypatch, {GOOGLE: (429, {"error": {"message": "secret-quota-detail"}}), GROQ: (200, groq_ok())})
    with caplog.at_level("WARNING"):
        await vision.estimate_meal(b"jpeg", "", chain_settings())
    assert "Google Gemini" in caplog.text
    assert "key-one" not in caplog.text
    assert "secret-quota-detail" not in caplog.text


def test_privacy_notice_names_every_provider_on_the_chain():
    notice = chain_settings().photo_privacy_notice
    assert "Google Gemini" in notice and "Groq" in notice
    assert "out of quota" in notice
    # A single-line install keeps the original single-provider wording.
    single = Settings(_env_file=None, ai_provider="groq", groq_api_key="k").photo_privacy_notice
    assert "Google" not in single and "next configured provider" not in single


def test_config_endpoint_reports_the_whole_chain_without_keys(app_factory):
    _, client = app_factory(ai_1_provider="groq", ai_1_api_key="private-groq-key",
                            ai_2_provider="gemini", ai_2_api_key="private-google-key")
    response = client.get("/api/config")
    config = response.json()
    assert config["ai_configured"] is True
    assert config["ai_provider"] == "groq"
    assert config["ai_provider_label"] == "Groq"
    assert config["ai_provider_labels"] == ["Groq", "Google Gemini"]
    assert "private-groq-key" not in response.text
    assert "private-google-key" not in response.text


@pytest.mark.parametrize("broken", [
    {"ai_1_provider": "gemini"},
    {"ai_1_provider": "anthropic", "ai_1_api_key": "k"},
    {"ai_1_provider": "gemini", "ai_1_api_key": "k", "ai_1_model": "https://evil.test"},
    {"ai_1_provider": "groq", "ai_1_api_key": "k", "ai_1_model": "../qwen"},
    {"ai_1_provider": "gemini", "ai_1_api_key": "k", "ai_1_model": "gpt-4.1-mini"},
])
def test_a_broken_line_is_rejected_at_startup(broken):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **broken)


def test_a_line_provider_is_normalised():
    config = Settings(_env_file=None, ai_1_provider="  GEMINI  ", ai_1_api_key="  k  ")
    assert config.ai_chain[0].provider == "gemini"
    assert config.ai_chain[0].api_key == "k"
