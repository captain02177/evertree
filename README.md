# EverTree 3D 🌳

A cooperative 3D tree "Tamagotchi" built as a Telegram Mini App: Streamlit +
Three.js (WebGL) + SQLAlchemy (PostgreSQL/SQLite) + python-telegram-bot,
with Telegram Stars monetization.

## Features

- **Telegram auth**: clones the user's Telegram name/photo into their in-game profile.
- **Coop teams (1-5 players)**: dynamic role assignment across 5 roles — Suvchi
  (Waterer), Bog'bon (Gardener), Quyoshchi (Sunlight), Tozalovchi (Cleaner,
  interactive 3D pest-clearing), Parvarishchi (Nurturer).
- **Referral links**: `t.me/<bot>?startapp=team_<CODE>` auto-joins a team and
  assigns an open role.
- **6h/7h degradation timer**: tasks reset every 6h; a 1h warning phase follows;
  any missed task after 7h drops the tree 1 level. Difficulty scales — level N
  requires N completions per task per cycle.
- **Telegram Stars "Magical Shield"**: 50 ⭐ for 10 days of degradation immunity,
  rendered as a glowing golden force-field around the tree.
- **Hyper-real 3D tree**: PBR-ish materials, procedural bark texture, wind sway,
  falling particles, orbit camera (360°, pinch-zoom, touch pan), growth stages
  from a buried seed up through a golden/pink canopy, wildlife, and a fairytale
  cottage at Level 31+.

## Project layout

```
app.py                     Streamlit entry point (UI, session, tabs)
bot.py                     Telegram bot (/start, /shield, Stars payments)
database.py                SQLAlchemy models + all game logic (roles, timers, shield)
components/three_tree.py   Three.js HTML component (3D tree, pest raycaster)
requirements.txt
.env.example
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN, WEBAPP_URL, DATABASE_URL, etc.
```

Load the `.env` values into your shell (or use `python-dotenv` in your process
manager) before running either process:

```bash
export $(grep -v '^#' .env | xargs)
```

### Run the Mini App (Streamlit)

```bash
streamlit run app.py
```

Deploy it somewhere with a public HTTPS URL (Streamlit Community Cloud,
a VPS behind nginx + certbot, etc.) — Telegram WebApps require HTTPS.
Put that URL in `WEBAPP_URL`.

### Run the bot

```bash
python bot.py
```

In [@BotFather](https://t.me/BotFather):
1. Create/select your bot, run `/setmenubutton` or `/newapp` to attach the
   Mini App to `WEBAPP_URL`.
2. Enable **Payments → Telegram Stars** (no provider token needed — Stars
   payments use `provider_token=""` and `currency="XTR"`, already wired up
   in `bot.py`).

### Database

Defaults to local SQLite (`evertree3d.db`) if `DATABASE_URL` is unset — fine
for development. For production, point `DATABASE_URL` at Postgres, e.g.:

```
postgresql+psycopg2://user:password@host:5432/evertree3d
```

Tables are created automatically on first run via `database.init_db()`.

## How the pieces fit together

- The Mini App (`app.py`) reads `window.Telegram.WebApp.initDataUnsafe` via a
  small JS bridge injected at the top of the page, forwards the Telegram user
  fields into Streamlit through query params, and calls
  `database.get_or_create_user(...)` to register/login the player.
- A referral deep-link (`?startapp=team_<code>`) is consumed by
  `database.join_team_by_code`, which also re-runs `assign_roles` so the new
  member gets an open role.
- `database.check_degradation(db, team)` runs on every page load. It looks at
  the *previous* 6h cycle: if any role's required completions weren't met and
  no shield is active, the tree level drops by 1 and an alert string is
  returned for the UI to display.
- The 3D tree (`components/three_tree.py`) is a self-contained HTML/JS payload
  rendered via `streamlit.components.v1.html`. It reads `level`/`stage` to pick
  bark/leaf colors and stage-specific extras (grass, wildlife, cottage), and —
  when `pest_mode=True` — spawns clickable pest meshes with a raycaster;
  clearing them all posts a `pests_cleared` message back to the parent window.
- Telegram Stars payments are bot-side only (`bot.py`): the Shop tab in the
  Mini App links out to `t.me/<bot>?start=shield_<team_id>`, which triggers
  `send_shield_invoice`. On `successful_payment`, `database.activate_shield`
  is called, extending any existing shield by 10 days.

## Notes / production hardening ideas

- Add a scheduled job (e.g. `python-telegram-bot`'s `JobQueue`, or a cron +
  `check_degradation` sweep over all teams) so degradation is evaluated even
  when no one opens the app — currently it's lazily checked on page load.
- Rate-limit `complete_task` per role/user if you want to prevent one player
  from spamming a task alone to hit the scaling requirement.
- Add HTTPS-only cookie/session validation of Telegram `initData` (HMAC check
  against the bot token) before trusting `tg_id` in production — the bridge
  here trusts the client-supplied query params, which is fine for prototyping
  but should be replaced with server-side `initData` verification.
