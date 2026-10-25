# Muse + Memory Layer for Life — Project Guide

The single entry point for working on this repository: what the system is, how to run it, where the code lives, what is done, and what is left. It links to deeper documents instead of repeating them.

_Last updated: 25 October 2026._

---

## 1. What this is

Two projects share this folder:

- **Muse** (the repository root) is an Expo / React Native app for iOS, Android, and web. Users sign in with Google and talk to **Cooper**, an AI assistant that can browse the web, use their connected apps (Gmail, Slack, …), and run tasks on a schedule.
- **Memory Layer for Life** ([`memory-layer-for-life/`](../memory-layer-for-life/README.md)) is a FastAPI service. It started as a personal "second brain" that turns notes into structured, source-backed memories (Phase 1 is done). It is now also **the backend of the Muse app**: sign-in verification, chat, schedules, app connections, usage limits, push notifications, and account deletion all live here.

```
 ┌─────────────── Muse app (Expo) ───────────────┐            ┌──────────── memory-layer-for-life (FastAPI) ─────────────┐
 │ Google sign-in via Supabase Auth ─► token     │  Bearer    │ verifies the token (Supabase JWKS, ES256)               │
 │ src/lib/api/*  ─────────────────────────────────────────►  │ /me /threads /schedules /tools /activity (assistant app) │
 │ reply stream (NDJSON over expo/fetch)  ◄────────────────── │ Cooper = Claude Haiku 5.5 tool loop                      │
 └───────────────────────────────────────────────┘            │   ├─ Browserbase (cloud browser)   ├─ Composio (apps)   │
                                                              │ scheduler (claims due slots in PostgreSQL)               │
 ┌──────── Supabase ────────┐                                 │ /ingestion /memories /processing … (memory layer)        │
 │ Auth only: Google OAuth, │                                 │ console UI at /  ·  API docs at /docs                    │
 │ JWKS signing keys        │                                 └───────────────────────┬──────────────────────────────────┘
 └──────────────────────────┘                                                         │ SQLAlchemy + Alembic
                                                              ┌───────────────────────▼──────────────────────────────────┐
                                                              │ PostgreSQL on Neon — 25 tables, row level security on all │
                                                              └───────────────────────────────────────────────────────────┘
```

Key choices, each recorded as an architecture decision (ADR) in [`DECISIONS.md`](../memory-layer-for-life/context%20for%20agent/DECISIONS.md):

| Decision                                                                                                                         | Why                                                                                                                                   | ADR           |
| -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| The app has no server code; this API is its backend                                                                              | One place for business logic, tested and migrated like the rest                                                                       | 026           |
| Supabase is used for sign-in only; data lives on Neon                                                                            | The owner's choice; the API uses the Supabase secret key only to delete a sign-in when an account is deleted                          | 026, 027, 034 |
| Tokens verified locally against Supabase's public keys                                                                           | No per-request call to Supabase; asymmetric keys only                                                                                 | 027           |
| Cooper runs on Claude in a provider-independent loop                                                                             | One provider, one cost log; replies stream and are stored server-side                                                                 | 028           |
| Schedules are claimed in PostgreSQL and run at most once                                                                         | A run may send a message; never send it twice                                                                                         | 029           |
| Row level security on every table                                                                                                | Keeps data closed even if the database is served through a Data API                                                                   | 030           |
| One reply per thread, held by a lease in the database                                                                            | Holds across every API process; a crashed reply's lease expires                                                                       | 032           |
| Attached files go to Claude once and are not stored                                                                              | No object storage or retention rules needed yet                                                                                       | 033           |
| Deleting an account revokes apps first, the sign-in last                                                                         | No third-party access outlives the account; a failure can be retried                                                                  | 034           |
| Push notifications through Expo's push service                                                                                   | One API for iOS and Android; no Apple or Google credentials here                                                                      | 035           |
| 40 prompts per user per day, counted in `daily_usage`                                                                            | A cost guard the owner chose; checked and counted in one atomic statement                                                             | 036           |
| App users' chats become their own memories                                                                                       | Evidence, entities, and memories carry an owner; resolution never crosses owners; only the user's words are captured                  | 037           |
| Memory search: words, names, and meaning, fused by rank                                                                          | Each kind of match finds what the others miss; filters and the owner apply inside every leg; embeddings are a derived index per model | 038           |
| Users manage their memories: every change in a history, corrections as new versions, sensitive memories never reach a model      | A memory store nobody can correct or delete is not trustworthy; the old text and its evidence stay inspectable                        | 044           |
| Life state from memories; reminders and a daily brief sent by the API, composed without a model                                  | What is due is a query, not a guess; a template brief costs nothing and cannot be wrong about dates                                   | 045           |
| Insights computed from memories, each naming its evidence; feedback per insight                                                  | Counts are exact and free; feedback hides what does not help and measures usefulness                                                  | 046           |
| WhatsApp imports in two steps with a cost estimate; photos and PDFs read into evidence; calendar events as plans without a model | Each extraction costs money, so the user decides how many; structured events need no model                                            | 047           |
| Schedules: once, daily, weekdays, monthly, every N hours; edit, delete; late slots skipped                                       | Covers what people actually ask for; a run hours late helps nobody, so it is recorded as skipped                                      | 043           |

---

## 2. Repository layout

```
memory-app/                              ← project root (the Expo app); no git repository yet
├── src/                                 ← app source (section 5)
├── docs/
│   ├── PROJECT_GUIDE.md                 ← this file
│   ├── BACKEND.md                       ← app ↔ backend contract in detail
│   ├── DEPLOYMENT.md                    ← environments, Fly.io, secrets, app builds, operations
│   ├── FEATURE_GUIDE.md                 ← every feature: how it works, how to test it, what is left
│   └── CODEBASE_EXPLANATION.md          ← file-by-file UI guide
├── assets/                              ← icons, splash, Cooper mascot
├── app.json · package.json · tsconfig.json · metro.config.js
├── .env / .env.local                    ← app configuration (section 4.1), gitignored
├── AGENTS.md                            ← rules for contributors and coding agents
└── memory-layer-for-life/               ← the backend (section 6)
    ├── app/                             ← Python package (layered: api, services, repositories, models, domain, integrations)
    ├── migrations/versions/             ← Alembic revisions 001–010
    ├── tests/                           ← unit, contract, golden, integration
    ├── scripts/                         ← workers and one-off commands
    ├── evaluation/ · golden.jsonl       ← memory-extraction quality evaluation
    ├── frontend/                        ← React test console (served at / when built)
    ├── context for agent/               ← vision, architecture, ADRs, status, roadmap
    └── README.md · RUN_LOCALLY.md · PHASE1_REPORT.md · .env.example
```

The backend folder is excluded from TypeScript (`tsconfig.json`) and from Metro (`metro.config.js`), so it never leaks into the app bundle or its typed routes.

---

## 3. Running it

### 3.1 Prerequisites

| Need                              | For                              | Notes                                                                                                                                           |
| --------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Node.js 22.13+ (or 24.3+) and npm | The app; required by Expo SDK 58 | Node 22.23 is in use                                                                                                                            |
| Python 3.12                       | The backend                      | `C:\Python312` on this machine                                                                                                                  |
| Expo Go **for SDK 58** on a phone | Testing on a device              | Same Wi-Fi as the computer. Until the store versions update (a few weeks after 21 Oct 2026), install it from [expo.dev/go](https://expo.dev/go) |
| Neon database                     | Backend data                     | `DATABASE_URL` in the backend `.env`                                                                                                            |
| Supabase project                  | Sign-in                          | Google provider enabled                                                                                                                         |
| Anthropic API key                 | Cooper                           | Required for chat and schedules                                                                                                                 |
| Composio / Browserbase keys       | App connections / browser        | Optional; tools are hidden without them                                                                                                         |
| An EAS development build          | Push notifications, voice input  | Expo Go cannot load either; the app runs without them there                                                                                     |
| Portable PostgreSQL 16            | Backend tests only               | See [RUN_LOCALLY.md](../memory-layer-for-life/RUN_LOCALLY.md) §2–3                                                                              |

### 3.2 One-time setup

**Backend.**

```powershell
cd memory-layer-for-life
# Dependencies (uv is installed in the venv; `make install` does the same)
.\.venv\Scripts\python.exe -m uv sync --all-extras
# Configuration: copy .env.example to .env and fill it in (section 4.2)
# Schema: bring the database to the latest revision (Neon is at 014)
# Revision 009 needs pgvector: Neon has it; a local PostgreSQL needs scripts\install_pgvector_windows.ps1
.\.venv\Scripts\python.exe -m alembic upgrade head
```

There is no `.venv` in the folder: it was deleted on 25 October 2026 so the project copies quickly between computers. Create it once on each computer that runs the backend or its tests (Python 3.12 needed): `py -3.12 -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install uv`, then `.\.venv\Scripts\python.exe -m uv sync --all-extras`. Deploying needs only Docker (DEPLOYMENT.md §0); call tools as `python -m <tool>`.

**App.**

```powershell
npm install
```

Then create `.env` and `.env.local` as in section 4.1.

**Supabase dashboard** (Authentication → URL Configuration → Redirect URLs):

- `exp://**`: Expo Go during development.
- `memory://**`, `memory-staging://**`, `memory-dev://**`: the production, staging, and development builds (section 3.7).

Supabase rejects any redirect address whose host is a raw IP address, even when it is listed. That is why `.env.local` serves the app under a hostname (section 4.1).

### 3.3 Everyday: start both and open the app

```powershell
# Terminal 1 — backend, reachable from the phone (Windows: allow Python on private networks)
cd C:\dev\memory-app\memory-layer-for-life
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — the app
cd C:\dev\memory-app
npx expo start
```

In Expo Go, scan the QR code or enter `exp://192-168-1-2.nip.io:8081` (your computer's address with dashes). Add `-c` to `npx expo start` after changing `.env`, `.env.local`, or `metro.config.js`. The app finds the backend at the same host on port 8000.

Useful addresses while it runs:

| Address                                     | What                                                                     |
| ------------------------------------------- | ------------------------------------------------------------------------ |
| `http://localhost:8000/docs`                | Interactive API documentation                                            |
| `http://localhost:8000/`                    | Memory-layer test console                                                |
| `http://localhost:8000/api/v1/health/ready` | Health and database check                                                |
| `http://localhost:8081`                     | The app in a web browser (the bundle builds; not yet tried in a browser) |

### 3.4 Check that it works

1. `GET /api/v1/health/ready` answers `{"status":"ready","database":"connected"}`.
2. The backend's startup line `application_ready` shows `sign_in_configured=True assistant_configured=True scheduler=True`. `apps_configured` is true only with a Composio key.
3. In the app: sign in, send "hi", and see the reply stream in and stay after a reload.
4. Ask "every morning at 8 summarize AI news", confirm the card, and find the schedule in the Tasks tab. "Run" there posts a result into the chat, and the result appears in the Feed.
5. Settings shows "N of 40 prompts used" for today.

### 3.5 Tests and quality checks

| Where                   | Command                                                                                        | Current result                                                                                                    |
| ----------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Backend, all tests      | `.\.venv\Scripts\python.exe -m pytest tests -q`                                                | 1,693 tests pass (25 October); needs the local `second_brain_test` database                                       |
| Backend coverage        | `python -m coverage run -m pytest tests -q; python -m coverage report`                         | 98 %                                                                                                              |
| Backend lint and format | `python -m ruff check .` and `python -m ruff format --check .`                                 | Clean                                                                                                             |
| Backend types           | `python -m mypy` (strict)                                                                      | Clean, 170 files                                                                                                  |
| App types               | `npx tsc --noEmit`                                                                             | Clean                                                                                                             |
| App lint                | `npm run lint` (ESLint, `eslint-config-expo`)                                                  | Clean                                                                                                             |
| App unit tests          | `npm test` (Jest, `jest-expo`)                                                                 | 19 suites, 158 tests pass                                                                                         |
| App release bundle      | `npx expo export --platform android`                                                           | Builds (Hermes)                                                                                                   |
| App project health      | `npx expo-doctor`                                                                              | 20 of 20 checks pass                                                                                              |
| App native bundle       | Metro: `/node_modules/expo-router/entry.bundle?platform=android&…` while `npx expo start` runs | Builds                                                                                                            |
| App web bundle          | The same with `platform=web`                                                                   | Builds in development; `npx expo export --platform web` failed earlier with "too many open files" on this machine |

The backend test setup blanks every external key and forces the test database, so no test reaches Anthropic, Supabase, Composio, Browserbase, or real data. Assistant-app tests use a scripted model, a token verifier, and in-memory Composio, Browserbase, Expo push, and Supabase admin clients (`tests/support/assistant.py`). The app's Jest tests cover the API client, stream parsing, formatting, attachment checks, transcripts, and the agent profile; there are no end-to-end tests (section 10).

### 3.6 Troubleshooting

| Symptom                                                       | Cause                                                                                               | Fix                                                                                                                          |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Google sign-in ends on `localhost:3000`                       | Supabase did not accept the redirect and fell back to its Site URL; raw-IP hosts are always refused | Allow `exp://**`; set `REACT_NATIVE_PACKAGER_HOSTNAME` in `.env.local` and open the app through that hostname                |
| Expo exits: "Refused to load personal environment variables"  | `REACT_NATIVE_PACKAGER_HOSTNAME` is in `.env`                                                       | Move it to `.env.local`                                                                                                      |
| The app cannot reach the backend                              | Backend bound to localhost, a firewall, or a changed IP                                             | Start uvicorn with `--host 0.0.0.0`; allow Python in Windows Firewall; update `.env.local` if the IP changed                 |
| A toast says "Please sign in again"                           | Session missing or expired (API answered 401)                                                       | Sign out and in; check `SUPABASE_URL` in the backend `.env`                                                                  |
| Code `AUTHENTICATION_NOT_CONFIGURED` (503)                    | `SUPABASE_URL` unset in the backend                                                                 | Set it                                                                                                                       |
| Code `PROVIDER_NOT_CONFIGURED` (503)                          | No Anthropic key                                                                                    | Set `ANTHROPIC_API_KEY`                                                                                                      |
| Code `ASSISTANT_PROVIDER_BILLING`                             | The Anthropic account has no credit                                                                 | Add credit                                                                                                                   |
| Code `INTEGRATION_NOT_CONFIGURED`                             | Composio or Browserbase key missing                                                                 | Add the key, or ignore                                                                                                       |
| Code `QUOTA_EXCEEDED` (429)                                   | The user used today's 40 prompts                                                                    | Wait for the reset (UTC midnight), raise `ASSISTANT_DAILY_PROMPT_LIMIT`, or set `app_users.daily_prompt_limit` for that user |
| Backend integration tests error with `ConnectionRefusedError` | The local test PostgreSQL is not running (it does not start with Windows)                           | `pg_ctl start`, see [RUN_LOCALLY.md](../memory-layer-for-life/RUN_LOCALLY.md#everyday-use)                                   |
| "Cooper ran into an unexpected problem"                       | A bug; the backend log has a `chat_turn_crashed` traceback                                          | Read the traceback; the user message is kept                                                                                 |
| `/health/ready` returns 503                                   | Database unreachable                                                                                | Check `DATABASE_URL`, network, Neon status                                                                                   |
| Metro "EMFILE: too many open files"                           | Windows file-handle limit under load                                                                | Add `--max-workers 2`, close other dev servers                                                                               |

More: [RUN_LOCALLY.md § Troubleshooting](../memory-layer-for-life/RUN_LOCALLY.md).

### 3.7 Deploy, and install it on a phone

The full runbook is [DEPLOYMENT.md](DEPLOYMENT.md). **Its section 0 is the free setup**: Render's free web service running the Docker image (`deploy/push-image.ps1`, `deploy/render.env.example`, migrations on start), Neon's free plan, and an uptime ping. Background pacing (`BACKGROUND_IDLE_INTERVAL_SECONDS`, `app/services/pacing.py`) lets the database sleep between jobs without anything running late. The rest describes the full setup: three environments (development on this laptop, staging and production on Fly.io), each with its own Neon database and keys; the Docker image; secrets; migrations; rollback; logs; costs. In short:

- **Backend:** `memory-layer-for-life/fly.staging.toml` and `fly.production.toml` (settings that are not secret), secrets in Fly only, and `.\deploy\deploy.ps1 staging|production` (checks, then deploys and smoke-tests). A deployed API (`ENVIRONMENT=staging|production`) refuses to start half-configured, trusts only `OPERATOR_API_KEY` on operator routes, can restrict sign-in to `ACCESS_ALLOWED_EMAILS`, hides its docs in production, and refuses bodies over 25 MB.
- **App:** EAS profiles in `eas.json`. Each variant is its own app (`app.config.ts`, `APP_VARIANT`), so they install side by side:

| Profile      | App                                                              | Backend                                                  |
| ------------ | ---------------------------------------------------------------- | -------------------------------------------------------- |
| `local`      | Muse Dev (`com.museai.app.dev`, scheme `memory-dev`)             | `http://192.168.1.2:8000`, this laptop on the same Wi-Fi |
| `staging`    | Muse Staging (`com.museai.app.staging`, scheme `memory-staging`) | `https://muse-cooper-api-staging.fly.dev`                |
| `production` | Muse (`com.museai.app`, scheme `memory`), APK                    | `https://muse-api.onrender.com` (free setup)             |
| `store`      | Muse, AAB for Google Play                                        | production                                               |

```powershell
npx eas-cli login
npx eas-cli build -p android --profile production   # first time: Yes to "create an EAS project" and "generate a new Android Keystore"
```

- Supabase must allow `memory://**`, `memory-staging://**`, and `memory-dev://**` (section 3.2).
- Android push needs Firebase: `google-services.json` stored in EAS as the secret file `GOOGLE_SERVICES_JSON`, plus the FCM V1 key in `eas credentials` (DEPLOYMENT.md §6.4).
- The feature-by-feature test guide is [FEATURE_GUIDE.md](FEATURE_GUIDE.md).

---

## 4. Configuration reference

### 4.1 App (`.env`, `.env.local`, both gitignored)

| Variable                               | File         | Purpose                                                                                     |
| -------------------------------------- | ------------ | ------------------------------------------------------------------------------------------- |
| `EXPO_PUBLIC_SUPABASE_URL`             | `.env`       | Supabase project, for sign-in                                                               |
| `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `.env`       | Public key, for sign-in only                                                                |
| `EXPO_PUBLIC_API_URL`                  | `.env`       | Optional. Backend origin; defaults in development to the dev server's host on port 8000     |
| `REACT_NATIVE_PACKAGER_HOSTNAME`       | `.env.local` | Hostname Expo serves under (`192-168-1-2.nip.io`), so Supabase accepts the sign-in redirect |

Only `EXPO_PUBLIC_*` values reach the app bundle, and all of them are public by design. Never put a secret in one; backend secrets live in `memory-layer-for-life/.env`.

### 4.2 Backend (`memory-layer-for-life/.env`)

Every setting with its default is in [`.env.example`](../memory-layer-for-life/.env.example) and the [README](../memory-layer-for-life/README.md#environment-configuration). The ones that matter day to day:

| Group                  | Variables                                                                                                                                               | Current value / note                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Database               | `DATABASE_URL`                                                                                                                                          | Neon, `postgresql+asyncpg://…?ssl=require`                                                                            |
| Model                  | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ASSISTANT_MODEL`                                                                                               | Haiku 5.5 for both memory extraction and Cooper                                                                       |
| Sign-in                | `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_SECRET_KEY`                                                                                              | The Supabase project; JWKS is derived when unset; the secret key is used only to delete a sign-in on account deletion |
| Assistant limits       | `ASSISTANT_EFFORT`, `ASSISTANT_MAX_TOKENS`, `ASSISTANT_MAX_STEPS`, `ASSISTANT_HISTORY_MESSAGES`, `CHAT_MAX_MESSAGE_CHARS`                               | medium, 8000, 10, 40, 8000                                                                                            |
| Memories from chats    | `MEMORY_CAPTURE_ENABLED`                                                                                                                                | On; users can turn it off in the app                                                                                  |
| Memory search          | `VOYAGE_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `RETRIEVAL_RERANK_MODEL`, `RETRIEVAL_MIN_SEMANTIC_SIMILARITY`, `RETRIEVAL_INDEXER_ENABLED` | Key set. voyage-4 at 1024 dimensions, no reranker, 0.3, on                                                            |
| Cost currency          | `USAGE_CURRENCY`, `USAGE_CURRENCY_PER_USD`                                                                                                              | INR at 88 per dollar (a fixed rate: costs are estimates)                                                              |
| Daily limit            | `ASSISTANT_DAILY_PROMPT_LIMIT`                                                                                                                          | 40 prompts per user per UTC day (0: unlimited); `app_users.daily_prompt_limit` overrides it for one user              |
| Chat files and replies | `CHAT_MAX_ATTACHMENTS`, `CHAT_MAX_ATTACHMENT_BYTES`, `CHAT_TURN_LEASE_SECONDS`                                                                          | 3 files, 5 MB each, 600 s                                                                                             |
| Push                   | `PUSH_NOTIFICATIONS_ENABLED`, `EXPO_PUSH_ACCESS_TOKEN`                                                                                                  | On; the token is optional                                                                                             |
| Scheduler              | `SCHEDULER_ENABLED`, `SCHEDULER_POLL_SECONDS`, `SCHEDULER_BATCH_SIZE`, `SCHEDULER_CONCURRENCY`, `SCHEDULE_RUN_STALE_SECONDS`                            | true, 60, 10, 3, 1800                                                                                                 |
| Integrations           | `COMPOSIO_API_KEY`, `COMPOSIO_AUTH_CONFIGS`, `BROWSERBASE_API_KEY`, `BROWSERBASE_RUN_TIMEOUT_SECONDS`, `INTEGRATION_TIMEOUT_SECONDS`                    | Composio key set (auth configs found or created on first connect, ADR-039); Browserbase key not set                   |
| Memory pipeline        | `EXTRACTION_*`, `PIPELINE_*`, `INGESTION_*`, `DEFAULT_TIMEZONE`                                                                                         | `DEFAULT_TIMEZONE` is not set, so it defaults to UTC (section 11.1)                                                   |
| Web                    | `CORS_ORIGINS`                                                                                                                                          | Includes `http://localhost:8081` for Expo web                                                                         |

`SUPABASE_SECRET_KEY` was shared in a chat transcript. The API now uses it (account deletion), so roll it in Supabase and put the new key in `.env`.

---

## 5. Frontend: where the code is

```
src/
├── app/                                  Expo Router screens (file = route)
│   ├── _layout.tsx                       Root stack, theme, toasts, notification banners and taps
│   ├── index.tsx                         Google sign-in (Supabase OAuth → session → /(tabs)/chat)
│   ├── auth/callback.tsx                 Landing screen for the OAuth deep link
│   ├── home.tsx                          Redirect to /(tabs)/chat
│   ├── tools.tsx                         Tools & Connections: connect / check / reconnect / disconnect
│   ├── notifications.tsx                 Notification switch and push-token registration
│   ├── help.tsx                          FAQ and the feedback form
│   ├── memories/index.tsx                Memories: All (search, timeline, capture switch), To review, People; + to write one
│   ├── memories/[id].tsx                 One memory: evidence, chat link, people, earlier versions, history; accept/edit/wrong/delete
│   ├── people/[id].tsx                   A person and their memories; rename, merge
│   ├── import.tsx                        Import a WhatsApp chat: pick the export, choose who you are, see the cost, start; progress
│   └── (tabs)/
│       ├── _layout.tsx                   Session guard, tab dock, header, drawer, header menu (clear / delete / share)
│       ├── chat.tsx                      Chat: history with "load earlier", streamed Markdown replies, cards, files, voice
│       ├── feed.tsx                      "For you" insights (thumbs up/down), then finished scheduled runs; tap opens the chat
│       ├── ideas.tsx                     Templates; tapping prefills the chat input
│       ├── tasks.tsx                     To do (open items by due date) and Schedules (list, "+ New", pause/resume, run now)
│       ├── settings.tsx                  Today's prompts and cost with a collapsible cost history, links, delete account, sign-out
│       └── index.tsx                     Redirect to chat
├── components/
│   ├── chat/                             MarkdownText (react-native-marked), AttachmentChips
│   ├── common/                           Header, mascot, sidebar drawer, menus, agent editor, browser preview
│   ├── settings/CostHistory.tsx          Collapsible daily / weekly / monthly cost columns (react-native-svg)
│   ├── tasks/ScheduleFormModal.tsx       Create and edit a schedule (with DateTimeFields)
│   ├── tasks/TodoPanel.tsx               The To do list: check off, snooze, due dates, stop tracking; TodoEditorModal adds one
│   ├── chat/LifeCards.tsx                Reminder and daily-brief cards (Done, Snooze, Not yet)
│   ├── feed/InsightsSection.tsx          Insight cards with evidence counts and feedback
│   ├── settings/ProactiveSettings.tsx    Daily brief, reminders, quiet hours (on the Notifications screen)
│   ├── tools/MemorySourceToggle.tsx      "Use for memories" on the Google Calendar sheet
│   ├── memories/                         MemoryRow, MemoryEditorModal, ReviewCards (suggestions, held-back)
│   └── tools/                            ToolCard, ManageToolModal
├── context/                              ToastContext, AgentProfileContext (saved name/icon/colour), ChatSessionContext
├── hooks/                                useRequireSession (sign-in guard), useVoiceInput, useChatKeyboard (input rides the keyboard)
├── lib/
│   ├── env.ts                            Reads EXPO_PUBLIC_* and derives the API URL
│   ├── supabase.ts                       Sign-in only; getAccessToken(); refreshes the token while the app is active
│   ├── api/                              The only way the app reaches data
│   │   ├── client.ts                     apiRequest(): bearer token, JSON, typed ApiError; signs out on a 401
│   │   ├── types.ts                      Wire types, exactly as the API sends them
│   │   ├── chatStream.ts                 streamReply(): NDJSON over expo/fetch
│   │   └── threads.ts · schedules.ts · tools.ts · me.ts · memories.ts · life.ts · insights.ts · sources.ts · activity.ts
│   ├── attachments.ts · attachmentPicker.ts   File checks (type, count, size) and the picker
│   ├── speech.ts                         On-device speech recognition; detects Expo Go without crashing
│   ├── pushNotifications.ts              Permission, Expo push token, notification taps
│   ├── transcript.ts                     The shared chat transcript
│   ├── usageChart.ts                     Cost formatting (₹ by default), axis ticks, period labels for the chart
│   ├── memories.ts                       Memory labels, timeline sections, history and review wording
│   ├── dataExport.ts                     Saves GET /me/export to a file and opens the share sheet
│   ├── life.ts                           Due and reminder labels, quick due dates and snoozes, search snippets
│   ├── timezoneSync.ts                   Reports the phone's timezone after sign-in
│   ├── imports.ts                        Import planning: conversations, cost estimate, progress text
│   └── formatSchedule.ts · formatTime.ts · scheduleForm.ts · dialogs.ts · navigation.ts
├── types/                                UI types; toUiMessage() maps API messages to bubbles
└── constants/                            Colors, theme, agent icons, template data
```

Rules, enforced by review and spelled out in [AGENTS.md](../AGENTS.md):

- All data goes through `src/lib/api`. The app never queries Supabase tables, calls Edge Functions, or adds Expo API routes.
- Supabase is used for `auth` only.
- Wire types mirror the backend and are mapped to UI types at the screen.
- `ApiError.message` is written for people; show it in toasts.

How a message flows: `chat.tsx` adds two optimistic bubbles, then `streamReply()` posts to `/threads/{id}/messages`. Each event updates the agent bubble: `turn_started` swaps in the stored user message, `text_delta` appends text, `tool_started` sets the typing label, `browser` and `connect_link` add cards, and `final` swaps in the stored reply. If the server refuses the message before streaming (409, 422, 429, 503), both bubbles are removed and the text returns to the input.

---

## 6. Backend: where the code is

Layered, as in [ARCHITECTURE.md](../memory-layer-for-life/context%20for%20agent/ARCHITECTURE.md): routers are thin, services own transactions, repositories run queries, the domain holds rules, and only integrations talk to the outside world.

| Layer                   | Memory layer (Phase 1)                                                                                                                  | Assistant app (new)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/api/v1/endpoints/` | `ingestion`, `processing`, `memories`, `llm_calls`, `playground`, `evaluations`, `console`, `reports`, `health`                         | `me` (profile, usage, push tokens, export, deletion), `my_memories` (the user's memories and review inbox), `people`, `threads` (incl. the NDJSON stream), `schedules`, `activity`, `feedback`, `tools`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `app/api/`              | `dependencies.py` (services)                                                                                                            | `get_principal` (bearer → verified user), `app_mappers.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `app/services/`         | `ingestion`, `processing/*` (runner, extraction, resolution, memory builder, replay), `evaluations`, `playground`, `queries`, `reports` | `users`, `chat`, `chat_turns` (turn orchestration), `assistant/` (agent loop, tools, prompts, context), `schedules`, `schedule_runs` (runner, dispatcher, loop), `tool_connections`, `usage` (daily limit, meter, cost history), `memory_capture` (chats into the memory pipeline), `retrieval/` (search engine, memory documents, indexer), `memories` (lifecycle, corrections, merges), `memory_review` (inbox, suggestions, held-back), `people`, `export`, `life_state` (overview, done/drop, reminders, brief), `proactive` (reminder and brief loop), `insights`, `imports` (WhatsApp), `file_capture` (photos and PDFs), `source_sync` (calendar), `notifications` (push), `account` (deletion), `background` |
| `app/repositories/`     | messages, processing runs, memories, entities, call log, evaluations, playground                                                        | `user_`, `chat_`, `schedule_`, `tool_connection_`, `usage_`, `push_token_`, `owned_memory_repository` (account deletion), `retrieval_repository` (one query per search leg), `embedding_repository`, `memory_review_repository` (alike pairs), `people_repository`, `export_repository`, `life_repository`, `insight_repository`, `import_repository`                                                                                                                                                                                                                                                                                                                                                                |
| `app/models/`           | 16 tables (raw messages → memories, call log, evaluations)                                                                              | `app_user`, `chat_thread`, `chat_message`, `scheduled_task`, `scheduled_task_run`, `tool_connection`, `daily_usage`, `push_token`, `feedback`, `memory_embedding`, `memory_event`, `insight_feedback`, `chat_import`, `synced_item`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `app/domain/`           | enums, errors, model catalog, identity, run state                                                                                       | `principal`, `schedule_rules` (timezone/DST-correct), `tool_catalog` (apps and auth configs), `attachments`, `retrieval` (query rules, rank fusion)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `app/integrations/`     | `anthropic_client`, `anthropic_calls` (call observer → cost log), `extraction/`                                                         | `supabase_auth` (JWKS verifier), `supabase_admin` (identity deletion), `assistant/` (step interface + Anthropic streaming adapter), `composio`, `browserbase`, `expo_push`, `embeddings/` (Voyage embeddings and reranking)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `app/schemas/`          | extraction contract, memory, console, …                                                                                                 | `app.py` (requests, responses, stream events), `message_metadata.py` (cards on a message)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `app/bootstrap.py`      | Composition root: builds every service once per process                                                                                 | Wires the HTTP client, verifier, integrations, toolbox, scheduler                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `app/main.py`           | App factory and lifespan                                                                                                                | Starts/stops the schedule loop, the memory index loop, the pipeline loop (retries failed saves), the proactive loop (reminders, briefs), and the source sync loop (calendar)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `scripts/`              | `process_pending`, `run_golden_eval`, `import_eval_reports`, `check_anthropic_connection`                                               | `run_schedules` (stand-alone dispatcher), `index_memories`, `run_retrieval_eval`, `install_pgvector_windows.ps1`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

How a chat turn runs (`services/chat_turns.py` → `assistant/agent.py`):

1. The request is checked: the message and its files are valid, a model is configured, the thread is the user's, and no reply holds the thread's lease. In one transaction, today's prompt is counted (or the request is refused with 429), the lease is taken, and the user message is stored.
2. The turn starts as background work, so it finishes and saves even if the phone disconnects. The response streams from a queue.
3. Each step calls Claude with the cached instructions, the per-request context (time, connected apps), the history, and the tools. Text streams out as `text_delta`. Tool calls run one after another, and their results go back to the model, for at most `ASSISTANT_MAX_STEPS` steps.
4. The reply and its cards are stored and the lease is released in one transaction, then `final` is sent. Every model call is written to `llm_calls` with its tokens, estimated cost, and user.

Cooper's tools (`services/assistant/tools.py`):

| Tool                              | Offered when                      | Does                                                                                                                                                                           |
| --------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `propose_schedule`                | Always (chat only)                | Attaches a schedule proposal card; nothing is created until the user confirms                                                                                                  |
| `browse_web`                      | Browserbase key set               | Runs a Browserbase agent task, streams its live view, returns the result                                                                                                       |
| `find_app_tools` / `run_app_tool` | Composio key set                  | Searches and runs actions in a connected app through a Tool Router session                                                                                                     |
| `connect_app`                     | Composio key set (chat only)      | Starts a Composio connect link and shows a Connect card                                                                                                                        |
| `search_memories`                 | Always (chats and scheduled runs) | Searches the user's own memories; returns each with its kind, date, review status, and the user's own words, and tells Cooper to say so rather than guess when nothing matches |

Safety rules in code: tool input is validated as untrusted, a tool slug must belong to its app, and write actions in chat are runtime-gated by explicit user approval (`confirmed=true` plus an approval signal on the latest user message). A scheduled run has nobody to ask, so it may change data only in the app it delivers to (`WritePolicy.DELIVERY_APP_ONLY`).

How a schedule runs (`services/schedule_runs.py`): every 60 seconds the dispatcher locks due schedules (`FOR UPDATE SKIP LOCKED`), inserts one run per slot, and moves `next_run_at` to the next slot after now, all in one transaction. Unique indexes allow one run per slot and one running run per schedule. Runs are never retried. Interrupted runs are marked failed after 30 minutes. A run counts as a prompt once its delivery checks pass; over the daily limit it fails without calling the model. Results go to the source thread, or the main thread for schedules made with "+ New" (delivery `chat`), or through the delivery app, and the owner's devices get a push notification.

---

## 7. Data model

Fourteen Alembic revisions build the schema. A test compares the models with the migrated schema, and another checks that every table has row level security.

| Revision | Adds                                                                                                                                                                                                           |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 001–002  | Memory layer core: `raw_messages` (immutable evidence), `processing_runs` and events, `extraction_results`, `entities`, `entity_mentions`, `memories`, `memory_sources`, `memory_entities`, `memory_relations` |
| 003      | `llm_calls` (every model call: tokens, cost, never content), `playground_runs`, `evaluation_runs`, `evaluation_case_results`                                                                                   |
| 004      | Assistant app: `app_users` (Supabase id), `chat_threads` (one main per user), `chat_messages` (JSONB `metadata` for cards), `scheduled_tasks`, `scheduled_task_runs`, `tool_connections`                       |
| 005      | Row level security on all 22 tables (no policies; the API connects as owner)                                                                                                                                   |
| 006      | Assistant profile and notification setting on `app_users`, `llm_calls.user_id`, `chat_threads.turn_lease_until`, `push_tokens`, `feedback`                                                                     |
| 007      | `daily_usage` (prompts per user per UTC day), `app_users.daily_prompt_limit`                                                                                                                                   |
| 008      | `owner_id` on `raw_messages`, `entities`, `memories` (empty: the operator's store); `app_users.memory_capture_enabled`                                                                                         |
| 009      | Retrieval: pgvector and pg_trgm, `memories.search_document`, `memory_embeddings`                                                                                                                               |
| 010      | Scheduling v2: `weekdays`, `day_of_month`, `start_date`, `interval_hours`; statuses `completed` and `skipped`                                                                                                  |
| 011      | `memory_events`, `memories.created_by`, trigram index on `normalized_content`, user-linked sources, run event `reviewed`; sensitive embeddings removed                                                         |
| 014      | `chat_imports`, `synced_items`; source sync columns on `tool_connections`; `created_by = app`; call log `transcription` / `capture`                                                                            |
| 013      | `insight_feedback` (useful or not, per user and insight)                                                                                                                                                       |
| 012      | Life state: `memories.due_on`, `remind_at`, `closed_at`, `close_reason`; brief, reminder, quiet-hours, and timezone preferences on `app_users`; `chat_messages.search_document`                                |

Every assistant-app lookup is scoped to the signed-in user, so another user's record reads as 404. The memory-layer tables have **no user column**: they belong to one owner (section 12.3).

---

## 8. API at a glance

Full contract: `/docs` on the running backend; app-side details in [BACKEND.md](./BACKEND.md).

| Area         | Routes                                                                                                                                                                             | Sign-in                                   |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------- | -------- | ------- | ----- | ------------------------------------------------------------------------------------- | -------- |
| User         | `GET/PATCH/DELETE /me`, `GET /me/export`, `GET /me/usage`, `GET /me/usage/history`, `POST /me/push-tokens`, `DELETE /me/push-tokens/{token}`, `POST /feedback`                     | Required                                  |
| Life         | `GET /me/life`, `GET /me/life/brief`, `POST /me/memories/{id}/complete                                                                                                             | drop                                      | reopen`, `POST /me/messages/search`, `GET /me/insights`, `POST /me/insights/feedback` | Required |
| Memories     | `GET/POST /me/memories`, `POST /me/memories/search`, `GET /me/memories/review`, `POST …/review/accept                                                                              | dismiss`, `POST …/held-back/{run_id}/save | dismiss`, `GET/PATCH/DELETE /me/memories/{id}`, `POST …/{id}/accept                   | retract  | restore | merge | replace`, `GET /me/people`, `GET/PATCH /me/people/{id}`, `POST /me/people/{id}/merge` | Required |
| Chat         | `GET/POST /threads`, `POST /threads/main`, `GET/DELETE /threads/{id}`, `DELETE /threads/{id}/messages`, `GET/POST /threads/{id}/messages`, `POST …/messages/{mid}/proposal/confirm | dismiss`                                  | Required                                                                              |
| Schedules    | `GET/POST /schedules`, `GET/PATCH /schedules/{id}`, `GET/POST /schedules/{id}/runs`, `GET /schedules/{id}/runs/{run_id}`, `GET /activity`                                          | Required                                  |
| Apps         | `GET /tools`, `POST /tools/{slug}/connect`, `GET/DELETE /tools/{slug}/connection`                                                                                                  | Required                                  |
| Memory layer | `/ingestion/*`, `/processing/*`, `/memories/*`                                                                                                                                     | **None**                                  |
| Console      | `/llm-calls/*`, `/playground/*`, `/evaluations/*`, `/console/*`, `/reports/*`, `/health/*`                                                                                         | **None**                                  |

Errors are always `{ error_code, message, detail }`. The reply stream emits `turn_started`, `text_delta`, `tool_started`, `browser`, `connect_link`, then `final` or `error`.

---

## 9. What is implemented

| Feature                                                                                                                                                                                                                                                                     | App                                                                   | Backend                                                                        | Verified by                                                                                                                                                                                        |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Google sign-in, session persistence, sign-out                                                                                                                                                                                                                               | ✅                                                                    | ✅ JWKS verification, user row on first request                                | Tests; live sign-in on a phone; live JWKS check                                                                                                                                                    |
| Main and side threads, drawer, delete                                                                                                                                                                                                                                       | ✅                                                                    | ✅                                                                             | Integration tests; phone                                                                                                                                                                           |
| Chat with streamed replies, server-stored history                                                                                                                                                                                                                           | ✅                                                                    | ✅ Claude Haiku 5.5, cost logged                                               | Tests; live streamed reply on a phone                                                                                                                                                              |
| Reply saved when the client disconnects                                                                                                                                                                                                                                     | n/a                                                                   | ✅                                                                             | Integration test                                                                                                                                                                                   |
| Schedule proposals in chat (confirm / edit / cancel)                                                                                                                                                                                                                        | ✅                                                                    | ✅                                                                             | Integration tests                                                                                                                                                                                  |
| Schedules: once, daily, weekly on chosen days, monthly, every N hours; edit, cancel, delete; detail screen with run history; time and date pickers; timezone shown; only connected apps offered                                                                             | ✅                                                                    | ✅ revision 010, late or overlapping slots skipped and recorded                | Integration and unit tests (backend and app); not yet used on a phone                                                                                                                              |
| Scheduler (timezone/DST-correct, one run per slot)                                                                                                                                                                                                                          | n/a                                                                   | ✅                                                                             | Unit and concurrency tests; startup smoke test                                                                                                                                                     |
| Delivery to chat                                                                                                                                                                                                                                                            | ✅                                                                    | ✅                                                                             | Integration tests                                                                                                                                                                                  |
| Delivery to Slack/email/… through Composio                                                                                                                                                                                                                                  | n/a                                                                   | ✅                                                                             | Tests with a fake Composio only                                                                                                                                                                    |
| App catalog and connections (connect/check/reconnect/disconnect)                                                                                                                                                                                                            | ✅                                                                    | ✅ auth configs found or created on first connect (ADR-039)                    | Tests with a fake Composio; **live**: Google Calendar connected from a phone (24 Oct)                                                                                                              |
| Cooper using connected apps                                                                                                                                                                                                                                                 | ✅ cards                                                              | ✅                                                                             | Tests with a fake Composio; **live**: Cooper created a Google Calendar event (24 Oct)                                                                                                              |
| Cooper browsing the web with a live view                                                                                                                                                                                                                                    | ✅ preview card                                                       | ✅                                                                             | Tests with a fake Browserbase only                                                                                                                                                                 |
| Row level security, user isolation                                                                                                                                                                                                                                          | n/a                                                                   | ✅                                                                             | Integration tests                                                                                                                                                                                  |
| Chats saved as memories, per user; Memories screen and switch                                                                                                                                                                                                               | ✅                                                                    | ✅ capture, owner-scoped resolution, `GET /me/memories`, deletion              | Integration tests with a scripted extractor; **live** (24 Oct): 5 messages captured, 5 real extraction calls, 3 memories (2 messages had nothing to remember), Memories screen loaded on the phone |
| Memory search and Cooper's recall (`search_memories`)                                                                                                                                                                                                                       | ✅ search on the Memories screen                                      | ✅ words + names + meaning, rank fusion, evidence, indexer; the same text once | 143 retrieval tests pass (pgvector installed locally 24 Oct); **live** (24 Oct): 3 memories embedded by Voyage, 2 searches by Cooper each found its memory                                         |
| Memory sources: WhatsApp import (preview, choose yourself, cost estimate, progress), photos and PDFs into memories, Google Calendar events as plans                                                                                                                         | ✅ Import screen, Memories +, Tools → Google Calendar                 | ✅ revision 014, ADR-047                                                       | 9 API integration tests, parser and calendar unit tests, app unit tests; **never used with a real export, file, or calendar**                                                                      |
| Insights in the Feed (money, people on your mind or gone quiet, follow-through, quiet goals, themes), each with its evidence; thumbs up/down; usefulness for the operator                                                                                                   | ✅ Feed "For you"                                                     | ✅ revision 013, ADR-046                                                       | 2 API integration tests, 10 rule tests, component test; **not yet used on a phone**                                                                                                                |
| To-do list from memories (overdue, today, this week, later, no date, goals), check off, snooze, due dates, reminders posted to chat and pushed, daily brief with follow-ups, quiet hours, chat search, Cooper's reminder and list tools                                     | ✅ Tasks → To do, chat cards, Notifications settings, Memories search | ✅ revision 012, ADR-045                                                       | 15 API integration tests, 20 rule tests, app unit and component tests; **not yet used on a phone**; revision 012 not on Neon                                                                       |
| Managing memories: review inbox (accept, accept all, suggestions, held-back), detail with evidence and history, write, correct, edit, wrong/restore, delete, merge, replace; people (rename, merge); sensitive memories kept from Cooper; data export; failed saves retried | ✅                                                                    | ✅ revision 011, ADR-044                                                       | 24 API integration tests, 21 rule tests, app unit and component tests; **not yet used on a phone**; revision 011 not on Neon                                                                       |
| Daily prompt limit (40) and usage meter, today's cost in ₹, collapsible cost chart (day/week/month)                                                                                                                                                                         | ✅ Settings card                                                      | ✅ `daily_usage`, atomic count, per-user override                              | Integration tests incl. concurrency; app unit tests                                                                                                                                                |
| One reply per thread across processes                                                                                                                                                                                                                                       | n/a                                                                   | ✅ lease in the database                                                       | Integration tests with two app instances                                                                                                                                                           |
| Images and PDFs in chat                                                                                                                                                                                                                                                     | ✅ picker, chips, names in history                                    | ✅ sent to Claude once                                                         | Integration and unit tests                                                                                                                                                                         |
| Markdown replies, "load earlier" history                                                                                                                                                                                                                                    | ✅                                                                    | ✅ paging                                                                      | App unit tests; type check                                                                                                                                                                         |
| Feed (finished runs), Ideas prefill, Tasks "+ New"                                                                                                                                                                                                                          | ✅                                                                    | ✅ `/activity`, `POST /schedules`                                              | Integration tests; app type check                                                                                                                                                                  |
| Header menu: clear, delete, share                                                                                                                                                                                                                                           | ✅                                                                    | ✅ `DELETE /threads/{id}/messages`                                             | Integration tests; app unit tests (transcript)                                                                                                                                                     |
| Saved assistant name, subtitle, icon, colour                                                                                                                                                                                                                                | ✅                                                                    | ✅ `PATCH /me`, used in Cooper's prompt                                        | Integration tests; app unit tests                                                                                                                                                                  |
| Notifications switch, push on finished runs, tap opens the chat; device registered at sign-in, unregistered at sign-out                                                                                                                                                     | ✅                                                                    | ✅ Expo push, dead tokens removed                                              | Tests with a fake Expo push; app unit tests. Needs `eas init` and a development build                                                                                                              |
| Help & Feedback, delete account                                                                                                                                                                                                                                             | ✅                                                                    | ✅ revokes apps, cascades, deletes the sign-in                                 | Integration tests with fakes                                                                                                                                                                       |
| Voice input                                                                                                                                                                                                                                                                 | ✅ on-device; message in Expo Go                                      | n/a                                                                            | Type check only                                                                                                                                                                                    |
| Sign-in guard, sign-out on 401, token refresh on resume                                                                                                                                                                                                                     | ✅                                                                    | ✅                                                                             | App unit tests (client)                                                                                                                                                                            |
| Memory layer: capture → extraction → entities → memories, replay, call log, console, evaluation                                                                                                                                                                             | not used by the app                                                   | ✅ (Phase 1)                                                                   | 887 Phase 1 tests; 12 live evaluation runs ([PHASE1_REPORT.md](../memory-layer-for-life/PHASE1_REPORT.md))                                                                                         |

The app features added on 19–24 October were built and checked by type check, lint, unit tests, and bundling, but **not yet used on a phone**.

---

## 10. What is left: app and assistant backend

Ordered by what to do first.

**Do before anyone else uses it**

| Item                                        | Why                                                                                                                                                                                                                                   | Size                                                                                                                                                                |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Try the new app features on a phone         | Feed, Settings meter, Notifications, Help, delete account, header menu, saved profile, "+ New", files, Markdown, "load earlier" were never used on a device                                                                           | One session with the checklist in section 3.4                                                                                                                       |
| Start a fresh git repository                | The old `.git` (the tutorial's history) was deleted on 25 October 2026, so there is no version control: no history, no review, no rollback                                                                                            | `git init`, check `git status` lists no `.env` or `*.secrets.env` file (both `.gitignore` files cover them), commit, and push to your own private GitHub repository |
| Roll the Supabase secret key                | It appeared in a chat transcript, and the API now uses it for account deletion                                                                                                                                                        | Minutes                                                                                                                                                             |
| A real operator sign-in for the console     | Since 24 Oct the operator routes answer only this computer or a request with `OPERATOR_API_KEY` (ADR-040); a sign-in needs the console rebuilt                                                                                        | Medium: clean `npm install` in `frontend/`, then a login                                                                                                            |
| Verify Composio and Browserbase live        | Composio key set and accepted (24 October); auth configs are found or created on first connect (ADR-039). No app connected yet; Browserbase has no key                                                                                | Connect one app from the phone; add a Browserbase key and run one browser task                                                                                      |
| Push in the installed app                   | Needs Firebase Cloud Messaging                                                                                                                                                                                                        | DEPLOYMENT.md §6.4                                                                                                                                                  |
| Deploy staging and production               | Everything is prepared and verified locally (image built and run, migrations from the image, fail-fast settings, operator lock, access list, size limit, stream keep-alive); it needs your Fly.io, Neon, Anthropic, and Expo accounts | DEPLOYMENT.md §2–4: rotate the leaked keys, create the Neon staging project and dev branch, `flyctl apps create`, secrets, `deploy.ps1`                             |
| Move the laptop off the production database | Development still uses Neon production                                                                                                                                                                                                | A `dev` branch (DEPLOYMENT.md §3.2)                                                                                                                                 |
| Known issues and memory roadmap             |                                                                                                                                                                                                                                       | FEATURE_GUIDE.md §24–25                                                                                                                                             |

**Product gaps**

| Item                   | Today                                                                                                             |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Plans and billing      | Deliberately out of scope: a fixed daily limit, no payments, no Upgrade button                                    |
| Appearance / dark mode | Removed from Settings for now                                                                                     |
| Files in chat          | Sent to Claude with one message and not stored; to discuss a file again, attach it again. HEIC photos are refused |
| Feed                   | Shows finished scheduled runs only; no other "intelligence" items                                                 |
| Web                    | The bundle builds but has never been tried in a browser; push and voice are native only                           |
| App end-to-end tests   | Only unit tests; no screen or device tests (e.g. Maestro)                                                         |
| Admin tools            | A user's own limit is set with SQL (`app_users.daily_prompt_limit`); feedback is read from the `feedback` table   |

**Backend gaps**

| Item                                        | Note                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------- |
| Expo push receipts                          | Tickets are checked (dead tokens removed); delivery receipts are not |
| A failed reply still uses its prompt        | Deliberate for now; a refund on provider failures is possible later  |
| Tool catalog logos use `logos.composio.dev` | Unverified                                                           |

---

## 11. What is left: Memory Layer for Life

The memory layer's own plan is in [ROADMAP.md](../memory-layer-for-life/context%20for%20agent/ROADMAP.md), its state in [STATUS.md](../memory-layer-for-life/context%20for%20agent/STATUS.md), and the full Phase 1 account in [PHASE1_REPORT.md](../memory-layer-for-life/PHASE1_REPORT.md) §12.

### 11.1 Phase 1 open items

| Item                                                                                   | What it needs                                                                                                     |
| -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `DEFAULT_TIMEZONE` unset: words like "tomorrow" resolve in UTC                         | One line in `.env`, e.g. `DEFAULT_TIMEZONE=Asia/Kolkata`                                                          |
| Haiku now extracts memories (the code default and ADR-023 recommend Sonnet)            | One evaluation run on the final prompt, about $0.10, to confirm Haiku's quality; Sonnet scored 122/124, Haiku 120 |
| Golden dataset: 124 unreviewed draft cases; `task_002` label dispute; no entity labels | A review by the dataset owner                                                                                     |
| Judge can contradict itself; each model judged itself                                  | Ask for the explanation before the verdict; one cross-judged run (~$0.45)                                         |
| Refusal fallback unproven                                                              | A real refusal (Haiku has no fallback)                                                                            |
| Console cannot be rebuilt with its normal tools; incomplete console lock file          | A clean `npm install` in `frontend/`                                                                              |
| Docker image not rebuilt since the console was added                                   | A build on a machine with Docker                                                                                  |
| Database far away (Neon US East; Phase 1 measured 0.2–4 s per request)                 | Recreate it in a nearer region                                                                                    |
| ✅ WhatsApp export importer (ADR-047)                                                  | Built and tested with sample exports; try one real export                                                         |

### 11.2 Phase 2 (retrieval): built, not yet verified

Implemented on 24 October 2026 (ADR-038, [RETRIEVAL_AND_VECTORS.md](../memory-layer-for-life/context%20for%20agent/RETRIEVAL_AND_VECTORS.md)). To finish it, in order:

| Step                                                                                                               | Cost                                         |
| ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| ✅ Install pgvector into the local test PostgreSQL (done 24 October)                                               | Free                                         |
| ✅ Run the test suite (143 retrieval tests pass)                                                                   | Free; no model or Voyage call                |
| ✅ Apply revisions 008 and 009 to Neon, restart the API with a Voyage key (done 24 October)                        | Free                                         |
| Chat, then check that new memories get embedded (`python -m scripts.index_memories --status`)                      | Cents (`voyage-4`: $0.06 per million tokens) |
| `python -m scripts.run_retrieval_eval --embedder voyage`, then tune the similarity floor and weights on its report | Cents                                        |
| ✅ A search screen in the app (Memories → All)                                                                     | App work                                     |

### 11.3 Phases not started

| Phase                          | Goal                                                | Delivers                                                                                               |
| ------------------------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 3 — Memory management          | ✅ Built 24 Oct (ADR-044)                           | Lifecycle, corrections as versions, history, merges, duplicate/conflict suggestions, held-back review  |
| 4 — Life state                 | ✅ Built 25 Oct (ADR-045)                           | Open items by due date, goals, gone-quiet items, done/drop/reopen, Cooper's list tools                 |
| 5 — API/UI integration         | ✅ In the app (ADR-044); console sign-in still open | Review inbox, search, memory detail with evidence, people, export                                      |
| 6 — Planning and notifications | ✅ Built 25 Oct (ADR-045)                           | Reminders, a daily brief with yesterday's items to check off, quiet hours, preferences                 |
| 7 — Feedback and insights      | ✅ Built 25 Oct (ADR-046)                           | Grounded insights without a model, feedback, usefulness per kind                                       |
| 8 — Integrations and scale     | ✅ Sources built 25 Oct (ADR-047); scale deferred   | WhatsApp import, photos/PDFs via Claude, Google Calendar as plans; queues and workers still not needed |

### 11.4 Joining the memory layer with the app

Chats are captured as memories (ADR-037), and Cooper recalls them through memory search (ADR-038). The path, in dependency order:

1. **Multi-user ownership.** ✅ `owner_id` on evidence, entities, and memories (revision 008); resolution never crosses owners; deleting an account deletes its memory data.
2. **Keep users' data off the open routes.** ✅ The console routes show only the operator's own data, and users read theirs through the signed-in `GET /me/memories`. Still open: sign-in for the console itself.
3. **Capture.** ✅ Each message the user sends (three words or more, never the assistant's replies) goes through `IngestionService` with source `app_chat` and the user's timezone, then the pipeline, in the background. Users can turn it off. Failed runs are retried by the API's pipeline loop (ADR-044).
4. **Recall.** ✅ Cooper's `search_memories` tool and `POST /me/memories/search` return source-backed results (ADR-038). ✅ The memory screen shows the evidence and links to the chat.
5. **Review** (Phase 3): ✅ the To review tab: accept (or accept all), correct, mark wrong, merge or replace suggested pairs, save or dismiss held-back messages.

---

## 12. Further reading

| Document                                                                                            | Covers                                                                        |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| [docs/BACKEND.md](./BACKEND.md)                                                                     | App ↔ backend: env, client modules, API, reply stream, schedules, connections |
| [docs/CODEBASE_EXPLANATION.md](./CODEBASE_EXPLANATION.md)                                           | App UI, file by file; design tokens                                           |
| [AGENTS.md](../AGENTS.md)                                                                           | Rules for contributors and coding agents (app)                                |
| [memory-layer-for-life/README.md](../memory-layer-for-life/README.md)                               | Backend overview, schema, settings, commands, API                             |
| [RUN_LOCALLY.md](../memory-layer-for-life/RUN_LOCALLY.md)                                           | Backend setup on Windows without Docker, tests, troubleshooting               |
| [DECISIONS.md](../memory-layer-for-life/context%20for%20agent/DECISIONS.md)                         | ADR-001 to ADR-030                                                            |
| [STATUS.md](../memory-layer-for-life/context%20for%20agent/STATUS.md)                               | What is verified and what is not                                              |
| [ROADMAP.md](../memory-layer-for-life/context%20for%20agent/ROADMAP.md)                             | Phases and exit gates                                                         |
| [PHASE1_REPORT.md](../memory-layer-for-life/PHASE1_REPORT.md)                                       | Phase 1 results, evaluations, costs, open items                               |
| [ENGINEERING_STANDARDS.md](../memory-layer-for-life/context%20for%20agent/ENGINEERING_STANDARDS.md) | How code here is written and verified                                         |
