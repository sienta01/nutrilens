"""Telegram long polling, account linking, and private photo logging.

Run one polling worker per bot token. Durable update IDs and unique meal update
IDs make redelivered Telegram messages safe across application restarts.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.models import BotUpdate, LinkCode, Meal, User
from app.security import RateLimiter, token_hash
from app.vision import VisionError

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramError(Exception):
    """Sanitized Telegram error: raw URLs contain the bot token."""

    def __init__(self, code: int = 503, retry_after: int = 0):
        self.code = code
        self.retry_after = max(0, min(retry_after, 60))
        super().__init__(f"Telegram request failed (status {code}).")


class _RedactToken(logging.Filter):
    def __init__(self, token: str):
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if self.token:
            record.msg = record.getMessage().replace(self.token, "[REDACTED]")
            record.args = ()
        return True


class TelegramBot:
    def __init__(self, settings: Settings, database: Any):
        self.settings = settings
        self.database = database
        self._client: httpx.AsyncClient | None = None
        self._photo_limiter = RateLimiter()
        # httpx's ordinary INFO request log includes the token in Telegram URLs.
        logging.getLogger("httpx").addFilter(_RedactToken(settings.telegram_bot_token))

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(40, connect=10), follow_redirects=False)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _api(self, method: str, payload: dict | None = None) -> Any:
        try:
            response = await self._get_client().post(
                f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{method}",
                json=payload or {},
            )
            body = response.json()
            if not isinstance(body, dict):
                raise TelegramError()
            if response.status_code != 200 or not body.get("ok"):
                retry = body.get("parameters", {}).get("retry_after", 0)
                raise TelegramError(int(body.get("error_code", response.status_code)), int(retry))
            return body.get("result")
        except TelegramError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise TelegramError() from None

    async def _send(self, chat_id: str, text: str) -> None:
        await self._api("sendMessage", {
            "chat_id": chat_id,
            "text": text[:4000],
            "link_preview_options": {"is_disabled": True},
        })

    def _mark(self, update_id: int) -> None:
        with self.database.session() as db:
            if db.get(BotUpdate, update_id) is None:
                db.add(BotUpdate(update_id=update_id))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()

    def _processed(self, update_id: int) -> bool:
        with self.database.session() as db:
            return db.get(BotUpdate, update_id) is not None

    async def run(self) -> None:
        if not self.settings.telegram_bot_token:
            logger.warning("Telegram polling is enabled but TELEGRAM_BOT_TOKEN is missing.")
            return
        offset: int | None = None
        backoff = 1
        from app.reminders import ReminderWorker
        reminders = asyncio.create_task(ReminderWorker(self.database, self._send).run(), name="fasting-reminders")
        try:
            # Start at Telegram's oldest unconfirmed message. Reconstructing an
            # offset from MAX(update_id) is unsafe after Telegram resets IDs
            # following a week of inactivity. BotUpdate is the durable checkpoint.
            while True:
                try:
                    params: dict[str, Any] = {"timeout": 25, "limit": 25, "allowed_updates": ["message"]}
                    if offset is not None:
                        params["offset"] = offset
                    updates = await self._api("getUpdates", params)
                    if not isinstance(updates, list):
                        raise TelegramError()
                    for event in updates:
                        event_id = event.get("update_id")
                        if type(event_id) is not int:
                            continue
                        try:
                            await self.handle_update(event)
                        except TelegramError as exc:
                            if exc.code in {400, 403}:
                                # An inaccessible chat must not stall everyone.
                                logger.warning("Telegram could not deliver a response (status %s).", exc.code)
                                self._mark(event_id)
                            else:
                                raise
                        offset = event_id + 1
                    backoff = 1
                except asyncio.CancelledError:
                    raise
                except TelegramError as exc:
                    if exc.code == 409:
                        logger.error("Telegram polling conflict: stop other workers or remove the existing webhook explicitly. The app has not changed the webhook.")
                        return
                    if exc.code in {401, 404}:
                        logger.error("Telegram authentication failed. Check TELEGRAM_BOT_TOKEN and restart the server.")
                        return
                    logger.warning("Telegram is temporarily unavailable (status %s); retrying.", exc.code)
                    await asyncio.sleep(max(backoff, exc.retry_after))
                    backoff = min(backoff * 2, 30)
                except Exception as exc:
                    # Never log exception text or traceback: network exceptions
                    # can contain tokens, private photos, or private message text.
                    logger.error("Telegram update processing failed (%s); retrying.", type(exc).__name__)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        finally:
            reminders.cancel()
            with suppress(asyncio.CancelledError):
                await reminders
            await self.aclose()

    async def handle_update(self, event: dict) -> None:
        update_id = event.get("update_id")
        if type(update_id) is not int or self._processed(update_id):
            return
        message = event.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        # Never disclose account information or process photos in group chats.
        if chat.get("type") != "private" or not sender.get("id") or str(chat.get("id")) != str(sender["id"]):
            self._mark(update_id)
            return
        chat_id, telegram_id = str(chat["id"]), str(sender["id"])
        text = (message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if command == "/start" and len(text.split(maxsplit=1)) == 2:
            await self._link(text.split(maxsplit=1)[1].strip(), telegram_id, chat_id, update_id)
            return
        if command in {"/start", "/help"}:
            await self._send(chat_id, (
                "Welcome to NutriLens!\n\n"
                f"1. Create or sign in to your account at {self.settings.app_url}.\n"
                "2. Open Settings → Connect Telegram and follow the one-time link.\n"
                "3. Send a food photo with a portion caption, or describe your meal: '2 eggs, 2 slices of toast and a banana'.\n\n"
                f"{self.settings.photo_privacy_notice} Review or correct meals on your dashboard.\n\n"
                "Exact values (no AI): /log Chicken rice | 650 | 40 | 75 | 20\n"
                "Order: name | kcal | protein | carbs | fat (grams). You can also use /log Meal name | kcal; omitted macros are recorded as 0.\n\n"
                "/today — today's calories and macros\n"
                "/goal — your calorie plan\n"
                "/fasting — current eating window and reminder status\n"
                "/undo — remove your latest meal sent through Telegram\n"
                "/help — show these instructions"
            ))
            self._mark(update_id)
            return
        with self.database.session() as db:
            user = db.scalar(select(User).where(User.telegram_user_id == telegram_id))
            if user is None:
                await self._send(chat_id, f"Connect your account first: sign in at {self.settings.app_url}, open Settings, and choose Connect Telegram.")
                self._mark(update_id)
                return
            if command == "/today":
                from app.services import day_summary
                summary = day_summary(db, user)
                totals, goals = summary["totals"], summary["goals"]
                await self._send(chat_id, (
                    f"Today · {summary['date']}\n"
                    f"{totals['calories']:,.0f} / {goals['calories']:,.0f} kcal\n"
                    f"Protein {totals['protein']:.0f} g · Carbs {totals['carbs']:.0f} g · Fat {totals['fat']:.0f} g\n"
                    f"{summary['meal_count']} meals logged\n\n{self.settings.app_url}"
                ))
            elif command == "/goal":
                from app.planning import goal_plan
                plan = goal_plan(user)
                detail = ""
                if user.goal_mode != "custom":
                    detail = f"\nMaintenance: {user.maintenance_calories:,} kcal"
                    if user.goal_mode in {"bulk", "deficit"}:
                        detail += f" · {'+' if user.goal_mode == 'bulk' else '−'}{user.calorie_adjustment:,} kcal"
                await self._send(chat_id, f"{plan['label']} · {plan['target']:,} kcal/day{detail}\nChoose your plan and targets in Settings: {self.settings.app_url}")
            elif command == "/fasting":
                from app.planning import fasting_status
                status = fasting_status(user)
                if not status["enabled"]:
                    reply = "Intermittent fasting is off. Enable it and choose your daily eating window in Settings."
                else:
                    minutes = (status["seconds_until_transition"] + 59) // 60
                    phase = "Eating window open" if status["phase"] == "eating" else "Fasting · eating window closed"
                    reply = (f"{phase}\nDaily eating window: {user.eating_window_start}–{user.eating_window_end} ({user.timezone})\n"
                             f"{'Closes' if status['phase'] == 'eating' else 'Opens'} in {minutes // 60}h {minutes % 60}m\n"
                             f"Telegram reminders: {'enabled' if user.fasting_reminders else 'off'}")
                await self._send(chat_id, f"{reply}\n{self.settings.app_url}")
            elif command == "/undo":
                meal = db.scalar(select(Meal).where(Meal.user_id == user.id, Meal.source == "telegram").order_by(Meal.logged_at.desc(), Meal.id.desc()).limit(1))
                if meal is None:
                    await self._send(chat_id, "There are no meals from Telegram to undo.")
                else:
                    name, image_path = meal.name, meal.image_path
                    db.delete(meal)
                    # Commit the deletion and marker together: a response retry
                    # must never delete the next meal in the user's journal.
                    db.add(BotUpdate(update_id=update_id))
                    db.commit()
                    self._remove_image(image_path)
                    await self._send(chat_id, f"Removed {name}. You can send another photo or meal description whenever you're ready.")
                    return
            elif message.get("photo"):
                existing = db.scalar(select(Meal).where(Meal.telegram_update_id == update_id, Meal.user_id == user.id))
                if existing is not None:
                    await self._send_receipt(chat_id, existing)
                else:
                    try:
                        try:
                            self._photo_limiter.check(f"telegram-photo:{user.id}", 20, 3600)
                        except HTTPException:
                            raise VisionError("You've reached the limit of 20 AI meal analyses per hour. Try again later or use /log Meal name | calories.", 429) from None
                        photo = self._choose_photo(message["photo"])
                        data = await self._download(photo["file_id"])
                        logged_at = self._message_time(message.get("date"))
                        meal_type = self._meal_type(logged_at, user.timezone)
                        from app.services import add_photo_meal
                        meal = await add_photo_meal(
                            db, user, data, (message.get("caption") or "")[:1000],
                            meal_type, logged_at.replace(tzinfo=timezone.utc), self.settings,
                            source="telegram", telegram_update_id=update_id,
                        )
                    except VisionError as exc:
                        db.rollback()
                        await self._send(chat_id, str(exc))
                    else:
                        await self._send_receipt(chat_id, meal)
            elif text and (not text.startswith("/") or command == "/log"):
                existing = db.scalar(select(Meal).where(Meal.telegram_update_id == update_id, Meal.user_id == user.id))
                if existing is not None:
                    await self._send_receipt(chat_id, existing)
                else:
                    description = text.split(maxsplit=1)[1].strip() if command == "/log" and len(text.split(maxsplit=1)) > 1 else "" if command == "/log" else text
                    try:
                        if "|" not in description:
                            try:
                                self._photo_limiter.check(f"telegram-photo:{user.id}", 20, 3600)
                            except HTTPException:
                                raise VisionError("You've reached the limit of 20 AI meal analyses per hour. Try again later or use /log Meal name | calories.", 429) from None
                        from app.services import add_text_meal
                        logged_at = self._message_time(message.get("date"))
                        meal = await add_text_meal(db, user, description, logged_at.replace(tzinfo=timezone.utc),
                                                   self._meal_type(logged_at, user.timezone), self.settings, update_id)
                    except VisionError as exc:
                        db.rollback()
                        await self._send(chat_id, str(exc))
                    else:
                        await self._send_receipt(chat_id, meal)
            else:
                await self._send(chat_id, "Send a food photo or describe your meal and portions. For exact values: /log Meal name | calories. Use /today, /goal, /fasting, /undo, or /help.")
        self._mark(update_id)

    async def _link(self, raw_code: str, telegram_id: str, chat_id: str, update_id: int) -> None:
        reply = "This connection link has expired or was already used. Create a new link in your NutriLens settings."
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", raw_code):
            await self._send(chat_id, reply)
            self._mark(update_id)
            return
        with self.database.session() as db:
            code = db.get(LinkCode, token_hash(raw_code))
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if code is not None and code.expires_at > now:
                user = db.get(User, code.user_id)
                linked = db.scalar(select(User).where(User.telegram_user_id == telegram_id))
                if user is not None and (
                    (linked is not None and linked.id != user.id)
                    or (user.telegram_user_id is not None and user.telegram_user_id != telegram_id)
                ):
                    reply = "This Telegram account or NutriLens account is already connected. Disconnect it in the linked account's Settings before reconnecting."
                elif user is not None:
                    # Conditional consumption plus UNIQUE telegram_user_id prevents
                    # both replayed links and concurrent account reassignment.
                    consumed = db.execute(delete(LinkCode).where(LinkCode.code_hash == code.code_hash, LinkCode.expires_at > now))
                    if consumed.rowcount == 1:
                        result = db.execute(update(User).where(
                            User.id == user.id,
                            (User.telegram_user_id.is_(None)) | (User.telegram_user_id == telegram_id),
                        ).values(telegram_user_id=telegram_id, telegram_chat_id=chat_id, fasting_updated_at=now))
                        if result.rowcount == 1:
                            try:
                                db.add(BotUpdate(update_id=update_id))
                                db.commit()
                            except IntegrityError:
                                db.rollback()
                                reply = "This account is already connected. Check your NutriLens settings and try a new link."
                            else:
                                await self._send(chat_id, f"You're connected to NutriLens! Send a food photo or describe your meal and portions. {self.settings.photo_privacy_notice} Use /log Meal name | calories for exact values without AI. Enable fasting reminders in Settings. Use /help for all commands.")
                                return
                        else:
                            db.rollback()
        await self._send(chat_id, reply)
        self._mark(update_id)

    def _choose_photo(self, photos: list[dict]) -> dict:
        candidates = [p for p in photos if isinstance(p, dict) and p.get("file_id") and (p.get("file_size") or 0) <= self.settings.max_upload_bytes]
        if not candidates:
            raise VisionError("This photo is too large. Send a smaller photo and try again.")
        return max(candidates, key=lambda p: (p.get("width", 0) * p.get("height", 0), p.get("file_size", 0)))

    async def _download(self, file_id: str) -> bytes:
        info = await self._api("getFile", {"file_id": file_id})
        if not isinstance(info, dict):
            raise TelegramError()
        if (info.get("file_size") or 0) > self.settings.max_upload_bytes:
            raise VisionError("This photo is too large. Send a smaller photo and try again.")
        file_path = info.get("file_path", "")
        # getFile normally returns photos/file_123.jpg. Never follow an arbitrary
        # location or pass the bot token to a redirected download endpoint.
        if not isinstance(file_path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", file_path) or file_path.startswith("/") or ".." in PurePosixPath(file_path).parts:
            raise TelegramError()
        url = f"https://api.telegram.org/file/bot{self.settings.telegram_bot_token}/{file_path}"
        try:
            async with self._get_client().stream("GET", url) as response:
                if response.status_code != 200:
                    raise TelegramError(response.status_code)
                length = response.headers.get("content-length")
                if length and int(length) > self.settings.max_upload_bytes:
                    raise VisionError("This photo is too large. Send a smaller photo and try again.")
                result = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(result) + len(chunk) > self.settings.max_upload_bytes:
                        raise VisionError("This photo is too large. Send a smaller photo and try again.")
                    result.extend(chunk)
                return bytes(result)
        except (httpx.HTTPError, ValueError):
            raise TelegramError() from None

    def _remove_image(self, image_path: str | None) -> None:
        if not image_path:
            return
        directory = Path(self.settings.upload_dir).resolve()
        target = (directory / image_path).resolve()
        if target != directory and directory in target.parents:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove a deleted meal photo from storage.")

    async def _send_receipt(self, chat_id: str, meal: Meal) -> None:
        detail = (f"{'Photo' if meal.image_path else 'Text'} estimate · {meal.confidence or 'low'} confidence."
                  if meal.estimated else "Logged using your supplied values.")
        await self._send(chat_id, (
            f"Logged {meal.name}\n"
            f"{'≈ ' if meal.estimated else ''}{meal.calories:,.0f} kcal\n"
            f"Protein {meal.protein:.0f} g · Carbs {meal.carbs:.0f} g · Fat {meal.fat:.0f} g\n\n"
            f"{meal.notes[:700]}\n\n"
            f"{detail} Review or correct it at {self.settings.app_url}.\n"
            "Use /undo to remove your latest Telegram meal."
        ))

    @staticmethod
    def _message_time(timestamp: Any) -> datetime:
        try:
            return datetime.fromtimestamp(int(timestamp), timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError, OSError):
            return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _meal_type(logged_at: datetime, timezone_name: str) -> str:
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            zone = timezone.utc
        hour = logged_at.replace(tzinfo=timezone.utc).astimezone(zone).hour
        if 5 <= hour < 11:
            return "breakfast"
        if 11 <= hour < 16:
            return "lunch"
        if 16 <= hour < 22:
            return "dinner"
        return "snack"
