# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

`.venv/` is gitignored and **uv-managed** (Python 3.13, `uv 0.10.9`). It has no `pip`, so `python -m pip install` fails with `No module named pip` — install through uv instead:

```powershell
uv pip install -r requirements-dev.txt   # runtime deps are usually present; pytest/ruff often are not
Copy-Item .env.example .env              # if .env is missing
```

```powershell
# Run the server (http://localhost:8000)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Tests and lint
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_planning.py -q                  # one file
.\.venv\Scripts\python.exe -m pytest tests/test_planning.py::test_all_reminder_events_and_offline_grace   # one test
.\.venv\Scripts\python.exe -m pytest -k fasting -q                              # by name
.\.venv\Scripts\python.exe -m ruff check app tests

# Optional browser smoke check: start a server with DEMO_ENABLED=true first
uv pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests\browser_smoke.py      # NUTRILENS_TEST_URL overrides the port
```

The committed suite takes **~3 minutes** — `hash_password()` uses `scrypt(n=16384)` and the API tests register real accounts. Budget for that rather than assuming a hang; run a single file while iterating.

Tests use temporary SQLite databases and mocked HTTP transports, and `asyncio_mode = "auto"` is set so `async def test_*` needs no marker. Ruff runs with `line-length = 120` and only the `E4`/`E7`/`E9`/`F` rule sets.

Two caveats before trusting a run:

- **Every `Settings(...)` built in a test must pass `_env_file=None`.** Without it pydantic-settings reads the developer's real `.env`, so an `AI_1_*` chain on disk silently becomes the chain under test — which is how two committed provider tests started hitting a live Groq line. `tests/conftest.py` now passes it; keep new direct constructions consistent.
- `tests/test_api_groq.py` is an untracked scratch script, not a test module: it defines no test functions, and its module body fires a **live** `GET https://api.groq.com/openai/v1/models` with the real `GROQ_API_KEY` at pytest **collection** time. It imports `requests` and `python-dotenv`, which are installed in the venv but absent from both requirements files. Delete or rename it before treating "the suite makes no network calls" as true.

Local Python is 3.13; the Dockerfile builds on `python:3.11-slim` and ruff targets `py311`. Avoid 3.12+-only syntax.

## The AI provider chain

`Settings` reads up to three ordered failover lines — `AI_1_PROVIDER` / `AI_1_API_KEY` / `AI_1_MODEL` through `AI_3_*` — and `ai_chain` turns them into a list of frozen `AiLine(provider, api_key, model)`. Providers are `gemini`, `groq`, and `openai`. Points that are easy to get wrong:

- **Lines replace the single-provider settings entirely.** If any `AI_n_*` line is set, `AI_PROVIDER` and its key are ignored — not merged, not appended. With no lines at all, `ai_chain` is the one legacy provider, or empty when its key is blank.
- **`extra="ignore"` means a typo'd line name vanishes silently.** `AI_1_PROVIER=groq` does not raise; it disables the line. This is what broke the chain once already: `.env` moved to `AI_1_*` while `Settings` still only knew `AI_PROVIDER`, so every line was dropped and `ai_configured` went quietly `False`.
- A line with a provider but no key (or vice versa) raises at **startup**, from `_build_chain()` in the `public_settings` model validator — not at the first upload.
- Per-line models are validated against *that line's* provider: a `gemini` line rejects `gpt-4.1-mini`, and every non-Gemini model must match `_MODEL_ID` (one optional namespace segment, each starting alphanumeric) so `../qwen`, `/qwen`, `a/b/c`, and URLs cannot redirect an endpoint.
- `ai_primary_provider` falls back to `ai_provider` when the chain is empty, so an unconfigured install still labels itself correctly in `/api/config` and the Settings page.

`_run_chain()` in [app/vision.py](app/vision.py) walks the lines and dispatches through the `_PROVIDERS` registry. **The chain advances only on failure.** A `VisionError` with status 422 is the model's real answer — "not food", a refusal, a safety block — and is re-raised immediately: asking the next provider would spend a second quota and risk inventing a meal the first one declined to see. Everything else (401/403/429/5xx, unreadable replies) moves to the next line, and the last line's error is what surfaces. Each line uses its own credential; a line never borrows the previous one's.

Groq speaks the OpenAI-compatible `api.groq.com/openai/v1/chat/completions` surface, with two quirks encoded in `_estimate_groq`: a single HTTP 400 triggers one downgrade from strict `json_schema` to plain `json_object` mode on the same model and account (so the downgraded system prompt has to state the schema itself), and `reasoning_format: hidden` is required for Qwen — which otherwise wraps its JSON in `<think>` tags — but rejected outright by `openai/gpt-oss-*`.

## Architecture

FastAPI + SQLAlchemy 2.0 + SQLite, served alongside a dependency-free vanilla-JS frontend from the same process. No build step, no JS toolchain, no ORM migration framework.

### App construction

[app/main.py](app/main.py) defines `create_app(settings)` — everything (database, rate limiter, routes, lifespan) is built inside that factory and closed over. Module-level `app = create_app()` is only the uvicorn entry point; tests call the factory directly with per-test `Settings` (see [tests/conftest.py](tests/conftest.py)), so nothing may rely on module-level singletons.

Several imports are deliberately deferred into function bodies (`app.vision`, `app.telegram_bot`, `app.demo`, `app.planning`, `app.services` inside `telegram_bot`) to keep import-time light and break cycles. Keep new cross-module calls in the same style when a cycle would otherwise form.

### Settings mutate themselves

[app/config.py](app/config.py) is not a passive record. A `model_validator` **forces** `demo_enabled = False` when `APP_URL`'s host is not localhost, and **forces** `cookie_secure = True` for an `https://` `APP_URL`. `GEMINI_MODEL` is regex-validated so a model ID can never redirect the API endpoint. Don't expect the values you set in `.env` to survive unchanged.

### Time handling — the most fragile area

Every `datetime` in the database is **naive UTC**: `models.utcnow()` returns `datetime.now(timezone.utc).replace(tzinfo=None)`. Each user carries an IANA `timezone` string, and all calendar logic goes through helpers in [app/services.py](app/services.py) — `to_utc()`, `day_bounds()`, `local_today()`, `iso()`. Never compare a stored timestamp against `datetime.now()` directly, and never compute a day boundary without the user's zone.

[app/planning.py](app/planning.py) layers eating windows on top of this: `scheduled_windows()` yields a ±2-day span of UTC window pairs so overnight windows (`22:00–06:00`) and DST transitions resolve correctly (`fold=0` picks the first occurrence on a repeated clock time; nonexistent times shift forward). `test_planning.py` pins these boundaries — changing window math without running it is how DST bugs get in.

`apply_plan_settings()` validates the **merged** settings (existing user + incoming changes) before mutating the `User`, so a rejected update leaves the account untouched. It also derives `daily_calorie_goal` from `goal_mode` + `maintenance_calories` + `calorie_adjustment`, and stamps `fasting_updated_at` whenever a field in `FASTING_FIELDS` changes — that timestamp suppresses reminders scheduled before the change.

### Request protection

An HTTP middleware in `create_app` guards every non-GET `/api/` request: it requires the `X-Requested-With: NutriLens` header, rejects cross-site `Origin`/`Sec-Fetch-Site`, and streams the body to enforce a size cap (11 MB for `/api/meals/photo`, 64 KB otherwise) before re-attaching it as `request._body`. Any new test client or fetch call must send that header. The middleware also sets the CSP, which forbids inline scripts — so the frontend cannot use inline `onclick` handlers.

The `RequestValidationError` handler deliberately rebuilds messages from `loc` + `msg` only, never echoing input, so passwords and photo bytes cannot leak into a 422 body.

Auth is server-side sessions: a random token in an HttpOnly cookie, only its SHA-256 stored in the `sessions` table. `RateLimiter` in [app/security.py](app/security.py) is per-process only — a multi-replica deployment needs a shared limiter in front.

### Telegram bot and reminders

[app/telegram_bot.py](app/telegram_bot.py) long-polls (no webhook endpoint exists) and must run as **exactly one worker**. Idempotency is layered, because Telegram redelivers:

- The `bot_updates` table is the durable offset checkpoint — never reconstruct an offset from `MAX(update_id)`, since Telegram resets IDs after a week of inactivity.
- `Meal.telegram_update_id` is `UNIQUE`, so a redelivered photo/text message re-sends the receipt instead of creating a second meal.
- `/undo` commits the meal deletion and the `BotUpdate` marker in one transaction, so a retried response can't delete the next meal.

Group chats are ignored outright (`chat.type != "private"`, or chat id ≠ sender id). Errors are logged by exception *type* only and a logging filter redacts the bot token, because Telegram URLs and network exceptions carry the token and private message content.

`ReminderWorker` ([app/reminders.py](app/reminders.py)) is started **from inside `TelegramBot.run()`**, not from the lifespan — so fasting reminders exist only when `TELEGRAM_POLLING=true`. It ticks every 30s and is deliberately **at-most-once**: it claims each event by inserting into `reminder_deliveries` (unique on `user_id, kind, scheduled_at`) and never retries a failed send, since a timeout may mean Telegram already accepted it.

### AI meal estimation

[app/vision.py](app/vision.py) handles all three providers behind one shared `MEAL_SCHEMA` and one strict `_validate_estimate()`. Rules the code enforces on purpose:

- Only providers on the configured chain are ever contacted, in order — a spare key for an unlisted provider is never used. See the chain section above for when a line is skipped.
- `normalize_image()` re-encodes onto a fresh canvas to strip EXIF/GPS/ICC/XMP, rejects animations and decompression bombs, and caps the long edge at 1600px. Only these normalized bytes are stored or sent.
- Every `VisionError` message is user-facing and provider-sanitized; provider error text is never surfaced. `VisionError.status_code` is what the route turns into an HTTP status.
- `is_food: false` is a rejection, not a zero-calorie meal — failed analysis never writes a record.
- Prompts explicitly mark image text and user notes as untrusted data.

### Privacy and sharing

Accounts start private. `share_meals` is meaningless without `share_progress` (the `PATCH /api/me` route clears it). `meal_dict(meal, shared=True)` strips notes and source metadata; `can_view_image()` re-checks the owner's current sharing flags on **every** image request, so revoking sharing immediately breaks previously-shared photo URLs. `image_file()` resolves and containment-checks every path against `UPLOAD_DIR` — uploads are never served as a static directory.

Demo workspaces ([app/demo.py](app/demo.py)) create a fresh `demo_group` UUID with three synthetic users per visit; `same_community()` keeps demo and real accounts mutually invisible and isolates one demo group from another. Demo users cannot connect Telegram, analyze photos, or receive reminders.

### Schema changes

`Database.initialize()` runs `create_all()` and then `migrations.upgrade()`. [app/migrations.py](app/migrations.py) is an additive-only `USER_COLUMNS` dict of fixed, application-owned DDL applied when a column is missing — repeatable and non-destructive. When you add a column to `User`, add it to both [app/models.py](app/models.py) and that dict; anything beyond additive column adds (renames, drops, backfills, other tables) needs a real migration story that does not exist yet.

### Frontend

[app/static/app.js](app/static/app.js) is one ~880-line file with no dependencies and no bundler. It keeps a single `state` object, re-renders pages by assigning template strings to `innerHTML`, and routes all interaction through **document-level delegated listeners** keyed on `data-action` / `data-page` attributes. Every interpolated value must pass through `esc()`. `refreshProgress()` polls every 30s and on `visibilitychange`, which is why a meal written by the bot appears without a reload.

## Reference

[README.md](README.md) documents the full user-facing behavior, every environment variable, provider setup, hosting/backup guidance, and the Telegram command list. Consult it before changing user-visible wording or configuration semantics.

Logging is configured once by `configure_logging()` in [app/main.py](app/main.py), driven by `LOG_LEVEL` (default `INFO`). It raises the level of the `app` logger only, leaving uvicorn's and httpx's alone, and both handlers are tagged `_nutrilens` so repeated `create_app()` calls in tests don't stack them. At `INFO` the startup banner prints the failover order (providers and models, never keys) and each provider attempt logs one line; failures log the **provider label and our mapped status only**, because provider error text can quote the user's photo or notes — the upstream status comes from the httpx line above it.

`DropPollingNoise` is attached to the `httpx` and `uvicorn.access` **loggers** (not the handlers, so a dropped record reaches neither the console nor the file). It discards exactly two things, and only on a 2xx: the Telegram `getUpdates` long poll and `GET /health`, each of which lands every ~30s on an idle server and otherwise buries real events and churns the rotating file. It is a filter rather than a level change on `httpx` because **a provider attempt's upstream status exists only on its httpx line** — silencing that logger would leave AI failures with no upstream status anywhere. A failing poll or an unhealthy probe still logs, and `LOG_LEVEL=DEBUG` removes the filter entirely.

Output goes to the console and, unless `LOG_FILE` is empty, to a `RotatingFileHandler` at `LOG_FILE` (default `data/nutrilens.log`, gitignored, rotating at `LOG_MAX_BYTES` keeping `LOG_BACKUP_COUNT`). Rotation assumes **one writer**, which matches the one-worker rule the Telegram bot already imposes. An unwritable path logs a warning and falls back to console-only rather than failing startup. `RedactSecrets` from [app/security.py](app/security.py) is attached to **both handlers**, not just the `httpx` logger as before, because a leaked token on disk persists in a way a console line does not. `tests/conftest.py` sets `log_file=""` so no test writes one.

On model IDs: `GEMINI_MODEL` defaults to the moving alias `gemini-flash-latest` on purpose. Google retires pinned IDs — `gemini-2.5-flash-lite`, the previous default, is still returned by the `/v1beta/models` listing but answers `generateContent` with `404 ... no longer available to new users`. **A model appearing in the list does not mean the key can call it**; check with an actual `generateContent` request.
