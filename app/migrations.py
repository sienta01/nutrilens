"""Additive schema upgrades for existing installations; never replace user data."""
from sqlalchemy import inspect, text


# Fixed application-owned identifiers and DDL, never interpolated user input.
USER_COLUMNS = {
    "goal_mode": "VARCHAR(16) NOT NULL DEFAULT 'custom'",
    "maintenance_calories": "INTEGER NOT NULL DEFAULT 2000",
    "calorie_adjustment": "INTEGER NOT NULL DEFAULT 300",
    "fasting_enabled": "BOOLEAN NOT NULL DEFAULT false",
    "eating_window_start": "VARCHAR(5) NOT NULL DEFAULT '12:00'",
    "eating_window_end": "VARCHAR(5) NOT NULL DEFAULT '20:00'",
    "fasting_reminders": "BOOLEAN NOT NULL DEFAULT false",
    "remind_window_open": "BOOLEAN NOT NULL DEFAULT true",
    "remind_window_close": "BOOLEAN NOT NULL DEFAULT true",
    "fasting_reminder_minutes": "INTEGER NOT NULL DEFAULT 30",
    "fasting_updated_at": "TIMESTAMP NULL",
}


def upgrade(engine):
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
        for name, definition in USER_COLUMNS.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))
