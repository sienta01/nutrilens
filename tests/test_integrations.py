import io
import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app import vision
from app.config import Settings
from app.db import Database
from app.main import DropPollingNoise, configure_logging
from app.models import BotUpdate, Meal, User
from app.telegram_bot import TelegramBot, TelegramError


def photo_bytes(size=(80, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "orange").save(buffer, format="JPEG")
    return buffer.getvalue()


def valid_estimate(**overrides):
    value = {"is_food": True, "name": "Rice bowl", "calories": 510, "protein": 25,
             "carbs": 64, "fat": 17, "confidence": "medium", "notes": "One bowl; oil amount is uncertain."}
    value.update(overrides)
    return value


def provider_body(value):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(value)}
    ]}]}


def mock_provider(monkeypatch, response_body, status=200):
    real_client = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=response_body)

    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs
    ))
    return calls


def test_normalize_rotates_strips_metadata_and_resizes():
    source = Image.new("RGB", (2400, 1200), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private camera description"
    buffer = io.BytesIO()
    source.save(buffer, "JPEG", exif=exif)
    normalized = vision.normalize_image(buffer.getvalue())
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (800, 1600)
        assert not image.getexif()
        assert "icc_profile" not in image.info


def test_normalize_transparency_to_white():
    source = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    with Image.open(io.BytesIO(vision.normalize_image(buffer.getvalue()))) as image:
        assert image.mode == "RGB"
        assert image.getpixel((10, 10)) == (255, 255, 255)


@pytest.mark.parametrize("content", [b"<svg><script>alert(1)</script></svg>", b"", b"not a jpeg", photo_bytes()[:50]])
def test_normalize_rejects_invalid_files(content):
    with pytest.raises(vision.VisionError):
        vision.normalize_image(content)


@pytest.mark.asyncio
async def test_estimate_requires_key_without_network(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(vision.httpx, "AsyncClient", fake)
    with pytest.raises(vision.VisionError, match="isn't configured") as error:
        await vision.estimate_meal(photo_bytes(), "", Settings(_env_file=None, ai_provider="openai", openai_api_key=""))
    assert error.value.status_code == 503
    fake.assert_not_called()


@pytest.mark.asyncio
async def test_estimate_uses_schema_image_and_no_storage(monkeypatch):
    calls = mock_provider(monkeypatch, provider_body(valid_estimate()))
    result = await vision.estimate_meal(photo_bytes(), "half a bowl", Settings(_env_file=None, ai_provider="openai", openai_api_key="test-secret"))
    assert result["calories"] == 510
    assert "is_food" not in result
    request = json.loads(calls[0].content)
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"]["additionalProperties"] is False
    assert request["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize("changes", [
    {"is_food": False}, {"calories": float("nan")}, {"fat": float("inf")},
    {"protein": -1}, {"calories": "510"}, {"calories": True}, {"confidence": []},
    {"name": ""}, {"unexpected": "value"},
])
@pytest.mark.asyncio
async def test_estimate_rejects_nonfood_and_invalid_values(monkeypatch, changes):
    mock_provider(monkeypatch, provider_body(valid_estimate(**changes)))
    with pytest.raises(vision.VisionError):
        await vision.estimate_meal(photo_bytes(), "", Settings(_env_file=None, ai_provider="openai", openai_api_key="test-secret"))


@pytest.mark.asyncio
async def test_provider_failure_never_exposes_secret(monkeypatch):
    mock_provider(monkeypatch, {"error": {"message": "Authorization test-secret failed"}}, 401)
    with pytest.raises(vision.VisionError) as error:
        await vision.estimate_meal(photo_bytes(), "", Settings(_env_file=None, ai_provider="openai", openai_api_key="test-secret"))
    assert error.value.status_code == 503
    assert "test-secret" not in str(error.value)


@pytest.fixture
def bot_context(tmp_path):
    settings = Settings(_env_file=None, upload_dir=tmp_path / "uploads", telegram_bot_token="123:test-bot-secret", openai_api_key="", gemini_api_key="")
    database = Database("sqlite:///:memory:")
    database.initialize()
    with database.session() as db:
        user = User(email="bot@example.com", display_name="Photo User", password_hash="not-used", timezone="Asia/Makassar", telegram_user_id="42", telegram_chat_id="42")
        db.add(user)
        db.commit()
        user_id = user.id
    bot = TelegramBot(settings, database)
    bot._send = AsyncMock()
    yield bot, database, user_id
    database.close()


def event(update_id, **message):
    return {"update_id": update_id, "message": {
        "chat": {"id": 42, "type": "private"}, "from": {"id": 42},
        "date": int(datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc).timestamp()), **message,
    }}


@pytest.mark.asyncio
async def test_telegram_photo_retry_saves_once_and_keeps_timestamp(bot_context, monkeypatch):
    bot, database, user_id = bot_context
    estimate = valid_estimate()
    estimate.pop("is_food")
    analyze = AsyncMock(return_value=estimate)
    monkeypatch.setattr(vision, "estimate_meal", analyze)
    bot._download = AsyncMock(return_value=photo_bytes())
    bot._send.side_effect = [TelegramError(503), None]
    update = event(501, photo=[{"file_id": "photo-1", "width": 100, "height": 100, "file_size": 1000}], caption="One bowl")
    with pytest.raises(TelegramError):
        await bot.handle_update(update)
    with database.session() as db:
        meal = db.scalar(select(Meal).where(Meal.user_id == user_id))
        assert meal.logged_at == datetime(2026, 9, 12, 4, 0)
        assert meal.meal_type == "lunch"
        assert db.get(BotUpdate, 501) is None
    await bot.handle_update(update)
    await bot.handle_update(update)
    with database.session() as db:
        assert len(list(db.scalars(select(Meal)))) == 1
        assert db.get(BotUpdate, 501) is not None
    assert analyze.await_count == 1
    assert bot._download.await_count == 1
    assert bot._send.await_count == 2


@pytest.mark.asyncio
async def test_telegram_provider_failure_marks_update_without_meal(bot_context, monkeypatch):
    bot, database, _ = bot_context
    analyze = AsyncMock(side_effect=vision.VisionError("Try a clearer photo."))
    monkeypatch.setattr(vision, "estimate_meal", analyze)
    bot._download = AsyncMock(return_value=photo_bytes())
    update = event(502, photo=[{"file_id": "photo-1"}])
    await bot.handle_update(update)
    await bot.handle_update(update)
    with database.session() as db:
        assert db.get(BotUpdate, 502) is not None
        assert list(db.scalars(select(Meal))) == []
    assert analyze.await_count == 1
    assert not list(bot.settings.upload_dir.glob("*.jpg"))


@pytest.mark.asyncio
async def test_telegram_photo_rate_limit_blocks_download_and_inference(bot_context):
    bot, database, user_id = bot_context
    for _ in range(20):
        bot._photo_limiter.check(f"telegram-photo:{user_id}", 20, 3600)
    bot._download = AsyncMock()
    await bot.handle_update(event(505, photo=[{"file_id": "photo"}]))
    bot._download.assert_not_awaited()
    assert "20 AI meal analyses per hour" in bot._send.call_args.args[1]
    with database.session() as db:
        assert db.get(BotUpdate, 505) is not None


@pytest.mark.asyncio
async def test_telegram_undo_retries_do_not_delete_another_meal(bot_context):
    bot, database, user_id = bot_context
    bot.settings.upload_dir.mkdir()
    (bot.settings.upload_dir / "latest.jpg").write_bytes(photo_bytes())
    with database.session() as db:
        other = User(email="other@example.com", display_name="Other", password_hash="not-used")
        db.add(other)
        db.flush()
        db.add_all([
            Meal(user_id=user_id, name="Earlier", calories=100, source="telegram", logged_at=datetime(2026, 9, 12, 1)),
            Meal(user_id=user_id, name="Latest Telegram", calories=200, source="telegram", logged_at=datetime(2026, 9, 12, 2), image_path="latest.jpg"),
            Meal(user_id=user_id, name="Web meal", calories=300, source="web", logged_at=datetime(2026, 9, 12, 3)),
            Meal(user_id=other.id, name="Other user meal", calories=400, source="telegram", logged_at=datetime(2026, 9, 12, 4)),
        ])
        db.commit()
    bot._send.side_effect = TelegramError(503)
    with pytest.raises(TelegramError):
        await bot.handle_update(event(503, text="/undo"))
    await bot.handle_update(event(503, text="/undo"))
    with database.session() as db:
        assert set(db.scalars(select(Meal.name))) == {"Earlier", "Web meal", "Other user meal"}
        assert db.get(BotUpdate, 503) is not None
    assert not (bot.settings.upload_dir / "latest.jpg").exists()


@pytest.mark.asyncio
async def test_group_photos_are_ignored(bot_context):
    bot, database, _ = bot_context
    bot._download = AsyncMock()
    await bot.handle_update(event(504, chat={"id": -10, "type": "group"}, photo=[{"file_id": "photo"}]))
    bot._send.assert_not_awaited()
    bot._download.assert_not_awaited()
    with database.session() as db:
        assert db.get(BotUpdate, 504) is not None


@pytest.mark.asyncio
async def test_download_enforces_size_limit_and_redacts_logs(bot_context, caplog):
    bot, _, _ = bot_context
    bot.settings.max_upload_bytes = 20
    bot._api = AsyncMock(return_value={"file_path": "photos/photo.jpg"})
    bot._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 21)))
    with caplog.at_level(logging.INFO, logger="httpx"):
        with pytest.raises(vision.VisionError, match="too large"):
            await bot._download("photo-id")
    await bot.aclose()
    assert bot.settings.telegram_bot_token not in caplog.text


@pytest.mark.asyncio
async def test_polling_conflict_stops_without_changing_webhook(bot_context, caplog):
    bot, _, _ = bot_context
    bot._api = AsyncMock(side_effect=TelegramError(409))
    await bot.run()
    assert bot._api.await_count == 1
    assert bot._api.call_args.args[0] == "getUpdates"
    assert "polling conflict" in caplog.text


@pytest.mark.parametrize("provider", ["gemini", "openai"])
async def test_text_estimate_uses_selected_provider_schema_and_no_image(monkeypatch, provider):
    body = provider_body(valid_estimate()) if provider == "openai" else {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(valid_estimate())}]}}],
    }
    calls = mock_provider(monkeypatch, body)
    config = Settings(_env_file=None, ai_provider=provider, gemini_api_key="fake-gemini", openai_api_key="fake-openai")
    result = await vision.estimate_text_meal("2 eggs, 2 slices of toast and a banana", config)
    assert result["calories"] == 510
    assert len(calls) == 1
    payload = json.loads(calls[0].content)
    assert "input_image" not in str(payload) and "inlineData" not in str(payload)
    if provider == "gemini":
        assert calls[0].url.host == "generativelanguage.googleapis.com"
        assert payload["generationConfig"]["responseJsonSchema"] == vision.MEAL_SCHEMA
        assert len(payload["contents"][0]["parts"]) == 1
        assert "2 eggs" in payload["contents"][0]["parts"][0]["text"]
        assert "described" in payload["systemInstruction"]["parts"][0]["text"]
    else:
        assert calls[0].url.host == "api.openai.com"
        assert payload["store"] is False
        assert payload["text"]["format"]["schema"] == vision.MEAL_SCHEMA
        assert len(payload["input"][0]["content"]) == 1
        assert "2 eggs" in payload["input"][0]["content"][0]["text"]
        assert "described" in payload["instructions"]


@pytest.mark.parametrize("message", ["2 eggs and toast", "/log 2 eggs and toast", "/log@NutriLensBot 2 eggs and toast"])
async def test_telegram_text_retry_deduplicates_and_preserves_local_meal_time(bot_context, monkeypatch, message):
    bot, database, user_id = bot_context
    estimate = valid_estimate()
    estimate.pop("is_food")
    analyze = AsyncMock(return_value=estimate)
    monkeypatch.setattr(vision, "estimate_text_meal", analyze)
    bot._send.side_effect = [TelegramError(503), None]
    update = event(601, text=message)
    with pytest.raises(TelegramError):
        await bot.handle_update(update)
    await bot.handle_update(update)
    await bot.handle_update(update)
    assert analyze.await_count == 1 and bot._send.await_count == 2
    assert analyze.call_args.args[0] == "2 eggs and toast"
    assert "Text estimate" in bot._send.call_args.args[1]
    with database.session() as db:
        meals = list(db.scalars(select(Meal)))
        assert len(meals) == 1
        meal = meals[0]
        assert meal.user_id == user_id and meal.source == "telegram" and meal.estimated
        assert meal.image_path is None and meal.confidence == "medium"
        assert meal.logged_at == datetime(2026, 9, 12, 4) and meal.meal_type == "lunch"
        assert db.get(BotUpdate, 601) is not None
    assert not list(bot.settings.upload_dir.glob("*"))


@pytest.mark.parametrize("message,expected", [
    ("/log Chicken rice | 650 | 40 | 75 | 20", (650, 40, 75, 20)),
    ("/log Coffee | 60.5", (60.5, 0, 0, 0)),
    ("Coffee | 0", (0, 0, 0, 0)),
])
async def test_exact_text_values_work_without_ai_and_can_be_undone(bot_context, monkeypatch, message, expected):
    bot, database, _ = bot_context
    analyze = AsyncMock()
    monkeypatch.setattr(vision, "estimate_text_meal", analyze)
    await bot.handle_update(event(602, text=message))
    await bot.handle_update(event(602, text=message))
    with database.session() as db:
        meal = db.scalar(select(Meal))
        assert (meal.calories, meal.protein, meal.carbs, meal.fat) == expected
        assert not meal.estimated and meal.confidence is None
        if expected[1:] == (0, 0, 0):
            assert "Macros not supplied" in meal.notes
    analyze.assert_not_called()
    assert "supplied values" in bot._send.call_args.args[1]
    assert "≈" not in bot._send.call_args.args[1]
    await bot.handle_update(event(603, text="/undo"))
    with database.session() as db:
        assert list(db.scalars(select(Meal))) == []


@pytest.mark.parametrize("message", [
    "/log", "/log | 250", "/log Rice | -5", "/log Rice | NaN", "/log Rice | inf",
    "/log Rice | 200 | 5", "/log Rice | 200 | 5 | 40 | 2 | 1", "/log Rice | 20001",
    "/log Rice | 200 | 5 | 40 | -2", "/log Rice | 200 kcal", "x" * 2001,
])
async def test_invalid_text_never_saves_or_calls_ai(bot_context, monkeypatch, message):
    bot, database, _ = bot_context
    analyze = AsyncMock()
    monkeypatch.setattr(vision, "estimate_text_meal", analyze)
    await bot.handle_update(event(604, text=message))
    analyze.assert_not_called()
    with database.session() as db:
        assert db.scalar(select(Meal)) is None and db.get(BotUpdate, 604) is not None


async def test_text_failure_and_unknown_commands_do_not_create_entries(bot_context, monkeypatch):
    bot, database, _ = bot_context
    analyze = AsyncMock(side_effect=vision.VisionError("I couldn't identify a meal."))
    monkeypatch.setattr(vision, "estimate_text_meal", analyze)
    await bot.handle_update(event(605, text="hello"))
    assert "couldn't identify a meal" in bot._send.call_args.args[1]
    for i, command in enumerate(["/unknown", "/goal", "/fasting", "/today", "/help"], 606):
        await bot.handle_update(event(i, text=command))
    assert analyze.await_count == 1
    with database.session() as db:
        assert db.scalar(select(Meal)) is None


async def test_text_respects_private_linked_accounts_and_shared_ai_limit(bot_context, monkeypatch):
    bot, database, user_id = bot_context
    analyze = AsyncMock()
    monkeypatch.setattr(vision, "estimate_text_meal", analyze)
    await bot.handle_update(event(611, text="Eggs", chat={"id": -42, "type": "group"}))
    await bot.handle_update(event(612, text="Eggs", chat={"id": 43, "type": "private"}, **{"from": {"id": 43}}))
    assert "Connect your account first" in bot._send.call_args.args[1]
    for _ in range(20):
        bot._photo_limiter.check(f"telegram-photo:{user_id}", 20, 3600)
    await bot.handle_update(event(613, text="Eggs"))
    assert "20 AI meal analyses" in bot._send.call_args.args[1]
    analyze.assert_not_called()
    # Exact values remain available after the shared photo/text inference limit.
    await bot.handle_update(event(614, text="/log Eggs | 160 | 14 | 0 | 10"))
    with database.session() as db:
        assert db.scalar(select(Meal)).user_id == user_id


async def test_each_telegram_account_logs_to_its_own_journal(bot_context):
    bot, database, user_id = bot_context
    with database.session() as db:
        other = User(email="other-text@example.com", display_name="Other", password_hash="unused",
                     telegram_user_id="43", telegram_chat_id="43")
        db.add(other)
        db.commit()
        other_id = other.id
    await bot.handle_update(event(615, text="/log Eggs | 160"))
    await bot.handle_update(event(616, text="/log Rice | 200", chat={"id": 43, "type": "private"}, **{"from": {"id": 43}}))
    with database.session() as db:
        assert db.scalar(select(Meal.name).where(Meal.user_id == user_id)) == "Eggs"
        assert db.scalar(select(Meal.name).where(Meal.user_id == other_id)) == "Rice"


def _httpx_record(message):
    return logging.LogRecord("httpx", logging.INFO, "", 0, message, (), None)


def _access_record(path, status):
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:43744", "GET", path, "1.1", status), None)


@pytest.mark.parametrize("record, kept", [
    # The long poll and the health probe repeat every ~30s on an idle server.
    (_httpx_record('HTTP Request: POST https://api.telegram.org/bot1234:secret/getUpdates "HTTP/1.1 200 OK"'), False),
    (_httpx_record('HTTP Request: POST https://api.telegram.org/bot[REDACTED]/getUpdates "HTTP/1.1 200 OK"'), False),
    (_access_record("/health", 200), False),
    # A failing poll or probe is the whole reason someone reads these logs.
    (_httpx_record('HTTP Request: POST https://api.telegram.org/bot[REDACTED]/getUpdates "HTTP/1.1 409 Conflict"'), True),
    (_access_record("/health", 503), True),
    # Provider attempts must survive: app.vision logs our mapped status, never the upstream one.
    (_httpx_record('HTTP Request: POST https://api.groq.com/openai/v1/chat/completions "HTTP/1.1 429 Too Many"'), True),
    (_httpx_record('HTTP Request: POST https://api.telegram.org/bot[REDACTED]/sendMessage "HTTP/1.1 200 OK"'), True),
    (_access_record("/api/meals", 200), True),
])
def test_polling_noise_filter_drops_idle_chatter_only(record, kept):
    assert DropPollingNoise().filter(record) is kept


def test_configure_logging_installs_one_filter_and_debug_removes_it():
    targets = [logging.getLogger("httpx"), logging.getLogger("uvicorn.access")]
    saved = [list(target.filters) for target in targets]
    # configure_logging() also lowers the root and "app" levels; a DEBUG call here must not
    # leak that into the rest of the session.
    root_level, app_level = logging.getLogger().level, logging.getLogger("app").level
    try:
        def installed():
            return [len([f for f in t.filters if isinstance(f, DropPollingNoise)]) for t in targets]

        base = dict(_env_file=None, log_file="", telegram_bot_token="")
        configure_logging(Settings(**base, log_level="INFO"))
        configure_logging(Settings(**base, log_level="INFO"))
        assert installed() == [1, 1], "repeated create_app() must not stack filters"

        configure_logging(Settings(**base, log_level="DEBUG"))
        assert installed() == [0, 0], "DEBUG means show everything"
    finally:
        for target, original in zip(targets, saved):
            for extra in list(target.filters):
                target.removeFilter(extra)
            for original_filter in original:
                target.addFilter(original_filter)
        logging.getLogger().setLevel(root_level)
        logging.getLogger("app").setLevel(app_level)
