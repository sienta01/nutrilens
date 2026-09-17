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

MEAL_COLUMNS = {
    "ai_provider": "VARCHAR(20) NULL",
    "ai_model": "VARCHAR(100) NULL",
}

# Table -> additive columns. Same rules as before: fixed identifiers, no backfill,
# nothing destructive, safe to re-run on every startup.
TABLE_COLUMNS = {"users": USER_COLUMNS, "meals": MEAL_COLUMNS}


def upgrade(engine):
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, wanted in TABLE_COLUMNS.items():
            columns = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in wanted.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
