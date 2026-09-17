from datetime import date as Date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Meal, User, utcnow
from app.planning import fasting_status, goal_plan

NUTRIENTS = ("calories", "protein", "carbs", "fat")


def iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def user_dict(user: User) -> dict:
    return {
        "id": user.id, "email": user.email, "display_name": user.display_name,
        "daily_calorie_goal": user.daily_calorie_goal, "protein_goal": user.protein_goal,
        "carbs_goal": user.carbs_goal, "fat_goal": user.fat_goal, "timezone": user.timezone,
        "share_progress": user.share_progress, "share_meals": user.share_meals,
        "telegram_connected": user.telegram_user_id is not None,
        "is_demo": user.is_demo, "created_at": iso(user.created_at),
        **{key: getattr(user, key) for key in (
            "goal_mode", "maintenance_calories", "calorie_adjustment", "fasting_enabled",
            "eating_window_start", "eating_window_end", "fasting_reminders",
            "remind_window_open", "remind_window_close", "fasting_reminder_minutes",
        )},
    }


def meal_dict(meal: Meal, *, shared: bool = False) -> dict:
    return {
        "id": meal.id, "name": meal.name,
        **{key: getattr(meal, key) for key in NUTRIENTS},
        "meal_type": meal.meal_type, "logged_at": iso(meal.logged_at),
        # Personal notes and source metadata never belong to a shared profile.
        "notes": "" if shared else meal.notes,
        "source": "shared" if shared else meal.source,
        "estimated": meal.estimated, "confidence": meal.confidence,
        "image_url": f"/api/meals/{meal.id}/image" if meal.image_path else None,
    }


def local_today(user: User) -> Date:
    return datetime.now(ZoneInfo(user.timezone)).date()


def to_utc(value: datetime | None, user: User) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(user.timezone))
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def day_bounds(date: Date, zone: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(zone)
    start = datetime.combine(date, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date + timedelta(days=1), time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def day_meals(db: Session, user: User, date: Date) -> list[Meal]:
    start, end = day_bounds(date, user.timezone)
    return list(db.scalars(select(Meal).where(
        Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end
    ).order_by(Meal.logged_at.desc(), Meal.id)))


def logging_streak(db: Session, user: User, today: Date) -> int:
    # Streaks measure consistent logging, never reward eating less.
    start, _ = day_bounds(today - timedelta(days=3650), user.timezone)
    _, end = day_bounds(today, user.timezone)
    times = db.scalars(select(Meal.logged_at).where(
        Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end
    ))
    zone = ZoneInfo(user.timezone)
    dates = {stamp.replace(tzinfo=timezone.utc).astimezone(zone).date() for stamp in times}
    cursor = today if today in dates else today - timedelta(days=1)
    streak = 0
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def day_summary(db: Session, user: User, date: Date | None = None, days: int = 7) -> dict:
    selected = date or local_today(user)
    first = selected - timedelta(days=days - 1)
    start, _ = day_bounds(first, user.timezone)
    _, end = day_bounds(selected, user.timezone)
    rows = list(db.scalars(select(Meal).where(
        Meal.user_id == user.id, Meal.logged_at >= start, Meal.logged_at < end
    ).order_by(Meal.logged_at.desc(), Meal.id)))
    weekly = {
        (first + timedelta(days=i)).isoformat(): {
            "date": (first + timedelta(days=i)).isoformat(),
            **dict.fromkeys(NUTRIENTS, 0.0), "meal_count": 0,
        } for i in range(days)
    }
    zone = ZoneInfo(user.timezone)
    selected_meals = []
    for meal in rows:
        day = meal.logged_at.replace(tzinfo=timezone.utc).astimezone(zone).date().isoformat()
        bucket = weekly[day]
        bucket["meal_count"] += 1
        for key in NUTRIENTS:
            bucket[key] = round(bucket[key] + getattr(meal, key), 2)
        if day == selected.isoformat():
            selected_meals.append(meal_dict(meal))
    totals = weekly[selected.isoformat()]
    return {
        "date": selected.isoformat(), "totals": {key: totals[key] for key in NUTRIENTS},
        "goals": {"calories": user.daily_calorie_goal, "protein": user.protein_goal,
                  "carbs": user.carbs_goal, "fat": user.fat_goal},
        "meal_count": totals["meal_count"], "streak": logging_streak(db, user, selected),
        "weekly": list(weekly.values()), "meals": selected_meals,
        "plan": goal_plan(user), "fasting": fasting_status(user),
    }


def same_community(viewer: User, owner: User) -> bool:
    if viewer.is_demo or owner.is_demo:
        return viewer.is_demo and owner.is_demo and viewer.demo_group == owner.demo_group
    return True


def can_view_image(viewer: User, owner: User) -> bool:
    return viewer.id == owner.id or (
        same_community(viewer, owner) and owner.share_progress and owner.share_meals
    )


def image_file(settings: Settings, image_path: str) -> Path:
    root = settings.upload_dir.resolve()
    path = (root / image_path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Invalid image path")
    return path


def delete_meal(db: Session, meal: Meal, settings: Settings):
    path = image_file(settings, meal.image_path) if meal.image_path else None
    db.delete(meal)
    db.commit()
    if path:
        path.unlink(missing_ok=True)


async def add_photo_meal(
    db: Session, user: User, data: bytes, notes: str, meal_type: str,
    logged_at: datetime | None, settings: Settings, source: str = "web",
    telegram_update_id: int | None = None,
) -> Meal:
    from app import vision

    if len(data) > settings.max_upload_bytes:
        raise vision.VisionError("Photo must be 10 MB or smaller.", 413)
    normalized = vision.normalize_image(data)
    result = await vision.estimate_meal(normalized, notes, settings)
    filename = f"{uuid4().hex}.jpg"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = image_file(settings, filename)
    path.write_bytes(normalized)
    meal = Meal(
        user_id=user.id, name=result["name"],
        **{key: result[key] for key in NUTRIENTS},
        meal_type=meal_type, logged_at=to_utc(logged_at, user),
        notes=(notes + ("\n" if notes else "") + result.get("notes", ""))[:2000],
        source=source, estimated=True, confidence=result["confidence"],
        ai_provider=result.get("ai_provider"), ai_model=result.get("ai_model"),
        image_path=filename, telegram_update_id=telegram_update_id,
    )
    try:
        db.add(meal)
        db.commit()
        db.refresh(meal)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return meal


async def add_text_meal(
    db: Session, user: User, description: str, logged_at: datetime,
    meal_type: str, settings: Settings, telegram_update_id: int,
) -> Meal:
    from pydantic import ValidationError
    from app import vision
    from app.schemas import MealCreate

    if not description.strip() or len(description) > 2000:
        raise vision.VisionError("Describe the food and portion size in 1–2,000 characters.")
    if "|" in description:
        parts = [part.strip() for part in description.split("|")]
        try:
            if len(parts) not in {2, 5}:
                raise ValueError()
            values = dict(zip(NUTRIENTS, parts[1:]))
            parsed = MealCreate(name=parts[0], **values)
        except (ValidationError, ValueError):
            raise vision.VisionError(
                "Use /log Meal name | calories OR /log Meal name | calories | protein | carbs | fat. "
                "Enter numbers only (kcal, then grams). Example: /log Chicken rice | 650 | 40 | 75 | 20."
            ) from None
        meal = Meal(user_id=user.id, name=parsed.name,
                    **{key: getattr(parsed, key) for key in NUTRIENTS},
                    notes="Values supplied by you." + (" Macros not supplied; recorded as 0. Edit them on your dashboard." if len(parts) == 2 else ""),
                    estimated=False)
    else:
        result = await vision.estimate_text_meal(description, settings)
        meal = Meal(user_id=user.id, name=result["name"],
                    **{key: result[key] for key in NUTRIENTS},
                    notes=(description + "\n" + result["notes"])[:2000],
                    estimated=True, confidence=result["confidence"],
                    ai_provider=result.get("ai_provider"), ai_model=result.get("ai_model"))
    meal.logged_at = to_utc(logged_at, user)
    meal.meal_type = meal_type
    meal.source = "telegram"
    meal.telegram_update_id = telegram_update_id
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal
