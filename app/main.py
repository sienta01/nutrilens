import asyncio
import csv
import io
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database
from app.models import LinkCode, LoginSession, Meal, User, utcnow
from app.schemas import Login, MealCreate, MealType, MealUpdate, Register, SettingsUpdate, validate_logged_at
from app.security import RateLimiter, hash_password, token_hash, verify_password
from app.services import (
    add_photo_meal, can_view_image, day_meals, day_summary, delete_meal, image_file,
    iso, local_today, meal_dict, to_utc, user_dict,
)

COOKIE_NAME = "nutrilens_session"
STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def get_db(request: Request):
    with request.app.state.db.session() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(LoginSession, token_hash(token)) if token else None
    if session is None or session.expires_at <= utcnow():
        raise HTTPException(401, "Sign in to continue.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


def owned_meal(db: Session, meal_id: str, user: User) -> Meal:
    meal = db.get(Meal, meal_id)
    if not meal or meal.user_id != user.id:
        raise HTTPException(404, "Meal not found.")
    return meal


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings.database_url)
    limiter = RateLimiter()
    dummy_hash = hash_password(secrets.token_urlsafe(24))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        worker = None
        if settings.telegram_polling:
            if settings.telegram_bot_token:
                from app.telegram_bot import TelegramBot
                bot = TelegramBot(settings, database)
                application.state.telegram_bot = bot
                worker = asyncio.create_task(bot.run(), name="telegram-polling")
            else:
                logger.warning("Telegram polling requested but TELEGRAM_BOT_TOKEN is empty.")
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            database.close()

    app = FastAPI(title="NutriLens", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-Requested-With") != "NutriLens":
                return JSONResponse({"detail": "Missing same-origin request header."}, status_code=403)
            origin = request.headers.get("origin")
            configured = urlsplit(settings.app_url)
            allowed_origins = {f"{configured.scheme}://{configured.netloc}", str(request.base_url).rstrip("/")}
            if (origin and origin not in allowed_origins) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
            limit = settings.max_upload_bytes + 1024 * 1024 if request.url.path == "/api/meals/photo" else 64 * 1024
            body_parts, body_size = [], 0
            async for chunk in request.stream():
                body_size += len(chunk)
                if body_size > limit:
                    return JSONResponse({"detail": "Request is too large."}, status_code=413)
                body_parts.append(chunk)
            request._body = b"".join(body_parts)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        # Do not echo input (including passwords, raw NaN, or photo bytes).
        messages = []
        for error in exc.errors()[:3]:
            location = ".".join(str(piece) for piece in error["loc"] if piece != "body")
            messages.append(f"{location + ': ' if location else ''}{error['msg']}")
        return JSONResponse({"detail": "; ".join(messages)}, status_code=422)

    def rate_auth(request: Request, operation: str, limit: int = 20, window: int = 60):
        address = request.client.host if request.client else "unknown"
        limiter.check(f"{operation}:{address}", limit, window)

    def sign_in(db: Session, user: User, request: Request, response: Response):
        old = request.cookies.get(COOKIE_NAME)
        if old:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(old)))
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= utcnow()))
        token = secrets.token_urlsafe(48)
        db.add(LoginSession(token_hash=token_hash(token), user_id=user.id,
                            expires_at=utcnow() + timedelta(days=settings.session_days)))
        db.commit()
        response.set_cookie(COOKIE_NAME, token, max_age=settings.session_days * 86400,
                            httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
        return user_dict(user)

    @app.get("/api/config")
    def config():
        return {
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_bot_username),
            "telegram_reminders_available": bool(settings.telegram_bot_token and settings.telegram_polling),
            "telegram_bot_username": settings.telegram_bot_username,
            "ai_configured": settings.ai_configured, "demo_enabled": settings.demo_enabled,
            "ai_provider": settings.ai_provider, "ai_provider_label": settings.ai_provider_label,
            "photo_privacy_notice": settings.photo_privacy_notice,
        }

    @app.get("/health")
    def health():
        with database.session() as db:
            db.execute(select(1))
        return {"status": "ok"}

    @app.post("/api/auth/register", status_code=201)
    def register(data: Register, request: Request, response: Response, db: Session = Depends(get_db)):
        rate_auth(request, "register", 10)
        user = User(email=str(data.email).lower(), password_hash=hash_password(data.password),
                    display_name=data.display_name, timezone=data.timezone)
        try:
            db.add(user)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "An account with that email already exists.")
        return sign_in(db, user, request, response)

    @app.post("/api/auth/login")
    def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
        rate_auth(request, "login")
        limiter.check(f"login-account:{token_hash(str(data.email).lower())}", 20, 60)
        user = db.scalar(select(User).where(User.email == str(data.email).lower(), User.is_demo.is_(False)))
        valid = verify_password(data.password, user.password_hash if user else dummy_hash)
        if not valid or user is None:
            raise HTTPException(401, "Email or password is incorrect.")
        return sign_in(db, user, request, response)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, db: Session = Depends(get_db)):
        token = request.cookies.get(COOKIE_NAME)
        if token:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(token)))
            db.commit()
        response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
        return {"ok": True}

    @app.post("/api/auth/demo")
    def demo(request: Request, response: Response, db: Session = Depends(get_db)):
        if not settings.demo_enabled:
            raise HTTPException(404, "Demo mode is disabled.")
        rate_auth(request, "demo", 5, 3600)
        from app.demo import create_demo
        return sign_in(db, create_demo(db), request, response)

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return user_dict(user)

    @app.patch("/api/me")
    def update_settings(data: SettingsUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
        from app.planning import apply_plan_settings
        changes = data.model_dump(exclude_unset=True)
        try:
            apply_plan_settings(user, changes, utcnow())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not user.share_progress:
            user.share_meals = False
        db.commit()
        return user_dict(user)

    @app.get("/api/dashboard")
    def dashboard(date: Date | None = Query(None, ge=Date(1970, 1, 1), le=Date(2100, 12, 31)), days: int = Query(7, ge=1, le=90),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
        return day_summary(db, user, date, days)

    @app.get("/api/meals")
    def list_meals(date: Date | None = Query(None, ge=Date(1970, 1, 1), le=Date(2100, 12, 31)), limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
        if date:
            meals = day_meals(db, user, date)[offset:offset + limit]
        else:
            meals = db.scalars(select(Meal).where(Meal.user_id == user.id)
                               .order_by(Meal.logged_at.desc(), Meal.id).limit(limit).offset(offset))
        return {"meals": [meal_dict(meal) for meal in meals]}

    @app.post("/api/meals", status_code=201)
    def create_meal(data: MealCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
        fields = data.model_dump(exclude={"logged_at"})
        meal = Meal(user_id=user.id, **fields, logged_at=to_utc(data.logged_at, user))
        db.add(meal)
        db.commit()
        return meal_dict(meal)

    @app.post("/api/meals/photo", status_code=201)
    async def photo(file: UploadFile = File(...), notes: str = Form("", max_length=2000),
                    meal_type: MealType = Form("snack"), logged_at: datetime | None = Form(None),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
        from app.vision import VisionError
        if user.is_demo:
            raise HTTPException(403, "Create your own account to analyze meal photos.")
        try:
            validate_logged_at(logged_at)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        limiter.check(f"photo:{user.id}", 20, 3600)
        raw = await file.read(settings.max_upload_bytes + 1)
        try:
            meal = await add_photo_meal(db, user, raw, notes, meal_type, logged_at, settings)
        except VisionError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        finally:
            await file.close()
        return meal_dict(meal)

    @app.patch("/api/meals/{meal_id}")
    def update_meal(meal_id: str, data: MealUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
        meal = owned_meal(db, meal_id, user)
        changes = data.model_dump(exclude_unset=True)
        nutrition_changed = any(
            key in changes and changes[key] != getattr(meal, key)
            for key in ("calories", "protein", "carbs", "fat")
        )
        if "logged_at" in changes:
            changes["logged_at"] = to_utc(changes["logged_at"], user)
        for key, value in changes.items():
            setattr(meal, key, value)
        if nutrition_changed:
            meal.estimated = False
            meal.confidence = None
        db.commit()
        return meal_dict(meal)

    @app.delete("/api/meals/{meal_id}")
    def remove_meal(meal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        delete_meal(db, owned_meal(db, meal_id, user), settings)
        return {"ok": True}

    @app.get("/api/meals/{meal_id}/image")
    def meal_image(meal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        meal = db.get(Meal, meal_id)
        owner = db.get(User, meal.user_id) if meal else None
        if not meal or not owner or not meal.image_path or not can_view_image(user, owner):
            raise HTTPException(404, "Photo not found.")
        try:
            path = image_file(settings, meal.image_path)
        except ValueError:
            raise HTTPException(404, "Photo not found.")
        if not path.is_file():
            raise HTTPException(404, "Photo not found.")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/community")
    def community(limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
        query = select(User).where(User.share_progress.is_(True), User.is_demo == user.is_demo)
        if user.is_demo:
            query = query.where(User.demo_group == user.demo_group)
        members = db.scalars(query.order_by(User.display_name, User.id).limit(limit).offset(offset))
        profiles = []
        for member in members:
            summary = day_summary(db, member)
            shared_meals = day_meals(db, member, local_today(member)) if member.share_meals else []
            profiles.append({
                "id": member.id, "display_name": member.display_name,
                "initials": "".join(part[0] for part in member.display_name.split()[:2]).upper(),
                "streak": summary["streak"], "totals": summary["totals"],
                "daily_calorie_goal": member.daily_calorie_goal, "weekly": summary["weekly"],
                "date": summary["date"], "timezone": member.timezone,
                "share_meals": member.share_meals,
                "meals": [meal_dict(meal, shared=True) for meal in shared_meals],
            })
        return {"users": profiles}

    @app.post("/api/telegram/link")
    def telegram_link(user: User = Depends(current_user), db: Session = Depends(get_db)):
        if user.is_demo:
            raise HTTPException(403, "Create your own account to connect Telegram.")
        if not settings.telegram_bot_token or not settings.telegram_bot_username:
            raise HTTPException(503, "Telegram is not configured. Add the bot token and username to .env.")
        limiter.check(f"link:{user.id}", 10)
        code = secrets.token_urlsafe(24)
        expiry = utcnow() + timedelta(minutes=10)
        db.execute(delete(LinkCode).where((LinkCode.user_id == user.id) | (LinkCode.expires_at <= utcnow())))
        db.add(LinkCode(code_hash=token_hash(code), user_id=user.id, expires_at=expiry))
        db.commit()
        return {"code": code, "deep_link": f"https://t.me/{settings.telegram_bot_username}?start={code}",
                "expires_at": iso(expiry)}

    @app.delete("/api/telegram/link")
    def unlink_telegram(user: User = Depends(current_user), db: Session = Depends(get_db)):
        user.telegram_user_id = None
        user.telegram_chat_id = None
        user.fasting_updated_at = utcnow()
        db.execute(delete(LinkCode).where(LinkCode.user_id == user.id))
        db.commit()
        return {"ok": True}

    @app.get("/api/export.csv", include_in_schema=False)
    @app.get("/api/export")
    def export(user: User = Depends(current_user), db: Session = Depends(get_db)):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        keys = ["logged_at", "name", "meal_type", "calories", "protein", "carbs", "fat", "notes", "source", "estimated"]
        writer.writerow(keys)
        for meal in db.scalars(select(Meal).where(Meal.user_id == user.id).order_by(Meal.logged_at.desc())):
            values = meal_dict(meal)
            row = []
            for key in keys:
                value = values[key]
                if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
                    value = "'" + value
                row.append(value)
            writer.writerow(row)
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="nutrilens-meals.csv"'})

    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
