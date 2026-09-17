from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(60))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    daily_calorie_goal: Mapped[int] = mapped_column(Integer, default=2000)
    protein_goal: Mapped[int] = mapped_column(Integer, default=120)
    carbs_goal: Mapped[int] = mapped_column(Integer, default=250)
    fat_goal: Mapped[int] = mapped_column(Integer, default=65)
    goal_mode: Mapped[str] = mapped_column(String(16), default="custom")
    maintenance_calories: Mapped[int] = mapped_column(Integer, default=2000)
    calorie_adjustment: Mapped[int] = mapped_column(Integer, default=300)
    fasting_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    eating_window_start: Mapped[str] = mapped_column(String(5), default="12:00")
    eating_window_end: Mapped[str] = mapped_column(String(5), default="20:00")
    fasting_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    remind_window_open: Mapped[bool] = mapped_column(Boolean, default=True)
    remind_window_close: Mapped[bool] = mapped_column(Boolean, default=True)
    fasting_reminder_minutes: Mapped[int] = mapped_column(Integer, default=30)
    fasting_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    share_progress: Mapped[bool] = mapped_column(Boolean, default=False)
    share_meals: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_group: Mapped[str | None] = mapped_column(String(36), index=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = (Index("ix_meals_user_logged", "user_id", "logged_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    calories: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float, default=0)
    carbs: Mapped[float] = mapped_column(Float, default=0)
    fat: Mapped[float] = mapped_column(Float, default=0)
    meal_type: Mapped[str] = mapped_column(String(20), default="snack")
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(10))
    # Which chain line actually answered; NULL for manual entries and pre-upgrade rows.
    ai_provider: Mapped[str | None] = mapped_column(String(20))
    ai_model: Mapped[str | None] = mapped_column(String(100))
    image_path: Mapped[str | None] = mapped_column(String(200))
    telegram_update_id: Mapped[int | None] = mapped_column(Integer, unique=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class LinkCode(Base):
    __tablename__ = "telegram_links"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class BotUpdate(Base):
    __tablename__ = "bot_updates"
    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "kind", "scheduled_at", name="uq_reminder_event"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="sending")
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
