# NutriLens

A Python calorie tracker with Telegram photo/text logging, bulking and deficit targets, intermittent fasting reminders, a responsive dashboard, and private accounts with optional community sharing.

## Run locally

Requires **Python 3.11+**. In PowerShell, from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**. Register your account, or choose **Explore demo** to try a separate workspace with sample meals and community profiles. Registration uses email as a login name; this version does not send verification emails or password-reset emails. Passwords require at least 10 characters.

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, `cp .env.example .env`, and `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

Manual meal logging, goals, fasting schedules, progress charts, sharing, and exports work without external credentials. Automatic photo and text analysis uses Gemini by default and needs a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey). OpenAI remains available as an optional provider. Telegram logging and reminders need a Telegram bot token. Exact-value Telegram entries and fasting reminders do not use an AI API.

## Connect Telegram and meal analysis

1. Open [@BotFather](https://t.me/BotFather) in Telegram. Send `/newbot`, follow its prompts, and save the token and bot username privately.
2. Edit `.env`:

   ```dotenv
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_BOT_USERNAME=your_bot_username_without_at
   TELEGRAM_POLLING=true
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key
   GEMINI_MODEL=gemini-flash-latest
   ```

3. Restart the server. Sign in on the website, open **Settings**, and choose **Connect Telegram**. Open the generated Telegram link and press **Start**. The link is single-use and expires after 10 minutes. Each website account can connect its own Telegram account to the same bot.
4. Send a meal photo in your private bot chat. An optional caption can explain portions or ingredients, for example `half a plate, with peanut sauce`. The bot saves an approximate calorie and macro estimate, replies with the result, and the web dashboard refreshes while open. You can correct or delete the entry on the website.

You can also send text:

- **AI estimate:** `2 eggs, 2 slices of toast and a banana`, or `/log 1 cup rice with 150g grilled chicken`. Include portions for a more useful estimate. Both Gemini and OpenAI support text logging; the configured provider is used.
- **Exact calories and macros, no AI:** `/log Chicken rice | 650 | 40 | 75 | 20`. The order is **meal name | kcal | protein (g) | carbs (g) | fat (g)**. Enter numbers without unit suffixes.
- **Calories only, no AI:** `/log Coffee | 60`. Omitted macros are recorded as **0**, with a note that they were not supplied. Add them later on the dashboard if needed.

Text entries appear in the same diary and totals as photos. AI entries are labeled estimates; supplied values are labeled manual values. Account ownership, sharing preferences, original message time, and `/undo` work for both. Empty, invalid, or unsuccessful entries are not saved. AI photo/text analyses share a limit of 20 per hour per Telegram account; exact-value entries remain available.

Bot commands:

| Command | Action |
| --- | --- |
| `/start` or `/help` | Show connection instructions and help |
| `/today` | Show today's calories, macros, and meal count |
| `/log description` | Estimate a meal from text |
| `/log Name \| kcal \| protein \| carbs \| fat` | Log supplied values without AI; macros may all be omitted |
| `/goal` | Show the current calorie plan and target |
| `/fasting` | Show the current fasting/eating phase, next transition, and reminder preference |
| `/undo` | Delete the latest meal logged through Telegram |

The bot receives updates through **long polling**, so local use does not need a public webhook or tunnel. Keep the Python server running. Use **exactly one app worker** when polling is enabled. If the bot has an existing webhook, explicitly remove it with Telegram's `deleteWebhook` method before enabling polling; the app reports conflicts and does not alter existing webhooks. This app has no public webhook endpoint.

Photos can also be uploaded on the website. JPEG, PNG, and WebP are supported up to 10 MB and 25 megapixels; very large dimensions and animated images are rejected. Images are resized, rotated, stripped of metadata, and stored privately. The normalized photo/caption or meal description is sent only to the providers you configure, in order, and only as far down that order as the first one that answers. The website and bot name every provider a photo may reach before analysis. Gemini free-tier content may be used by Google to improve its products; consult [Google’s data-use terms](https://ai.google.dev/gemini-api/terms). With OpenAI selected, requests use `store: false`, and its processing/retention terms still apply. There is no local AI model bundled with the app.

Photo estimates cannot measure portions, oils, or hidden ingredients precisely. Every generated meal is labeled as an estimate with a confidence level and serving assumptions, and the Telegram receipt names the provider and model that answered, so a meal logged by a fallback line is identifiable after the fact. Correct its numbers when needed. Failed analysis never creates a made-up meal. The selected model must be available to your provider account and support image input plus structured JSON output.

## Gemini free tier and provider choice

The default `gemini-flash-latest` is a moving alias that always points at a current Flash model, which matters because Google retires pinned IDs — `gemini-2.5-flash-lite` is still listed by the models endpoint but now returns `404 … no longer available to new users` for keys created after its cutoff. Pin an exact ID instead if you need the model to stay fixed. Check [Google’s pricing](https://ai.google.dev/gemini-api/docs/pricing) for the free-tier status of whichever model the alias resolves to. Create your key in [Google AI Studio](https://aistudio.google.com/apikey), select an eligible free-tier project, and check its current [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Availability and quotas vary by model, project, and region. All users on this installation share the configured Google project's quota.

`AI_PROVIDER=gemini` chooses the API provider; it does **not** force Google to use free billing. If your Google project is on a paid tier, its API usage follows that project's billing. No fixed number of free photos is guaranteed. If quota is exhausted on a single-provider install, the app reports the error and saves no meal. You can retry later or log the meal manually.

### Failover across several providers

Set numbered lines instead of `AI_PROVIDER` to try providers in order. Each line carries its own key, so a line that is out of quota hands the same photo to the next account:

```dotenv
AI_1_PROVIDER=groq
AI_1_API_KEY=your_groq_api_key
AI_2_PROVIDER=gemini
AI_2_API_KEY=your_google_api_key
AI_3_PROVIDER=openai
AI_3_API_KEY=your_openai_api_key
```

Up to eight lines are read (`AI_1_*` through `AI_8_*`); numbers you skip or leave blank are simply passed over, so the chain is as long as your `.env` makes it. A line numbered beyond the eighth is ignored without complaint — raise `AI_LINE_LIMIT` in [app/config.py](app/config.py) if you need more.

`AI_n_MODEL` is optional and defaults to that provider's model setting. Two lines may name the same provider with different keys. Setting any `AI_n_*` line replaces `AI_PROVIDER` and its key entirely, and a line missing its provider or key is rejected at startup rather than at the first upload.

The chain advances **only on failure** — exhausted quota, rejected credentials, an outage, or an unreadable reply. A provider that answers "this isn't food" or refuses the image has genuinely answered, so that result is final and no second account is charged. When every line fails, the last provider's error is what you see. The Settings page shows the configured order, and the photo privacy notice names every provider a photo may reach.

To use OpenAI instead, set these values and restart:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
```

Only the keys actually named by your configuration are required. OpenAI API usage is billed separately from a ChatGPT subscription. Existing meal records and account settings work with either provider. No new Python dependencies are needed for Gemini support.

## Calorie plans and intermittent fasting

In **Settings → Your daily goals**, choose **Custom target**, **Maintenance**, **Bulking (surplus)**, or **Calorie deficit**. Enter your own maintenance estimate and desired daily surplus/deficit. For example, maintenance of 2,400 kcal with a 300 kcal adjustment gives a bulking target of 2,700 or a deficit target of 2,100. Maintenance uses the base directly; Custom lets you enter a target directly. Macro goals remain individually editable. These are tracking preferences, not an automatic maintenance calculator. Dashboard totals and charts use your selected target; historical charts show the current goal rather than a history of past goal changes.

In **Settings → Intermittent fasting**:

1. Enable the fasting schedule and choose when the **eating window opens and closes**. `12:00–20:00` means 8 hours eating / 16 hours fasting. Overnight windows, such as `22:00–06:00`, are supported.
2. Enable **Telegram reminders** after connecting your Telegram account. Choose opening and closing notifications separately, and a fasting heads-up 0–120 minutes before the window closes. Set the heads-up to 0 to disable it.
3. **Save changes.** The dashboard shows the current phase and time until the next opening or closing, even when viewing a historical food-diary date. `/fasting` shows the same status in Telegram. The schedule does not prevent meal logging outside the eating window.

Schedules use each account's IANA time zone, including daylight saving. On a repeated clock time, the first occurrence is used; a nonexistent time moves forward by the clock change. A window that becomes empty on that day is skipped. Displayed fasting/eating hours describe the nominal daily schedule; actual elapsed hours may differ on clock-change days.

Reminders require **`TELEGRAM_POLLING=true` and a running server with a working bot**. They are checked every 30 seconds, so delivery is approximate. Events up to 5 minutes old can be delivered after a brief interruption; older events and events preceding a schedule change/reconnection are skipped. Delivery attempts are stored in the database to avoid duplicates on restarts. A failed or interrupted send is not retried because Telegram may already have accepted it; reminders are best effort. Turn off the schedule/reminder toggle or disconnect Telegram to stop them. Demo accounts never send reminders. Each account has its own schedule and private destination; fasting preferences are not published in the community.

Existing installations keep their calorie targets in **Custom target** mode, with fasting and reminders off. Startup automatically adds the new settings and reminder table while retaining existing accounts, meals, and connections.

## Accounts, progress, and sharing

- Every account has its own meal history, daily calorie/macro goals, IANA time zone, Telegram connection, and CSV export. Calendar dates and totals use the account's time zone, including daylight-saving boundaries.
- Dashboard dates, 7/30-day trends, calorie totals, macros, and logging streaks are based on saved meals. Streaks measure consecutive days of logging; they do not reward low calorie intake.
- Accounts start **private**. **Share progress** publishes your display name, daily totals, calorie goal, weekly trend, and logging streak to other signed-in users in the community.
- **Share meals** is a separate opt-in for your meal names, nutrition, and photos from the last 7 days, grouped by day in the community. Your personal meal notes, email, login details, and Telegram identity stay private. Turning progress sharing off also turns meal sharing off. Previously shared photo URLs check permissions on every request.
- Community sharing is visible to all signed-in accounts on this installation; there are no friend lists or follower approvals in this version. Someone who already viewed shared content may keep a copy.
- Demo workspaces use synthetic data, are isolated from real users and other demo sessions, and cannot connect Telegram or use paid photo analysis. Public `APP_URL` hostnames automatically disable the demo endpoint. Demo data persists locally until database maintenance or removal.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_URL` | `http://localhost:8000` | Website address used in bot messages and request checks |
| `BIND_ADDR` | `127.0.0.1` | Compose only: address the published port binds to; `0.0.0.0` exposes it to the LAN |
| `DATABASE_URL` | `sqlite:///./data/nutrilens.db` | Persistent SQLAlchemy database URL |
| `UPLOAD_DIR` | `./data/uploads` | Private meal photo directory |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS; an `https://` `APP_URL` forces it on, overriding this value |
| `DEMO_ENABLED` | `true` | Sample workspaces, automatically disabled for a public `APP_URL` |
| `TELEGRAM_BOT_TOKEN` | empty | BotFather token |
| `TELEGRAM_BOT_USERNAME` | empty | Bot username, without `@` |
| `TELEGRAM_POLLING` | `false` | Start the bot polling worker inside the server |
| `LOG_LEVEL` | `INFO` | `CRITICAL`–`DEBUG`; see [Log levels](#log-levels) below |
| `LOG_FILE` | `data/nutrilens.log` | Rotating log file; empty disables file logging |
| `LOG_MAX_BYTES` | `5242880` | Rotate once the log file reaches this size |
| `LOG_BACKUP_COUNT` | `3` | Rotated files kept alongside the current one |
| `AI_1_PROVIDER` … `AI_8_PROVIDER` | empty | Failover chain line: `gemini`, `groq`, or `openai` |
| `AI_1_API_KEY` … `AI_8_API_KEY` | empty | That line's own credential and billing account |
| `AI_1_MODEL` … `AI_8_MODEL` | provider default | Optional per-line model override |
| `AI_PROVIDER` | `gemini` | Single-provider fallback, ignored when any `AI_n_*` line is set |
| `GEMINI_API_KEY` | empty | Server-side Gemini API credential from Google AI Studio |
| `GEMINI_MODEL` | `gemini-flash-latest` | Gemini model with image input and structured-output support |
| `GROQ_API_KEY` | empty | Optional server-side Groq API credential |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Image-capable Groq model with structured-output support |
| `OPENAI_API_KEY` | empty | Optional server-side OpenAI API credential |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Image-capable model with structured-output support |

Settings load from `.env` and environment variables, with environment variables taking precedence. Never put API keys in the frontend. `.env`, local databases, uploads, and the virtual environment are ignored by Git.

### Log levels

`LOG_LEVEL` sets the level of the application's own `app` logger. Each level includes everything below it in this table.

| Level | What the application logs |
| --- | --- |
| `ERROR` | Something stopped: every configured AI line failed, a Telegram polling conflict or rejected token, a fasting reminder check that raised |
| `WARNING` | Degraded but still running: one AI line failed and the chain moved to the next, Groq's strict-schema downgrade, an unwritable `LOG_FILE`, polling enabled with no token, a meal photo that could not be deleted from storage |
| `INFO` (default) | Normal operation: the failover chain at startup, one line per provider attempt naming the provider and model, and whether the chain recovered or gave a final answer |
| `DEBUG` | Adds no messages of its own. It removes the polling-noise filter, so successful Telegram `getUpdates` polls and `GET /health` probes reappear |

Three behaviours are worth knowing before you pick a level to quieten things down:

- **Uvicorn's access log ignores `LOG_LEVEL` completely.** Uvicorn pins `uvicorn.access` at `INFO` with `propagate: false`, so request lines keep appearing at every setting, including `CRITICAL`. The only ones suppressed are successful `/health` probes, and that is the filter's doing rather than the level's.
- **`WARNING` and below also silence `httpx`.** That logger has no level of its own, so it follows the root level, which tracks `LOG_LEVEL` down to `INFO` but no lower. Since a provider attempt's upstream status is recorded *only* on its httpx line, dropping to `WARNING` leaves AI failures showing our mapped status with no upstream status anywhere. Prefer `INFO` while diagnosing provider problems.
- **`ERROR` and `CRITICAL` still let third-party warnings through.** The root logger is never raised above `WARNING`, so libraries continue to report at that level even when the app itself has gone quiet.

Keys, tokens, and photo bytes are never logged at any level. Provider error text is never surfaced, and `RedactSecrets` rewrites the bot token out of every record reaching the console or the file.

## Hosting

For use by other people, host the app on an always-on server with persistent storage and an HTTPS reverse proxy. Set `APP_URL=https://your-domain`, `COOKIE_SECURE=true`, and `DEMO_ENABLED=false`. Configure the proxy to allow request bodies up to 11 MB. Do not expose `data/uploads` as a static directory. Run one Uvicorn worker if Telegram polling is enabled.

An optional container setup is included:

```shell
docker compose up --build -d
```

It reads your `.env`, binds port 8000 on localhost, and stores the database and photos in a persistent Docker volume. Put your reverse proxy in front of that port, or see [Reaching it from other devices](#reaching-it-from-other-devices) to open it to your network instead.

The initial schema is created at startup. This version includes an additive startup migration for calorie plans and fasting preferences in `app/migrations.py`. Future schema changes still need explicit migrations; no general migration framework is included.

### Reaching it from other devices

The published port is loopback-only by default, so the app answers on the Docker host and nowhere else. That is correct behind a reverse proxy on the same host, and it is why a machine on the same LAN gets a refused connection. To reach it from other devices without a proxy:

```shell
BIND_ADDR=0.0.0.0
APP_URL=http://<docker-host-lan-ip>:8000
```

Then `docker compose up -d --force-recreate` — Compose does not reliably notice edits to the *contents* of `env_file`, so a plain `up -d` can leave the previous `APP_URL` baked into the running container. Open port 8000 in the Docker host's firewall.

**Keep `APP_URL` on `http://` for this.** An `https://` value forces `COOKIE_SECURE=true` through the `model_validator` in `app/config.py`, which overrides `COOKIE_SECURE` in `.env` rather than merging with it. The browser then withholds the session cookie over plain HTTP, and login fails by silently returning you to the login screen with nothing logged as an error.

`BIND_ADDR=0.0.0.0` also covers a VPN interface such as Tailscale, so the same port answers on the host's VPN address with no extra configuration. Traffic over a WireGuard-based VPN is already encrypted end to end, which makes plain HTTP over that address a reasonable remote path; a TLS-terminating proxy in front would add a hostname and a padlock rather than confidentiality you lack. Note that such a proxy also changes the browser's `Origin` to `https://`, which the mutation check rejects unless `APP_URL` matches it exactly — and matching it re-triggers the `COOKIE_SECURE` behaviour above, breaking plain-IP access. Pick one or the other.

**If Docker runs inside WSL2, the VPN address is the WSL distro's, not Windows'.** A VPN client running inside the distro registers as its own node with its own address, separate from the one the Windows host has — they are two peers on the same network, not one machine with one address. The container binds inside the distro's network namespace, so it answers on the distro's VPN address and the Windows host's VPN address times out. WSL2's mirrored networking mode adds to the confusion by sharing the host's *physical* adapter, so the LAN address works while the VPN address does not: mirroring covers Ethernet and Wi-Fi, not the virtual adapter the VPN creates. Check which address is listening before assuming the port is blocked:

```shell
curl http://<windows-host-vpn-ip>:8000/health
curl http://<wsl-distro-vpn-ip>:8000/health
```

On the LAN segment itself this is unencrypted, session cookie included, so use it only on a network you trust and do not port-forward it. `APP_URL` is also what the Telegram bot puts in its messages, so a LAN address there produces links that work at home and fail elsewhere. If the host is on a VPN, prefer its VPN hostname there — it resolves from your devices in both places, and browsing by LAN address still works regardless, because the mutation check accepts whatever `Host` the request carries.

The app uses scrypt password hashes, random server-side sessions with hashed tokens, HttpOnly/SameSite cookies, same-origin mutation checks, upload validation, authenticated photo delivery, and account ownership checks. Login and photo requests have single-process limits. For larger public deployments, add a shared rate limiter, database migrations, a password recovery flow, and operational monitoring. SQLite is suitable for a small shared installation; multi-replica deployments need additional coordination and a shared database/storage service.

### Data, rebuilds, and backups

The container keeps nothing of its own. `compose.yaml` points both the database and the photo directory at `/app/data`, which is the named volume `nutrilens-data`:

```yaml
environment:
  DATABASE_URL: sqlite:////app/data/nutrilens.db
  UPLOAD_DIR: /app/data/uploads
volumes:
  - nutrilens-data:/app/data
```

A named volume is independent of both the image and the container, so rebuilding is non-destructive. These all keep your data:

```shell
docker compose up -d --build
docker compose up -d --force-recreate
docker compose down
docker compose restart
```

`down` on its own removes containers and networks and deliberately leaves named volumes alone. These delete the database and every uploaded photo:

```shell
docker compose down -v
docker volume rm <project>_nutrilens-data
docker system prune -a --volumes
```

`docker compose down -v` is the one to be careful with: it is a single character away from the safe command and is freely suggested in troubleshooting threads.

Note that the `environment:` block above is what makes any of this persistent. `.env` ships a *relative* `DATABASE_URL`, which inside a container would resolve into the writable layer and be lost on every recreate; Compose gives `environment:` precedence over `env_file:`, so the absolute path wins. Leave those two lines in place.

To back up, find the volume's real name first — Compose prefixes it with the project directory:

```shell
docker volume ls | grep nutrilens
```

Back up the database and uploads together while the application is stopped, or use SQLite's backup API for an online copy. Copying only a live `.db` file can miss changes held in WAL files. The API is available through the bundled Python, so no extra tooling is needed:

```shell
docker compose exec nutrilens python -c "import sqlite3; s=sqlite3.connect('/app/data/nutrilens.db'); d=sqlite3.connect('/tmp/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp nutrilens:/tmp/backup.db ./nutrilens-backup.db
docker compose cp nutrilens:/app/data/uploads ./nutrilens-uploads
```

The snapshot is written to `/tmp` rather than `/app/data` on purpose: a copy left inside the volume would be picked up by the next backup, and by the one after that.

Provider tokens and database backups should be handled as secrets.

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
```

The API and integration tests use temporary databases and mocked network requests. They cover authentication, account isolation, date boundaries, meal mutations, image privacy, sharing and revocation, Telegram photo/text logging and retries, calorie calculations, fasting/DST boundaries, reminder deduplication and opt-outs, legacy database migration, and response validation for both Gemini and OpenAI. No Telegram messages or paid AI requests are sent by these tests.

For optional browser checks, start a test server with demo mode enabled, install `playwright` with pip, run `python -m playwright install chromium`, then run `python tests/browser_smoke.py` using the same Python environment. Set `NUTRILENS_TEST_URL` to test a port other than 8000. This exercises the desktop/mobile interface, meal editing, calorie plans, fasting controls, sharing preferences, and CSV downloads. Screenshots are saved under `artifacts/`. Each run uses its own sample-data demo account.

`GET /health` checks the server/database. FastAPI's API documentation is at `/docs`; mutation requests require `X-Requested-With: NutriLens` and a signed-in session cookie. The web interface sets this header automatically.

```text
app/
  main.py          FastAPI routes, authentication, lifecycle
  models.py        Database models
  services.py      Progress, private image storage, meal operations
  vision.py        Image sanitation and Gemini/OpenAI estimates
  telegram_bot.py  Private chat bot and durable update handling
  planning.py      Calorie targets and local-time fasting windows
  reminders.py     Durable Telegram reminder worker
  migrations.py    Additive upgrades for existing installations
  static/          Responsive HTML, CSS, and JavaScript frontend
tests/             API and mocked integration tests
```

Implementation references: [Gemini generateContent API](https://ai.google.dev/api/generate-content), [Gemini image inputs](https://ai.google.dev/gemini-api/docs/image-understanding), [Telegram Bot API](https://core.telegram.org/bots/api), [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), and [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).
