"""End-to-end API checks for ownership, privacy, and nutrition accounting."""

import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import BotUpdate, LinkCode, Meal, User
from app.security import token_hash
from app.telegram_bot import TelegramBot


PASSWORD = "A-long-test-password-493!"


def register(client, email="alex@example.com", display_name="Alex", **extra):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": display_name,
            "timezone": "UTC",
            **extra,
        },
    )
    assert response.status_code in (200, 201), response.text
    return response


def current_user(client):
    response = client.get("/api/me")
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload.get("user", payload)


def test_registration_login_logout_and_hashed_password(client, app):
    response = register(client)
    user = current_user(client)
    assert user["email"] == "alex@example.com"
    assert user["display_name"] == "Alex"
    assert user["share_progress"] is False
    assert user["share_meals"] is False
    assert PASSWORD not in response.text
    assert "password_hash" not in response.text
    cookies = response.headers.get("set-cookie", "").lower()
    assert "httponly" in cookies
    assert "samesite=lax" in cookies or "samesite=strict" in cookies

    with app.state.db.session() as session:
        stored = session.scalar(select(User).where(User.email == "alex@example.com"))
        assert stored is not None
        assert stored.password_hash != PASSWORD
        assert PASSWORD not in stored.password_hash

    assert client.post("/api/auth/logout").status_code in (200, 204)
    assert client.get("/api/me").status_code == 401
    response = client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    assert current_user(client)["id"] == user["id"]


def test_duplicate_and_bad_credentials(client):
    register(client)
    duplicate = client.post(
        "/api/auth/register",
        json={"email": "ALEX@example.com", "password": PASSWORD, "display_name": "Other"},
    )
    assert duplicate.status_code == 409
    client.post("/api/auth/logout")
    for email, password in (
        ("alex@example.com", "Incorrect-password!"),
        ("missing@example.com", PASSWORD),
    ):
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert client.get("/api/me").status_code == 401


def test_password_preserves_intended_surrounding_whitespace(client):
    password = "  validPassword123  "
    register(client, password=password)
    original_id = current_user(client)["id"]
    client.post("/api/auth/logout")

    trimmed = client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": password.strip()}
    )
    assert trimmed.status_code == 401
    assert client.get("/api/me").status_code == 401

    exact = client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": password}
    )
    assert exact.status_code == 200, exact.text
    assert current_user(client)["id"] == original_id


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD, "display_name": "Alex"},
        {"email": "alex@example.com", "password": "x", "display_name": "Alex"},
        {"email": "alex@example.com", "password": PASSWORD, "display_name": ""},
    ],
)
def test_invalid_registration(client, payload):
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_mutations_require_custom_header_and_same_origin(client):
    client.headers.pop("X-Requested-With")
    payload = {"email": "alex@example.com", "password": PASSWORD, "display_name": "Alex"}
    assert client.post("/api/auth/register", json=payload).status_code == 403
    client.headers["X-Requested-With"] = "NutriLens"
    assert client.post(
        "/api/auth/register", json=payload, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
    register(client)
    assert client.patch(
        "/api/me", json={"share_progress": True}, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
    assert current_user(client)["share_progress"] is False


@pytest.mark.parametrize("endpoint", ["/api/me", "/api/meals", "/api/dashboard"])
def test_private_endpoints_require_authentication(client, endpoint):
    assert client.get(endpoint).status_code == 401


@pytest.mark.parametrize(
    "field", ["display_name", "timezone", "daily_calorie_goal", "protein_goal", "carbs_goal", "fat_goal", "share_progress", "share_meals"]
)
def test_profile_patch_rejects_null(client, field):
    register(client)
    assert client.patch("/api/me", json={field: None}).status_code == 422


def test_invalid_profile_values_leave_account_unchanged(client):
    register(client)
    before = current_user(client)
    for payload in (
        {"timezone": "Imaginary/Nowhere"},
        {"daily_calorie_goal": -1},
        {"display_name": ""},
    ):
        assert client.patch("/api/me", json=payload).status_code == 422
    assert current_user(client) == before


def create_meal(client, **changes):
    response = client.post(
        "/api/meals",
        json={
            "name": "Grilled chicken bowl",
            "calories": 520,
            "protein": 42,
            "carbs": 53,
            "fat": 16,
            "meal_type": "lunch",
            "notes": "One bowl",
            **changes,
        },
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    return payload.get("meal", payload)


def meals(client):
    response = client.get("/api/meals")
    assert response.status_code == 200, response.text
    return response.json()["meals"]


def test_meal_create_correct_and_delete(client):
    register(client)
    meal = create_meal(client)
    assert meal["name"] == "Grilled chicken bowl"
    assert meal["calories"] == 520
    assert meal["source"] == "manual"
    assert meal["estimated"] is False
    assert [item["id"] for item in meals(client)] == [meal["id"]]

    response = client.patch(
        f"/api/meals/{meal['id']}", json={"calories": 610, "protein": 49, "notes": "Larger portion"}
    )
    assert response.status_code == 200, response.text
    corrected = meals(client)[0]
    assert corrected["calories"] == 610
    assert corrected["protein"] == 49
    assert corrected["notes"] == "Larger portion"
    assert client.delete(f"/api/meals/{meal['id']}").status_code in (200, 204)
    assert meals(client) == []
    assert client.delete(f"/api/meals/{meal['id']}").status_code == 404


def test_accounts_cannot_edit_delete_or_download_each_others_meals(client, second_client, app):
    register(client)
    alice_meal = create_meal(client, name="Private Alice meal")
    register(second_client, email="blair@example.com", display_name="Blair")
    assert meals(second_client) == []
    meal_id = alice_meal["id"]
    assert second_client.patch(f"/api/meals/{meal_id}", json={"calories": 0}).status_code == 404
    assert second_client.delete(f"/api/meals/{meal_id}").status_code == 404
    assert second_client.get(f"/api/meals/{meal_id}/image").status_code == 404
    assert meals(client)[0]["calories"] == 520

    # A real stored image still must not be readable through another account.
    image_path = app.state.settings.upload_dir / "ownership-check.jpg"
    image_path.write_bytes(b"private-image-content")
    with app.state.db.session() as session:
        row = session.get(Meal, meal_id)
        row.image_path = image_path.name
        session.commit()
    assert second_client.get(f"/api/meals/{meal_id}/image").status_code == 404


@pytest.mark.parametrize("field", ["calories", "protein", "carbs", "fat"])
def test_negative_nutrition_is_rejected_on_create_and_edit(client, field):
    register(client)
    meal = create_meal(client)
    response = client.post("/api/meals", json={"name": "Invalid", "calories": 100, field: -0.1})
    assert response.status_code == 422
    assert client.patch(f"/api/meals/{meal['id']}", json={field: -0.1}).status_code == 422
    assert len(meals(client)) == 1
    assert meals(client)[0][field] == meal[field]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_nutrition_rejected_without_server_error(client, value):
    register(client)
    response = client.post(
        "/api/meals",
        content='{"name":"Invalid","calories":' + value + "}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert meals(client) == []


def test_meal_cannot_assign_another_owner_or_source(client, second_client):
    register(client)
    register(second_client, email="blair@example.com", display_name="Blair")
    other_id = current_user(second_client)["id"]
    for extra in ({"user_id": other_id}, {"source": "telegram"}, {"estimated": True}):
        response = client.post("/api/meals", json={"name": "Bad assignment", "calories": 100, **extra})
        assert response.status_code == 422
    assert meals(client) == []
    assert meals(second_client) == []


def test_csv_export_is_private_and_escapes_spreadsheet_formulas(client, second_client):
    register(client)
    dangerous_name = '=HYPERLINK("https://example.com","click")'
    create_meal(client, name=dangerous_name, notes="@SUM(1+1)")
    register(second_client, email="blair@example.com", display_name="Blair")
    create_meal(second_client, name="Blair's private meal")

    response = client.get("/api/export")
    assert response.status_code == 200, response.text
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert "Blair's private meal" not in response.text
    rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert len(rows) == 1
    values = list(rows[0].values())
    assert "'" + dangerous_name in values
    assert "'@SUM(1+1)" in values


def community(client):
    response = client.get("/api/community")
    assert response.status_code == 200, response.text
    return response.json()["users"]


def test_progress_and_meal_sharing_require_separate_opt_ins_and_revoke(client, second_client):
    register(client)
    owner_id = current_user(client)["id"]
    private_name = "Private meal only visible by explicit consent"
    create_meal(client, name=private_name, notes="Private meal notes")
    register(second_client, email="blair@example.com", display_name="Blair")
    assert owner_id not in {user["id"] for user in community(second_client)}

    assert client.patch("/api/me", json={"share_progress": True}).status_code == 200
    response = second_client.get("/api/community")
    shared = next(user for user in response.json()["users"] if user["id"] == owner_id)
    assert shared["display_name"] == "Alex"
    assert shared.get("meals", []) == []
    assert private_name not in response.text
    assert "alex@example.com" not in response.text
    assert "password_hash" not in response.text
    assert "telegram_chat_id" not in response.text

    assert client.patch("/api/me", json={"share_meals": True}).status_code == 200
    shared = next(user for user in community(second_client) if user["id"] == owner_id)
    assert any(meal["name"] == private_name for meal in shared["meals"])

    assert client.patch("/api/me", json={"share_meals": False}).status_code == 200
    response = second_client.get("/api/community")
    assert private_name not in response.text
    assert owner_id in {user["id"] for user in response.json()["users"]}

    assert client.patch("/api/me", json={"share_progress": False}).status_code == 200
    assert owner_id not in {user["id"] for user in community(second_client)}


def test_shared_meals_span_recent_days_and_carry_their_local_day(client, second_client):
    register(client)
    owner_id = current_user(client)["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    create_meal(client, name="Bowl from today")
    create_meal(client, name="Bowl from three days ago", logged_at=(now - timedelta(days=3)).isoformat())
    create_meal(client, name="Bowl from three weeks ago", logged_at=(now - timedelta(days=21)).isoformat())
    assert client.patch("/api/me", json={"share_progress": True, "share_meals": True}).status_code == 200
    register(second_client, email="blair@example.com", display_name="Blair")

    shared = next(user for user in community(second_client) if user["id"] == owner_id)
    names = [meal["name"] for meal in shared["meals"]]
    assert names == ["Bowl from today", "Bowl from three days ago"]
    assert shared["meals"][0]["date"] == shared["date"]
    assert shared["meals"][1]["date"] == (now - timedelta(days=3)).date().isoformat()
    assert all(meal["notes"] == "" and meal["source"] == "shared" for meal in shared["meals"])

    response = second_client.get("/api/community", params={"days": 30})
    assert response.status_code == 200, response.text
    assert response.json()["days"] == 30
    wider = next(user for user in response.json()["users"] if user["id"] == owner_id)
    assert "Bowl from three weeks ago" in {meal["name"] for meal in wider["meals"]}
    assert "One bowl" not in response.text

    assert client.patch("/api/me", json={"share_meals": False}).status_code == 200
    assert second_client.get("/api/community", params={"days": 30}).text.count("Bowl from") == 0


def test_meal_sharing_alone_does_not_publish_account(client, second_client):
    register(client)
    owner_id = current_user(client)["id"]
    create_meal(client)
    assert client.patch("/api/me", json={"share_meals": True}).status_code == 200
    register(second_client, email="blair@example.com", display_name="Blair")
    assert owner_id not in {user["id"] for user in community(second_client)}


def test_demo_sessions_have_isolated_meals_and_never_expose_real_users(client, second_client):
    register(client)
    real_id = current_user(client)["id"]
    client.patch("/api/me", json={"share_progress": True, "share_meals": True})
    create_meal(client, name="Real user's private demo-independent meal")

    response = second_client.post("/api/auth/demo")
    assert response.status_code in (200, 201), response.text
    first_demo = current_user(second_client)
    assert first_demo["is_demo"] is True
    first_meals = meals(second_client)
    assert first_meals
    first_peer_ids = {user["id"] for user in community(second_client)}
    assert real_id not in first_peer_ids
    assert first_demo["id"] not in {user["id"] for user in community(client)}
    assert first_peer_ids.isdisjoint({user["id"] for user in community(client)})

    second_client.delete(f"/api/meals/{first_meals[0]['id']}")
    second_client.post("/api/auth/logout")
    assert second_client.post("/api/auth/demo").status_code in (200, 201)
    assert current_user(second_client)["id"] != first_demo["id"]
    second_meals = meals(second_client)
    assert len(second_meals) == len(first_meals)
    assert {meal["id"] for meal in second_meals}.isdisjoint({meal["id"] for meal in first_meals})
    assert first_peer_ids.isdisjoint({user["id"] for user in community(second_client)})
    assert len(meals(client)) == 1


def test_demo_can_be_disabled_in_configuration(app_factory):
    _, client = app_factory(demo_enabled=False)
    assert client.post("/api/auth/demo").status_code in (403, 404)
    assert client.get("/api/me").status_code == 401


def test_dashboard_seven_and_thirty_day_windows(client):
    register(client)
    for date, calories in (
        ("2026-09-12", 100),
        ("2026-09-06", 200),
        ("2026-08-14", 300),
        ("2026-08-13", 400),
        ("2026-09-13", 500),
    ):
        create_meal(client, calories=calories, logged_at=f"{date}T12:00:00Z")
    for days, expected_sum, first_day in (
        (7, 300, "2026-09-06"),
        (30, 600, "2026-08-14"),
    ):
        response = client.get("/api/dashboard", params={"date": "2026-09-12", "days": days})
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["date"] == "2026-09-12"
        assert summary["totals"]["calories"] == 100
        assert summary["meal_count"] == 1
        assert len(summary["weekly"]) == days
        assert summary["weekly"][0]["date"] == first_day
        assert summary["weekly"][-1]["date"] == "2026-09-12"
        assert sum(point["calories"] for point in summary["weekly"]) == expected_sum


def test_dashboard_uses_user_timezone_across_daylight_saving_boundary(client):
    register(client, timezone="America/Los_Angeles")
    # March 8 is 23 hours long in Los Angeles in 2026.
    for stamp, calories in (
        ("2026-03-08T07:59:59Z", 100),
        ("2026-03-08T08:00:00Z", 250),
        ("2026-03-09T06:59:59Z", 300),
        ("2026-03-09T07:00:00Z", 400),
    ):
        create_meal(client, logged_at=stamp, calories=calories)
    naive = create_meal(client, logged_at="2026-03-08T12:00:00", calories=50)
    assert datetime.fromisoformat(naive["logged_at"].replace("Z", "+00:00")) == datetime(
        2026, 3, 8, 19, tzinfo=timezone.utc
    )

    response = client.get("/api/dashboard", params={"date": "2026-03-08", "days": 7})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["totals"]["calories"] == 600
    assert summary["meal_count"] == 3
    assert summary["weekly"][-2]["calories"] == 100
    assert sum(day["calories"] for day in summary["weekly"]) == 700


@pytest.mark.parametrize("endpoint", ["/api/dashboard", "/api/meals"])
@pytest.mark.parametrize("date", ["0001-01-01", "1969-12-31", "2101-01-01", "9999-12-31"])
def test_out_of_range_query_dates_return_validation_error(client, endpoint, date):
    register(client)
    response = client.get(endpoint, params={"date": date})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("date", ["1970-01-01", "2100-12-31"])
def test_supported_dashboard_date_boundaries_do_not_overflow(client, date):
    register(client)
    response = client.get("/api/dashboard", params={"date": date, "days": 90})
    assert response.status_code == 200, response.text
    assert len(response.json()["weekly"]) == 90
    assert response.json()["totals"]["calories"] == 0


@pytest.mark.parametrize(
    "stamp", ["0001-01-01T00:00:00Z", "1969-12-31T23:59:59Z", "2101-01-01T00:00:00Z", "9999-12-31T23:59:59Z"]
)
def test_out_of_range_meal_timestamps_rejected_before_saving_or_analysis(client, app, monkeypatch, stamp):
    register(client)
    existing = create_meal(client)
    analysis = AsyncMock()
    monkeypatch.setattr("app.vision.estimate_meal", analysis)

    created = client.post("/api/meals", json={"name": "Invalid date", "calories": 100, "logged_at": stamp})
    edited = client.patch(f"/api/meals/{existing['id']}", json={"logged_at": stamp})
    uploaded = client.post(
        "/api/meals/photo",
        files={"file": ("food.png", png_photo(), "image/png")},
        data={"logged_at": stamp},
    )
    for response in (created, edited, uploaded):
        assert response.status_code == 422, response.text
        assert isinstance(response.json()["detail"], str)
    analysis.assert_not_awaited()
    assert meals(client) == [existing]
    assert list(app.state.settings.upload_dir.iterdir()) == []


def telegram_start(code, *, update_id, telegram_id):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": telegram_id, "type": "private"},
            "from": {"id": telegram_id},
            "text": "/start " + code,
        },
    }


def test_telegram_configuration_is_required_before_linking(client):
    register(client)
    response = client.post("/api/telegram/link")
    assert response.status_code == 503
    assert current_user(client)["telegram_connected"] is False


def test_telegram_link_is_secret_expiring_and_single_use(app_factory):
    app, client = app_factory(
        telegram_bot_token="123456:fake-test-token",
        telegram_bot_username="nutrilens_test_bot",
    )
    register(client)
    user_id = current_user(client)["id"]
    response = client.post("/api/telegram/link")
    assert response.status_code == 200, response.text
    link = response.json()
    assert link["deep_link"] == f"https://t.me/nutrilens_test_bot?start={link['code']}"
    expires = datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
    assert datetime.now(timezone.utc) < expires <= datetime.now(timezone.utc) + timedelta(minutes=16)
    with app.state.db.session() as session:
        saved = session.get(LinkCode, token_hash(link["code"]))
        assert saved is not None
        assert saved.user_id == user_id
        assert saved.code_hash != link["code"]

    bot = TelegramBot(app.state.settings, app.state.db)
    bot._send = AsyncMock()
    event = telegram_start(link["code"], update_id=1001, telegram_id=42)
    asyncio.run(bot.handle_update(event))
    assert current_user(client)["telegram_connected"] is True
    with app.state.db.session() as session:
        assert session.get(LinkCode, token_hash(link["code"])) is None
        assert session.get(User, user_id).telegram_user_id == "42"
        assert session.get(BotUpdate, 1001) is not None

    # Telegram redelivery is a no-op, and a consumed code cannot reassign owner.
    delivered = bot._send.await_count
    asyncio.run(bot.handle_update(event))
    assert bot._send.await_count == delivered
    asyncio.run(bot.handle_update(telegram_start(link["code"], update_id=1002, telegram_id=99)))
    with app.state.db.session() as session:
        assert session.get(User, user_id).telegram_user_id == "42"
        assert session.scalar(select(User).where(User.telegram_user_id == "99")) is None


def test_telegram_expired_and_replaced_codes_cannot_link(app_factory):
    app, client = app_factory(
        telegram_bot_token="123456:fake-test-token",
        telegram_bot_username="nutrilens_test_bot",
    )
    register(client)
    first = client.post("/api/telegram/link").json()
    replacement_response = client.post("/api/telegram/link")
    assert replacement_response.status_code == 200, replacement_response.text
    replacement = replacement_response.json()
    assert replacement["code"] != first["code"]
    with app.state.db.session() as session:
        assert session.get(LinkCode, token_hash(first["code"])) is None
        code = session.get(LinkCode, token_hash(replacement["code"]))
        code.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        session.commit()

    bot = TelegramBot(app.state.settings, app.state.db)
    bot._send = AsyncMock()
    asyncio.run(bot.handle_update(telegram_start(first["code"], update_id=2001, telegram_id=42)))
    asyncio.run(bot.handle_update(telegram_start(replacement["code"], update_id=2002, telegram_id=42)))
    assert current_user(client)["telegram_connected"] is False


def png_photo():
    output = io.BytesIO()
    Image.new("RGB", (48, 32), "green").save(output, format="PNG")
    return output.getvalue()


def test_invalid_photo_and_missing_ai_never_save_a_meal(client, app):
    register(client)
    invalid = client.post(
        "/api/meals/photo", files={"file": ("fake.jpg", b"<script>alert('bad')</script>", "image/jpeg")}
    )
    assert invalid.status_code == 422, invalid.text
    response = client.post(
        "/api/meals/photo", files={"file": ("food.png", png_photo(), "image/png")}
    )
    assert response.status_code == 503, response.text
    assert "detail" in response.json()
    assert "configur" in response.json()["detail"].lower() or "api key" in response.json()["detail"].lower()
    assert meals(client) == []
    assert list(app.state.settings.upload_dir.iterdir()) == []


def test_upload_limit_rejects_large_file_before_analysis(app_factory):
    app, client = app_factory(max_upload_bytes=32)
    register(client)
    response = client.post(
        "/api/meals/photo", files={"file": ("too-large.png", png_photo(), "image/png")}
    )
    assert response.status_code == 413, response.text
    assert meals(client) == []
    assert list(app.state.settings.upload_dir.iterdir()) == []


def test_photo_estimate_saved_sanitized_shared_only_by_consent_and_correctable(
    client, second_client, app, monkeypatch
):
    register(client)
    estimate = {
        "name": "Vegetable rice bowl", "calories": 430, "protein": 12,
        "carbs": 68, "fat": 13, "confidence": "medium", "notes": "Assumes one bowl.",
    }
    analysis = AsyncMock(return_value=estimate)
    monkeypatch.setattr("app.vision.estimate_meal", analysis)
    response = client.post(
        "/api/meals/photo",
        files={"file": ("../../food.png", png_photo(), "image/png")},
        data={"notes": "Half portion", "meal_type": "lunch", "logged_at": "2026-09-12T12:00:00Z"},
    )
    assert response.status_code == 201, response.text
    meal = response.json()
    assert meal["estimated"] is True
    assert meal["confidence"] == "medium"
    assert meal["calories"] == 430
    assert meal["notes"] == "Half portion\nAssumes one bowl."
    assert meal["image_url"] == f"/api/meals/{meal['id']}/image"
    analysis.assert_awaited_once()
    stored = list(app.state.settings.upload_dir.iterdir())
    assert len(stored) == 1
    assert stored[0].suffix == ".jpg"
    assert stored[0].name != "food.png"
    owner_image = client.get(meal["image_url"])
    assert owner_image.status_code == 200
    assert owner_image.content.startswith(b"\xff\xd8")
    assert "no-store" in owner_image.headers["cache-control"]

    register(second_client, email="blair@example.com", display_name="Blair")
    assert second_client.get(meal["image_url"]).status_code == 404
    client.patch("/api/me", json={"share_progress": True})
    assert second_client.get(meal["image_url"]).status_code == 404
    client.patch("/api/me", json={"share_meals": True})
    assert second_client.get(meal["image_url"]).status_code == 200
    client.patch("/api/me", json={"share_meals": False})
    assert second_client.get(meal["image_url"]).status_code == 404
    client.patch("/api/me", json={"share_meals": True})
    client.patch("/api/me", json={"share_progress": False})
    assert second_client.get(meal["image_url"]).status_code == 404

    correction = client.patch(f"/api/meals/{meal['id']}", json={"calories": 300})
    assert correction.status_code == 200, correction.text
    assert correction.json()["estimated"] is False
    assert correction.json()["confidence"] is None
    assert client.delete(f"/api/meals/{meal['id']}").status_code == 200
    assert list(app.state.settings.upload_dir.iterdir()) == []
    assert client.get(meal["image_url"]).status_code == 404


def test_editing_notes_or_unchanged_numbers_preserves_estimate(client, monkeypatch):
    register(client)
    estimate = {"name": "Rice bowl", "calories": 420, "protein": 12, "carbs": 65,
                "fat": 11, "confidence": "medium", "notes": "One bowl."}
    monkeypatch.setattr("app.vision.estimate_meal", AsyncMock(return_value=estimate))
    meal = client.post("/api/meals/photo", files={"file": ("meal.png", png_photo(), "image/png")}).json()
    result = client.patch(f"/api/meals/{meal['id']}", json={"notes": "Lunch", "calories": 420})
    assert result.status_code == 200
    assert result.json()["estimated"] is True
    assert result.json()["confidence"] == "medium"
