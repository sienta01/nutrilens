"""Calorie plans, local-time schedules, durable reminders, and existing-data upgrades."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.db import Database
from app.models import Meal, ReminderDelivery, User
from app.planning import due_reminders, fasting_status
from app.reminders import ReminderWorker
from app.telegram_bot import TelegramError


def register(client, email="planner@example.com"):
    response = client.post("/api/auth/register", json={
        "email": email, "password": "test-password-12345", "display_name": "Planner", "timezone": "Asia/Makassar",
    })
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize("mode,target", [("bulk", 2700), ("deficit", 2100), ("maintain", 2400), ("custom", 1850)])
def test_goal_calculation_drives_dashboard(client, mode, target):
    register(client)
    response = client.patch("/api/me", json={"goal_mode": mode, "maintenance_calories": 2400,
                                           "calorie_adjustment": 300, "daily_calorie_goal": 1850})
    assert response.status_code == 200
    assert response.json()["daily_calorie_goal"] == target
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["goals"]["calories"] == target
    assert dashboard["plan"]["mode"] == mode
    assert dashboard["plan"]["target"] == target


def test_goal_partial_update_and_legacy_direct_target(client):
    register(client)
    client.patch("/api/me", json={"goal_mode": "bulk", "maintenance_calories": 2200, "calorie_adjustment": 250})
    assert client.patch("/api/me", json={"calorie_adjustment": 400}).json()["daily_calorie_goal"] == 2600
    assert client.patch("/api/me", json={"display_name": "Changed"}).json()["goal_mode"] == "bulk"
    result = client.patch("/api/me", json={"daily_calorie_goal": 1900}).json()
    assert result["goal_mode"] == "custom"
    assert result["daily_calorie_goal"] == 1900


@pytest.mark.parametrize("changes", [
    {"goal_mode": "deficit", "maintenance_calories": 100, "calorie_adjustment": 300},
    {"goal_mode": "bulk", "maintenance_calories": 20000, "calorie_adjustment": 1},
    {"goal_mode": "unknown"}, {"goal_mode": None}, {"calorie_adjustment": -1},
    {"eating_window_start": "24:00"}, {"eating_window_end": "12:00"},
    {"eating_window_start": "9:00"}, {"fasting_enabled": None},
    {"fasting_reminder_minutes": 121},
    {"eating_window_start": "19:45", "eating_window_end": "20:00", "fasting_reminder_minutes": 30},
])
def test_invalid_plan_settings_are_atomic(client, changes):
    original = register(client)
    assert client.patch("/api/me", json={"display_name": "Should not save", **changes}).status_code == 422
    assert client.get("/api/me").json() == original


def test_independent_accounts_and_private_fasting_preferences(client, second_client):
    register(client)
    other = register(second_client, "second@example.com")
    response = client.patch("/api/me", json={"goal_mode": "deficit", "maintenance_calories": 2400,
        "calorie_adjustment": 400, "fasting_enabled": True, "fasting_reminders": True,
        "eating_window_start": "22:00", "eating_window_end": "06:00", "share_progress": True})
    assert response.status_code == 200
    assert second_client.get("/api/me").json() == other
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["fasting"]["eating_hours"] == 8
    assert dashboard["fasting"]["fasting_hours"] == 16
    shared = second_client.get("/api/community").json()["users"][0]
    assert "fasting" not in shared and "eating_window_start" not in shared and "goal_mode" not in shared


def scheduled_user(**overrides):
    return SimpleNamespace(timezone="Asia/Makassar", **{
        "fasting_enabled": True, "eating_window_start": "12:00", "eating_window_end": "20:00",
        "fasting_reminders": True, "remind_window_open": True, "remind_window_close": True,
        "fasting_reminder_minutes": 30, "telegram_user_id": "42", "telegram_chat_id": "42",
        "is_demo": False, "created_at": datetime(2020, 1, 1), "fasting_updated_at": None, **overrides,
    })


@pytest.mark.parametrize("stamp,phase,next_stamp", [
    ("2026-09-12T03:59:59+00:00", "fasting", "2026-09-12T04:00:00Z"),
    ("2026-09-12T04:00:00+00:00", "eating", "2026-09-12T12:00:00Z"),
    ("2026-09-12T11:59:59+00:00", "eating", "2026-09-12T12:00:00Z"),
    ("2026-09-12T12:00:00+00:00", "fasting", "2026-09-13T04:00:00Z"),
])
def test_local_window_boundaries(stamp, phase, next_stamp):
    result = fasting_status(scheduled_user(), datetime.fromisoformat(stamp))
    assert result["phase"] == phase
    assert result["next_transition_at"] == next_stamp
    assert result["seconds_until_transition"] > 0


def test_overnight_window_uses_previous_days_opening():
    user = scheduled_user(eating_window_start="22:00", eating_window_end="06:00")
    now = datetime(2026, 9, 12, 18, tzinfo=timezone.utc)  # 02:00 the following local day
    result = fasting_status(user, now)
    assert result["phase"] == "eating"
    assert result["next_transition_at"] == "2026-09-12T22:00:00Z"
    assert due_reminders(user, now.replace(hour=22))[0][0] == "window_close"


def test_dst_elapsed_time_and_missing_and_repeated_local_times():
    user = scheduled_user(eating_window_start="01:00", eating_window_end="04:00")
    user.timezone = "America/New_York"
    spring = fasting_status(user, datetime(2026, 3, 8, 6, tzinfo=timezone.utc))
    assert spring["seconds_until_transition"] == 2 * 3600
    autumn = fasting_status(user, datetime(2026, 11, 1, 5, tzinfo=timezone.utc))
    assert autumn["seconds_until_transition"] == 4 * 3600
    user.eating_window_start = "02:30"
    missing = fasting_status(user, datetime(2026, 3, 8, 7, tzinfo=timezone.utc))
    assert missing["next_transition_at"] == "2026-03-08T07:30:00Z"
    user.eating_window_start = "01:30"
    first_fold = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert due_reminders(user, first_fold)[0][0] == "window_open"
    assert due_reminders(user, first_fold + timedelta(hours=1)) == []


@pytest.mark.parametrize("changes", [
    {"fasting_enabled": False}, {"fasting_reminders": False}, {"telegram_user_id": None},
    {"telegram_chat_id": None}, {"is_demo": True}, {"remind_window_open": False},
    {"fasting_updated_at": datetime(2026, 9, 12, 4, 0, 1)},
])
def test_reminders_respect_opt_in_connection_and_changed_schedule(changes):
    assert due_reminders(scheduled_user(**changes), datetime(2026, 9, 12, 4, 1, tzinfo=timezone.utc)) == []


def test_all_reminder_events_and_offline_grace():
    user = scheduled_user()
    for hour, minute, kind in [(4, 0, "window_open"), (11, 30, "fasting_soon"), (12, 0, "window_close")]:
        now = datetime(2026, 9, 12, hour, minute, tzinfo=timezone.utc)
        assert due_reminders(user, now) == [(kind, now)]
        assert due_reminders(user, now + timedelta(minutes=4, seconds=59)) == [(kind, now)]
        assert due_reminders(user, now + timedelta(minutes=5)) == []
    assert due_reminders(scheduled_user(fasting_reminder_minutes=0), datetime(2026, 9, 12, 11, 30, tzinfo=timezone.utc)) == []


async def test_reminders_are_durable_per_user_and_failures_do_not_block_others(app):
    database = app.state.db
    with database.session() as db:
        for chat_id in ["42", "43"]:
            db.add(User(email=f"{chat_id}@example.com", password_hash="unused", display_name=chat_id,
                timezone="Asia/Makassar", telegram_user_id=chat_id, telegram_chat_id=chat_id,
                fasting_enabled=True, fasting_reminders=True, created_at=datetime(2020, 1, 1)))
        db.commit()
    send = AsyncMock(side_effect=[TelegramError(403), None])
    now = datetime(2026, 9, 12, 4, tzinfo=timezone.utc)
    await ReminderWorker(database, send).tick(now)
    assert send.await_count == 2
    await ReminderWorker(database, send).tick(now + timedelta(minutes=1))
    assert send.await_count == 2  # Even ambiguous failed sends are not retried.
    with database.session() as db:
        records = list(db.scalars(select(ReminderDelivery)))
        assert sorted(record.status for record in records) == ["failed", "sent"]
        assert len({record.user_id for record in records}) == 2
    send.side_effect = None
    await ReminderWorker(database, send).tick(now + timedelta(days=1))
    assert send.await_count == 4


async def test_disabled_disconnected_demo_and_mismatched_chats_never_receive_reminders(app):
    with app.state.db.session() as db:
        for i, changes in enumerate([{"fasting_enabled": False}, {"fasting_reminders": False},
            {"telegram_chat_id": None}, {"is_demo": True}, {"telegram_chat_id": "999"}]):
            db.add(User(**{"email": f"{i}@example.com", "display_name": "Test", "password_hash": "unused",
                "timezone": "Asia/Makassar", "telegram_user_id": str(i), "telegram_chat_id": str(i),
                "fasting_enabled": True, "fasting_reminders": True, "created_at": datetime(2020, 1, 1), **changes}))
        db.commit()
    send = AsyncMock()
    await ReminderWorker(app.state.db, send).tick(datetime(2026, 9, 12, 4, tzinfo=timezone.utc))
    send.assert_not_called()


def test_migration_preserves_existing_account_meals_and_is_repeatable(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE users (
            id VARCHAR(36) PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(256) NOT NULL,
            display_name VARCHAR(60) NOT NULL, timezone VARCHAR(80) NOT NULL, daily_calorie_goal INTEGER NOT NULL,
            protein_goal INTEGER NOT NULL, carbs_goal INTEGER NOT NULL, fat_goal INTEGER NOT NULL,
            share_progress BOOLEAN NOT NULL, share_meals BOOLEAN NOT NULL, is_demo BOOLEAN NOT NULL,
            demo_group VARCHAR(36), telegram_user_id VARCHAR(32) UNIQUE, telegram_chat_id VARCHAR(32), created_at DATETIME NOT NULL
        )"""))
        conn.execute(text("""INSERT INTO users VALUES (
            'legacy', 'legacy@example.com', 'preserve-hash', 'Existing', 'Asia/Makassar', 2350,
            125, 260, 70, 1, 0, 0, NULL, '42', '42', '2026-01-01 00:00:00'
        )"""))
        Meal.__table__.create(conn)
        conn.execute(Meal.__table__.insert().values(id="existing-meal", user_id="legacy", name="Rice", calories=400))
    engine.dispose()
    database = Database(url)
    try:
        database.initialize()
        database.initialize()
        with database.session() as db:
            user = db.get(User, "legacy")
            assert user.password_hash == "preserve-hash" and user.daily_calorie_goal == 2350
            assert user.telegram_user_id == "42" and user.share_progress
            assert user.goal_mode == "custom" and not user.fasting_enabled and not user.fasting_reminders
            assert user.eating_window_start == "12:00"
            assert db.get(Meal, "existing-meal").calories == 400
        assert "reminder_deliveries" in inspect(database.engine).get_table_names()
    finally:
        database.close()
