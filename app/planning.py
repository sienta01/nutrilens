"""User-selected calorie targets and daily eating windows, with no dietary prescription."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import User

GOAL_LABELS = {"custom": "Custom target", "maintain": "Maintenance", "bulk": "Bulking", "deficit": "Calorie deficit"}
FASTING_FIELDS = {
    "fasting_enabled", "eating_window_start", "eating_window_end", "fasting_reminders",
    "remind_window_open", "remind_window_close", "fasting_reminder_minutes", "timezone",
}


def apply_plan_settings(user: User, changes: dict, now: datetime):
    """Validate the merged settings before mutating the persisted account."""
    mode = changes.get("goal_mode", user.goal_mode)
    if "daily_calorie_goal" in changes and "goal_mode" not in changes:
        mode = "custom"
    maintenance = changes.get("maintenance_calories", user.maintenance_calories)
    adjustment = changes.get("calorie_adjustment", user.calorie_adjustment)
    target = changes.get("daily_calorie_goal", user.daily_calorie_goal)
    if mode != "custom":
        target = maintenance + (adjustment if mode == "bulk" else -adjustment if mode == "deficit" else 0)
    if not 1 <= target <= 20000:
        raise ValueError("The calculated calorie target must be between 1 and 20,000. Adjust your maintenance or calorie offset.")
    start = changes.get("eating_window_start", user.eating_window_start)
    end = changes.get("eating_window_end", user.eating_window_end)
    if start == end:
        raise ValueError("Eating-window start and end must be different.")
    minutes = changes.get("fasting_reminder_minutes", user.fasting_reminder_minutes)
    if minutes and minutes >= eating_minutes(start, end):
        raise ValueError("The fasting heads-up must be shorter than your eating window. Set it to 0 to disable it.")
    if any(key in changes and changes[key] != getattr(user, key) for key in FASTING_FIELDS):
        user.fasting_updated_at = now
    for key, value in changes.items():
        setattr(user, key, value)
    user.goal_mode = mode
    user.daily_calorie_goal = target


def goal_plan(user: User) -> dict:
    return {"mode": user.goal_mode, "label": GOAL_LABELS[user.goal_mode],
            "maintenance_calories": user.maintenance_calories, "calorie_adjustment": user.calorie_adjustment,
            "target": user.daily_calorie_goal}


def eating_minutes(start: str, end: str) -> int:
    def minutes(value):
        hour, minute = map(int, value.split(":"))
        return hour * 60 + minute
    return (minutes(end) - minutes(start)) % 1440


def aware_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def scheduled_windows(user: User, now: datetime):
    zone = ZoneInfo(user.timezone)
    today = now.astimezone(zone).date()

    def boundary(day, value):
        hour, minute = map(int, value.split(":"))
        # First occurrence in a fall-back fold; nonexistent spring times move
        # forward by the offset change when converted back from UTC.
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0).astimezone(timezone.utc)

    for offset in range(-2, 3):
        day = today + timedelta(days=offset)
        end_day = day + timedelta(days=int(user.eating_window_end < user.eating_window_start))
        start, end = boundary(day, user.eating_window_start), boundary(end_day, user.eating_window_end)
        if end > start:
            yield start, end


def fasting_status(user: User, now: datetime | None = None) -> dict:
    now = aware_utc(now)
    hours = eating_minutes(user.eating_window_start, user.eating_window_end) / 60
    result = {"enabled": user.fasting_enabled, "timezone": user.timezone,
              "window_start": user.eating_window_start, "window_end": user.eating_window_end,
              "eating_hours": hours, "fasting_hours": 24 - hours,
              "reminders_enabled": user.fasting_reminders,
              "telegram_connected": user.telegram_user_id is not None}
    if not user.fasting_enabled:
        return {**result, "phase": "disabled", "next_transition_at": None, "seconds_until_transition": 0}
    windows = list(scheduled_windows(user, now))
    current = next(((start, end) for start, end in windows if start <= now < end), None)
    transition = current[1] if current else next(start for start, _ in windows if start > now)
    return {**result, "phase": "eating" if current else "fasting",
            "next_transition_at": transition.isoformat().replace("+00:00", "Z"),
            "seconds_until_transition": max(0, int((transition - now).total_seconds()))}


def due_reminders(user: User, now: datetime | None = None) -> list[tuple[str, datetime]]:
    now = aware_utc(now)
    if not (user.fasting_enabled and user.fasting_reminders and user.telegram_chat_id
            and user.telegram_user_id and not user.is_demo):
        return []
    cutoff = now - timedelta(minutes=5)
    changed = aware_utc(user.fasting_updated_at or user.created_at)
    events = []
    for start, end in scheduled_windows(user, now):
        candidates = []
        if user.remind_window_open:
            candidates.append(("window_open", start))
        if user.remind_window_close:
            candidates.append(("window_close", end))
        if user.fasting_reminder_minutes:
            candidates.append(("fasting_soon", end - timedelta(minutes=user.fasting_reminder_minutes)))
        events.extend((kind, stamp) for kind, stamp in candidates if cutoff < stamp <= now and stamp >= changed)
    return sorted(events, key=lambda event: event[1])
