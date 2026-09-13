"""Best-effort, durable, at-most-once Telegram reminder attempts."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ReminderDelivery, User
from app.planning import aware_utc, due_reminders

logger = logging.getLogger(__name__)


class ReminderWorker:
    def __init__(self, database, send):
        self.database = database
        self.send = send

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.error("Fasting reminder check failed (%s).", type(exc).__name__)
            await asyncio.sleep(30)

    async def tick(self, now: datetime | None = None):
        now = aware_utc(now)
        with self.database.session() as db:
            ids = list(db.scalars(select(User.id).where(
                User.fasting_enabled.is_(True), User.fasting_reminders.is_(True),
                User.telegram_chat_id.is_not(None), User.is_demo.is_(False),
            )))
        for user_id in ids:
            with self.database.session() as db:
                user = db.get(User, user_id)
                events = due_reminders(user, now) if user else []
            for kind, scheduled_at in events:
                with self.database.session() as db:
                    # Read again so a changed schedule or disconnected account is
                    # respected before claiming each notification.
                    user = db.get(User, user_id)
                    if not user or (kind, scheduled_at) not in due_reminders(user, now):
                        continue
                    if user.telegram_chat_id != user.telegram_user_id:
                        continue
                    delivery = ReminderDelivery(user_id=user.id, kind=kind,
                                                scheduled_at=scheduled_at.replace(tzinfo=None))
                    db.add(delivery)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        continue
                    delivery_id, chat_id = delivery.id, user.telegram_chat_id
                    messages = {
                        "window_open": "Your eating window is open. Your scheduled fast has ended.",
                        "window_close": "Your eating window is closed. Your scheduled fast starts now.",
                        "fasting_soon": f"Fasting reminder: your eating window closes in {user.fasting_reminder_minutes} minutes.",
                    }
                    message = (f"{messages[kind]}\n"
                               f"Daily eating window: {user.eating_window_start}–{user.eating_window_end} ({user.timezone}).\n"
                               "Adjust your schedule or turn reminders off in NutriLens Settings. Use /fasting for current status.")
                try:
                    await self.send(chat_id, message)
                except Exception as exc:
                    # A timeout can mean Telegram accepted the message. Do not
                    # retry an ambiguous send and risk duplicate notifications.
                    status = "failed"
                    logger.warning("Fasting reminder delivery failed (%s).", type(exc).__name__)
                else:
                    status = "sent"
                with self.database.session() as db:
                    delivery = db.get(ReminderDelivery, delivery_id)
                    if delivery:
                        delivery.status = status
                        db.commit()
