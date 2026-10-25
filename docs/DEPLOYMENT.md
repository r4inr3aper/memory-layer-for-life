# Deploying Muse

How the backend runs in production, how the environments are kept apart, and how to ship the Android app against them. Everything here is ready in the repository. The steps that need your accounts are marked **You**.

- **Section 0 is the free setup: start there.**
- Sections 1–8 are the full setup, with a staging environment on Fly.io, for when you outgrow the free plans. Sections 2 (rotate keys), 3.3 (Supabase), 5.2 (migrations) and 6 (building and installing the app) apply to both.

*Written 25 October 2026. Free plans and prices change, so check the linked pages before you rely on the numbers.*

---

## 0. Free setup: Render + Neon Free (start here)

### 0.1 What runs where, and what it costs

| Piece | Free service | The limit that matters |
|---|---|---|
| Backend | [Render](https://render.com) free web service, region **Ohio** (next to the database), running the Docker image | 512 MB, 0.1 CPU. It sleeps after 15 minutes without requests, so a free uptime monitor pings it. Render gives 750 free hours a month: enough for one service that never sleeps |
| Database | Your existing [Neon](https://neon.com) project, Free plan | 100 compute-hours a month. See below |
| Keep-awake ping | [UptimeRobot](https://uptimerobot.com) (or cron-job.org), free | A check every 5 minutes |
| Code and build terminal | [GitHub](https://github.com) private repository, and GitHub Codespaces (a terminal in the browser) | Codespaces' free monthly allowance; it stops itself after 30 idle minutes |
| Image registry (only for the Docker route, 0.3) | [Docker Hub](https://hub.docker.com), free | A private repository for the image |
| App builds | Expo EAS, free plan | Builds may wait in a queue |
| Push notifications | Firebase Cloud Messaging, free | |
| AI | Anthropic | **Not free**: pay per use. On Haiku a chat reply is about $0.002 (₹0.2). Set a spend limit in the Anthropic console |

**How the database stays within 100 hours.**
- Neon's free database sleeps after 5 idle minutes, and every minute it is awake counts. The backend's background jobs used to query it every 15–60 seconds, which kept it awake around the clock: about 180 hours a month.
- The free setup turns on **background pacing** (`BACKGROUND_IDLE_INTERVAL_SECONDS=3600`, in `app/services/pacing.py`). While you use the app, the jobs run at their normal pace; the database is awake for you anyway.
- When nobody is using it, all jobs wake together once an hour, or **exactly when something is due**: a reminder, a schedule slot, the daily brief, a retry. The database sleeps in between, and nothing runs late.
- The uptime monitor pings `/api/v1/health/live`, which never touches the database, so it keeps Render awake without waking Neon.
- Expect roughly 30–50 of the 100 hours a month.

**Compared with the full setup:**
- There are two environments, not three: development on the laptop and production on Render. Render's free hours cover one always-on service.
- A deploy means a push to GitHub (route 0.2) or a new image (route 0.3); the image migrates the database when it starts.
- The first request after a quiet spell waits about a second while Neon wakes.

### 0.2 Route A: only a browser, nothing installed (**You**, about 45 minutes)

Everything runs in the cloud:
- **GitHub Codespaces** is a terminal in the browser, with git and Node already there.
- **Render** builds the Docker image itself from the repository, using the Blueprint in `render.yaml` at the repository root: Docker, the free plan, Ohio, the health check, every setting that isn't secret, and prompts for the secrets.
- **Expo** builds the app in its cloud.

The step-by-step version, with the commands to paste, is `DEPLOY-STEPS.txt`, kept next to `muse-code.zip` (a copy of the project without packages, backend secrets or private data). In short:

1. **GitHub:**
   1. Create a new private repository with a README.
   2. **Code** → **Codespaces** → **Create codespace on main**.
   3. Drag the project zip into the file list.
   4. In the terminal: unzip it, check that no `.env` is staged, commit, and `git push origin HEAD`.

   The `.gitignore` files keep every `.env` out of GitHub. The root `.env`, which holds only the public Supabase values, stays in the codespace for the app build.
2. **Render:**
   1. Sign up with GitHub, then **New** → **Blueprint** → pick the repository.
   2. Enter the values it asks for (copied from `memory-layer-for-life/.env`). For `ACCESS_ALLOWED_EMAILS`, enter `["you@gmail.com"]`.
   3. Click **Apply**, and wait for **Live**.
   4. Check `https://muse-api.onrender.com/api/v1/health/ready`. Render generates `OPERATOR_API_KEY` itself.
3. **UptimeRobot** on `/api/v1/health/live` every 5 minutes. Then the **Supabase** redirect URL `memory://**`, and Neon at 0.25 CU (as in 0.3).
4. **The app,** in the codespace terminal:
   ```bash
   nvm install 22
   npm ci
   npx eas-cli login
   npx eas-cli build -p android --profile production
   ```
   Install from the link. Then commit and push the `app.json` change: the first build writes the EAS project id into it.
5. **Later deploys:** push to GitHub. Render rebuilds only when something under `memory-layer-for-life/` changed.

### 0.3 Route B: from a computer with Docker (**You**, about 30 minutes)

1. **Rotate the leaked keys** (section 2).
2. **Neon** (5 minutes):
   - In your project, **Branches** → `main` → its compute → **Edit**, and set the size to **0.25 CU**. Small and fixed uses the fewest compute-hours.
   - **Connect** → pooling **off** → copy the connection URL. It goes in as it is.
3. **Docker Hub** (5 minutes):
   - Sign up, then **Create repository** `muse-api`, set to **Private**.
   - **Account settings** → **Personal access tokens** → create one with Read & Write.
   - Log in, pasting the token as the password:
     ```powershell
     docker login -u <your-docker-username>
     ```
4. **Build and push the image** (5 minutes). Docker Desktop must be running.
   ```powershell
   cd C:\dev\memory-app\memory-layer-for-life
   .\deploy\push-image.ps1 -Image docker.io/<your-docker-username>/muse-api
   ```
   It runs lint, types and every test first, which needs the Python environment (`.venv`). On a computer without it, add **`-SkipChecks`**: Docker installs every package inside the image, so only Docker is needed. Add `-SkipTests` to skip only the tests.

   **Recreating the Python environment** (only to run the backend or its checks on that computer; Python 3.12 needed):
   ```powershell
   cd C:\dev\memory-app\memory-layer-for-life
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install uv
   .\.venv\Scripts\python.exe -m uv sync --all-extras
   ```
5. **The settings file** (5 minutes):
   ```powershell
   Copy-Item deploy\render.env.example deploy\render.env
   notepad deploy\render.env
   ```
   Fill in:
   - `DATABASE_URL` (from step 2);
   - `SUPABASE_URL`;
   - `ANTHROPIC_API_KEY`;
   - `ACCESS_ALLOWED_EMAILS` (your Google email);
   - `OPERATOR_API_KEY` (generate one with `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"`);
   - and uncomment the optional keys you use (`SUPABASE_SECRET_KEY`, `COMPOSIO_API_KEY`, `VOYAGE_API_KEY`).

   The file is gitignored.
6. **Render** (10 minutes): sign up, then **New** → **Web Service** → **Existing Image**:
   1. Image URL `docker.io/<your-docker-username>/muse-api:latest`. Under **Credential**, add your Docker Hub username and the token.
   2. **Name** `muse-api`, **Region** **Ohio (US East)**, **Instance type** **Free**.
   3. **Environment** → **Add from .env** → paste the whole of `deploy\render.env`.
   4. **Advanced** → **Health Check Path** `/api/v1/health/live`.
   5. **Deploy**. The first start takes 2–3 minutes: it pulls the image, migrates (nothing to do; Neon is at the latest revision), and starts.
   6. Check it: open `https://muse-api.onrender.com/api/v1/health/ready`. You should see `"status":"ready","database":"connected"`.
   7. If Render gave the service a different address (the name was taken), put that address in `eas.json` under `production` → `EXPO_PUBLIC_API_URL`.
   8. **Settings** → **Deploy Hook**: copy the URL and keep it private. Later deploys use it.
7. **Keep it awake** (3 minutes): in UptimeRobot, **Add New Monitor** → HTTP(s) → URL `https://muse-api.onrender.com/api/v1/health/live` → interval **5 minutes**. It also emails you if the API goes down.
8. **Supabase:** make sure `memory://**` is in the redirect URLs (section 3.3).
9. **The laptop:** don't run the backend against the production database at the old pace. It would keep Neon awake and use up the free hours.
   - Stop it when you don't need it.
   - Or add `BACKGROUND_IDLE_INTERVAL_SECONDS=3600` to `memory-layer-for-life/.env`.
   - Better: create a **separate free Neon project** for development, which has its own 100 hours, and put its URL in that `.env`.
10. **Build and install the app** (section 6):
    ```powershell
    cd C:\dev\memory-app
    npx eas-cli login
    npx eas-cli build -p android --profile production
    ```
    Open the link on your phone, install, and sign in with Google.

### 0.4 Deploying a change (route B)

```powershell
cd C:\dev\memory-app\memory-layer-for-life
$env:RENDER_DEPLOY_HOOK = '<the deploy hook URL from step 6>'
.\deploy\push-image.ps1 -Image docker.io/<your-docker-username>/muse-api -HealthUrl https://muse-api.onrender.com
```

The script:
1. checks everything;
2. builds and pushes the image (tagged with the date and time, and `latest`);
3. has Render deploy that exact tag;
4. waits until the API answers ready.

Migrations run when the new version starts. If one fails, the new version doesn't start and the old one keeps serving. To roll back, use Render → **Events** → an earlier deploy → **Rollback**.

### 0.5 Watching the free limits

| Where | What to look at |
|---|---|
| Neon → your project → **Usage** / **Monitoring** | Compute hours this month; well under 100 is normal |
| Render → the service → **Logs** | JSON logs; `application_ready … database_sleeps_between_ticks=true` at each start |
| Render → **Billing** | Free hours used this month |
| UptimeRobot | Uptime, and an email if the API goes down |
| Anthropic console → **Usage** | What the AI costs; set a monthly limit |

If Neon's hours ever run out, its database is suspended until the 1st of next month. Then either upgrade the project to Launch (section 3.2), or check that nothing else (such as the laptop) is keeping it awake.

---

## 1. The shape of it

```
 Phone: Muse app (EAS build)                       Fly.io, region iad (Ashburn)
 ┌─────────────────────────┐   https + Bearer    ┌──────────────────────────────────────────┐
 │ "Muse" / "Muse Staging" │ ──────────────────► │ muse-cooper-api (one machine, always on)  │
 │ Google sign-in          │ ◄── reply stream ── │ FastAPI + background loops                │
 └───────────┬─────────────┘                     │ (scheduler, reminders, brief, memory      │
             │ sign-in only                      │  pipeline, indexer, calendar sync)        │
             ▼                                   └──────┬───────────────┬────────────────────┘
 ┌─────────────────────────┐   verifies tokens (JWKS)   │               │ SQL over TLS
 │ Supabase Auth           │ ◄──────────────────────────┘               ▼
 └─────────────────────────┘                     ┌──────────────────────────────────────────┐
                                                 │ Neon PostgreSQL, AWS us-east-2 (Ohio)     │
                                                 └──────────────────────────────────────────┘
```

The API runs in Ashburn because the database is in Ohio, about 10 ms away. Every request makes several queries, so the API must sit next to the database, not next to the phone.

### 1.1 Three environments

| | Development | Staging | Production |
|---|---|---|---|
| **What it's for** | Writing code on the laptop | Trying a change for real before production | Your real assistant and memories |
| **Backend** | `uvicorn` on the laptop | Fly app `muse-cooper-api-staging`. It stops when idle and starts on the next request | Fly app `muse-cooper-api`, always on |
| **Database** | Neon project `muse-staging`, branch `dev` | Neon project `muse-staging`, branch `main` | Your existing Neon project, branch `main` (your data) |
| **Settings** | `memory-layer-for-life/.env` | `fly.staging.toml` plus Fly secrets | `fly.production.toml` plus Fly secrets |
| **App build** | Expo Go, or the `local` profile ("Muse Dev") | `staging` profile ("Muse Staging") | `production` profile ("Muse"); `store` for Google Play |
| **Anthropic key** | Dev workspace | Staging workspace | Production workspace |
| **Composio** | Non-production project | Non-production project | Production project |
| **Daily prompt limit** | 40 | 20 | 40 |

**What "separated" means here:**
- **Data.** Each environment has its own database. A test in staging can never touch a real memory, and the laptop stops writing to production.
- **Secrets.** They live only in Fly's encrypted secret store (and the laptop's gitignored `.env`). No secret is in any file in the repository, and none is ever printed: a misconfigured start names the problem without echoing values.
- **Settings that are not secret** (models, limits, timezone, which loops run) live in `fly.<environment>.toml`. They are reviewed like code, so you can see what differs between staging and production.
- **Keys.** Each environment uses its own provider keys, each with its own spend limit. A runaway loop in staging cannot spend production's budget.
- **Apps.** The three app builds are separate apps: different name, package (`com.museai.app`, `.staging`, `.dev`) and sign-in scheme. They install side by side, and a sign-in always returns to the app that started it.

### 1.2 What protects production (built in)

| Protection | Where |
|---|---|
| Refuses to start half-configured, listing every problem: database on localhost or without TLS, no Supabase URL, no Anthropic key, operator key under 32 characters, `*` in CORS | `app/core/config.py` (`deployed_settings_are_complete`) |
| Startup errors never echo values (passwords, keys) into logs | `hide_input_in_errors` in the same file |
| Database URLs pasted from Neon work as they are (scheme and TLS parameters normalized for the driver) | `normalize_database_url` |
| Operator routes (memory layer, call log, evaluations) accept only `X-Operator-Key` when deployed; "localhost" is never trusted there | `app/api/dependencies.py` (`require_operator`) |
| Access list: only the emails in `ACCESS_ALLOWED_EMAILS` may use the app. Anyone else gets 403 before the API stores anything | `get_principal` |
| API docs (`/docs`, `/openapi.json`) off in production | `API_DOCS_ENABLED` |
| Request bodies over 25 MB refused with 413 before they are read | `app/core/request_limits.py` |
| Reply stream sends a keep-alive every 15 s, so long browser tasks are not cut off by the proxy | `app/api/v1/endpoints/threads.py` |
| JSON logs with a request id on every line | `app/core/logging.py`, `request_logging.py` |
| Image built from `uv.lock` exactly as tested; runs as a non-root user; no secrets, tests or console inside | `memory-layer-for-life/Dockerfile`, `.dockerignore` |
| Migrations run once per deploy in a temporary machine, before traffic moves. A failure stops the deploy and the old version keeps serving | `release_command` in the toml files |
| Health check on `/api/v1/health/live`; graceful shutdown waits up to 25 s for replies in progress | toml files, Dockerfile |
| A deploy script that refuses to ship unless lint, format, types and all tests pass, and smoke-tests the result | `memory-layer-for-life/deploy/deploy.ps1` |

These were verified locally:
- The image was built and run.
- Migrations ran from it.
- A production start with missing settings was refused, with no secret in the output.
- Operator routes answered 403 from outside the container, and the container reported healthy.
- 1,693 backend tests and 158 app tests pass.

---

## 2. Before anything else: rotate leaked keys (**You**)

These keys appeared in chat transcripts or in this repository's history, so treat them as public. Rotate each one, and put the new value only in the place listed.

| Key | Where to rotate | New value goes in |
|---|---|---|
| Supabase secret key (`sb_secret_…`) | Supabase → Project Settings → API Keys: create a new secret key, then delete the old one | Fly secrets (`SUPABASE_SECRET_KEY`) and the laptop's `.env` |
| Composio API key | Composio → Settings → Project Settings → API Keys | Fly secrets and the laptop's `.env` |
| Keys in the old committed `.env` (commits before `3d96b22`: OpenAI, Browserbase, Composio) | Each provider's console. Revoke them | Nowhere, unless still used |

---

## 3. One-time setup

### 3.1 Tools and accounts (**You**)

1. **Fly.io account** at [fly.io](https://fly.io). A payment card is required; small apps cost a few dollars a month (section 7).
2. **Install `flyctl`** in PowerShell, then open a new terminal:
   ```powershell
   iwr https://fly.io/install.ps1 -useb | iex
   flyctl auth login
   ```
3. **Expo account** (free), for app builds: `npx eas-cli login`.
4. Neon, Supabase, Anthropic and Composio accounts already exist.

### 3.2 Databases on Neon (**You**)

1. **Production: your existing project.**
   - Upgrade it to the **Launch** plan. The background loops query the database every 15–60 seconds, so it never sleeps. On the Free plan (100 compute-hours a month), production would be suspended about halfway through the month.
   - In the project's compute settings, set autoscaling to **0.25–1 CU** to cap the cost.
   - Get the URL: **Connect** → branch `main` → **turn connection pooling off** (direct connection) → copy the URL. Paste it as is; the API converts Neon's `postgresql://…?sslmode=require&channel_binding=require` into the form its driver needs.
2. **Staging: a new project.**
   - **New project** → name `muse-staging` → region **AWS US East 2 (Ohio)** → Postgres version same as production.
   - Copy its direct URL for staging. Its tables are created by the first staging deploy.
3. **Development: a branch of staging.**
   - In `muse-staging` → **Branches** → **New branch** `dev` from `main` → copy its direct URL.
   - Put it in `memory-layer-for-life/.env` as `DATABASE_URL`, replacing the production URL there now. Then:
     ```powershell
     cd C:\dev\memory-app\memory-layer-for-life
     .\.venv\Scripts\python.exe -m alembic upgrade head
     ```
   - From then on, the laptop never touches production.
   - **Do this before or right after the first production deploy.** Two backends on one database would both run the background loops. Nothing would be sent twice (each reminder and schedule slot is claimed in the database), but embeddings would be paid for twice, and you could not tell which machine did what.

### 3.3 Supabase sign-in (**You**)

Supabase → **Authentication** → **URL Configuration** → **Redirect URLs**. Make sure all of these are listed:

```
memory://**
memory-staging://**
memory-dev://**
exp://**
```

One Supabase project serves every environment. It only proves who you are; each environment keeps its own data. Then:
- Under **Sign In / Providers**, keep **anonymous sign-ins off**.
- Once you have signed in to production once, consider turning off **Allow new users to sign up**. The access list already blocks strangers at the API, and this blocks them at sign-in as well.

### 3.4 Provider keys per environment (**You**)

- **Anthropic.** [console.anthropic.com](https://console.anthropic.com) → Settings → **Workspaces**. Create `muse-staging` and `muse-production`, give each a monthly spend limit (for example $5 and $25), and create an API key in each. Use the existing key only on the laptop, or give it its own workspace too.
- **Composio.** Keep the current project for production. Create a second project for staging and development, with its own API key.
  - This matters: disconnecting an app deletes the account in Composio. If staging and production shared a project, disconnecting Gmail while testing staging would disconnect it in production too.
- **Voyage** (optional, search by meaning): a key per environment, or leave it empty in staging.

### 3.5 Create the Fly apps (**You**)

```powershell
cd C:\dev\memory-app\memory-layer-for-life
flyctl apps create muse-cooper-api-staging
flyctl apps create muse-cooper-api
```

App names are global on Fly. If either name is taken, pick another and change it in three places:
- the `app = "…"` line in the toml;
- `EXPO_PUBLIC_API_URL` of the matching profile in the root `eas.json`;
- this document.

### 3.6 Secrets (**You**)

```powershell
cd C:\dev\memory-app\memory-layer-for-life
Copy-Item deploy\secrets.example.env deploy\staging.secrets.env
Copy-Item deploy\secrets.example.env deploy\production.secrets.env
notepad deploy\staging.secrets.env
notepad deploy\production.secrets.env
```

Fill in each file. The comments in it explain every line:

| Secret | Staging | Production |
|---|---|---|
| `DATABASE_URL` | `muse-staging` → `main` | Existing project → `main` |
| `SUPABASE_URL` | Same project | Same project |
| `ANTHROPIC_API_KEY` | Staging workspace key | Production workspace key |
| `ACCESS_ALLOWED_EMAILS` | `["you@gmail.com"]` | `["you@gmail.com"]` (add anyone you invite) |
| `OPERATOR_API_KEY` | New random value | Different random value |
| `SUPABASE_SECRET_KEY` | The rotated key (optional) | The rotated key |
| `COMPOSIO_API_KEY` | Non-production project | Production project |
| `VOYAGE_API_KEY`, `BROWSERBASE_API_KEY` | Optional | Optional |

Generate an operator key with:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Both files are gitignored. The deploy script imports them into Fly and refuses a file that still holds template values. After importing, delete the files or keep them in a password manager.

---

## 4. First deploy

### 4.1 Staging

```powershell
cd C:\dev\memory-app\memory-layer-for-life
.\deploy\deploy.ps1 staging -ImportSecrets
```

The script:
1. Runs lint, format, types and the full test suite. The local test PostgreSQL must be running, or add `-SkipTests` for code you have just tested.
2. Imports the secrets.
3. Runs `flyctl deploy`. Fly builds the image on its own machines, runs `alembic upgrade head` against the staging database, starts the new machine, and waits for its health check.
4. Calls `https://muse-cooper-api-staging.fly.dev/api/v1/health/ready` and prints `Deployed: … (database connected)`.

Check it yourself:

```powershell
curl https://muse-cooper-api-staging.fly.dev/api/v1/health/ready
# {"status":"ready","database":"connected","details":null}
flyctl logs -a muse-cooper-api-staging
# look for application_ready ... sign_in_configured=true assistant_configured=true
```

Then build the staging app (section 6), install it, sign in, and run the smoke test in section 4.3.

### 4.2 Production

```powershell
.\deploy\deploy.ps1 production -ImportSecrets
```

It asks you to type the app name to confirm. The migrations have nothing to do, because production is already at the latest revision (014). Then build the production app (section 6), install it, sign in, and run the smoke test.

### 4.3 Smoke test after every deploy (5 minutes)

1. `GET /api/v1/health/ready` answers `ready` and `connected`.
2. In the app:
   1. Sign in; the chat opens.
   2. Send "hi"; the reply streams in.
   3. Settings shows the prompt count up by 1.
3. Ask "remind me in 2 minutes to stretch". The reminder appears in the chat about 2 minutes later.
4. Tasks → Schedules → **Run** on any schedule. The result appears in the Feed and the chat.
5. With a second Google account not on the access list: sign-in completes, then every screen shows "This Muse is private…".
6. `curl https://<app>.fly.dev/api/v1/memories` answers 403 `OPERATOR_ACCESS_DENIED`. In production, `/docs` answers 404.

---

## 5. Everyday operations

### 5.1 Shipping a change

1. Run the tests locally, then `.\deploy\deploy.ps1 staging`.
2. Try the change in "Muse Staging".
3. Run `.\deploy\deploy.ps1 production`.

App code changes need a new app build (section 6). Backend-only changes don't: the installed app keeps working.

**Deploy when no scheduled task is about to run.**
- A deploy replaces the single machine: the API is gone for 10–30 seconds.
- Replies in progress get 25 seconds to finish.
- A scheduled run caught mid-way is recorded as failed (`SCHEDULE_RUN_INTERRUPTED`) and not retried.
- A schedule slot that falls in the gap still runs when the machine is back (anything up to an hour late runs).

### 5.2 Migrations

- A deploy runs `alembic upgrade head` before switching. If it fails, nothing changes: read the error in the deploy output, fix it, deploy again.
- **Write migrations that the previous version of the code can live with**: add columns or tables first, remove them in a later release. Then a bad release can be fixed by deploying the previous image, and the database never has to go backwards.
- Before a risky migration, snapshot production in Neon: **Branches** → **New branch** from `main`, named `before-<change>`. Restoring is then a matter of minutes. Point-in-time restore also exists: up to 7 days on Launch.

### 5.3 Rolling back

```powershell
flyctl releases -a muse-cooper-api --image          # find the previous image
flyctl deploy --config fly.production.toml --image registry.fly.io/muse-cooper-api:deployment-XXXX
```

If the bad release added a migration, the old code can still run on the newer schema, provided the migration only added things (section 5.2). Do not downgrade the database unless that migration removed or renamed something. In that case, first run `flyctl ssh console -a muse-cooper-api -C "alembic downgrade -1"` with the current image, then deploy the old one.

### 5.4 Logs, health, and looking inside

| Task | Command |
|---|---|
| Follow logs (JSON, one line per request, each with `request_id`) | `flyctl logs -a muse-cooper-api` |
| Machine state and health checks | `flyctl status -a muse-cooper-api` |
| CPU, memory, response times | Fly dashboard → the app → **Metrics** |
| A shell in the running machine | `flyctl ssh console -a muse-cooper-api` |
| Embedding coverage, without spending anything | `flyctl ssh console -a muse-cooper-api -C "python -m scripts.index_memories --status"` |
| Operator API from your laptop | `curl -H "X-Operator-Key: <key>" https://muse-cooper-api.fly.dev/api/v1/llm-calls/usage` |
| Restart | `flyctl apps restart muse-cooper-api` |
| More memory | Change `memory` under `[[vm]]` in the toml and deploy, or `flyctl scale memory 2048 -a muse-cooper-api` |

**Optional uptime alerts.** A free monitor (for example UptimeRobot or Better Stack) that requests `https://muse-cooper-api.fly.dev/api/v1/health/ready` every 5 minutes and emails you when it fails. Do this for production only: pinging staging would keep it, and its database, awake.

### 5.5 Changing a setting or a secret

- **Not secret** (a model, a limit, a loop on or off): edit `fly.<environment>.toml`, then deploy.
- **Secret:** `flyctl secrets set ANTHROPIC_API_KEY=sk-ant-... -a muse-cooper-api`. This restarts the machine with the new value. List the names (never the values) with `flyctl secrets list -a muse-cooper-api`.
- **Adding someone to the app:** `flyctl secrets set 'ACCESS_ALLOWED_EMAILS=["you@gmail.com","friend@gmail.com"]' -a muse-cooper-api`. Keep the single quotes in PowerShell.

---

## 6. Building and installing the Android app

### 6.1 Profiles

| Profile | App on the phone | Backend | Build type |
|---|---|---|---|
| `local` | Muse Dev (`com.museai.app.dev`) | `http://192.168.1.2:8000`: the laptop, same Wi-Fi only | APK |
| `staging` | Muse Staging (`com.museai.app.staging`) | `https://muse-cooper-api-staging.fly.dev` | APK |
| `production` | Muse (`com.museai.app`) | `https://muse-api.onrender.com` (the free setup; `https://muse-cooper-api.fly.dev` on the full one) | APK, version raised on every build |
| `store` | Muse | Production | AAB for Google Play |

The backend address is fixed into the app when it is built, so each profile's app always talks to its own backend. `app.config.ts` refuses to build `production` or `store` against anything but https.

### 6.2 Build (**You**)

```powershell
cd C:\dev\memory-app
npx eas-cli login
npx eas-cli build -p android --profile production
```

The first time, answer:
- **Yes** to "create an EAS project". It writes the project id into `app.json`; keep that change, because push needs it.
- **Yes** to "generate a new Android Keystore". Expo stores it.

Each app (dev, staging, production) gets its own keystore the first time it is built. A build takes 10–20 minutes and ends with a link and a QR code.

### 6.3 Install

1. Open the link on the phone (or scan the QR code) and tap **Install**. Android downloads the APK.
2. Open the APK. If Android says installs from this source are blocked, tap **Settings**, allow your browser to install apps, go back, and tap **Install**.
3. Open **Muse** and sign in with Google (an account on the access list).
4. Allow notifications when asked. They work once section 6.4 is done.

A newer build installs over the old one and keeps you signed in. Muse, Muse Staging and Muse Dev can all be installed at once.

### 6.4 Push notifications (**You**, once)

Android push goes through Firebase Cloud Messaging. Without this, everything else works and the app simply receives no push.

1. [console.firebase.google.com](https://console.firebase.google.com) → **Add project** (e.g. `muse`).
2. **Add app** → Android → package `com.museai.app`. Repeat for `com.museai.app.staging` and `com.museai.app.dev` if you want push in those builds.
3. Download **google-services.json**. It covers every app you added. Save it in `C:\dev\memory-app`; it is gitignored and never uploaded with the code.
4. Store it in EAS as a secret file:
   ```powershell
   npx eas-cli env:create --name GOOGLE_SERVICES_JSON --type file --value .\google-services.json --visibility secret --environment production --environment preview --environment development
   ```
5. Firebase → Project settings → **Service accounts** → **Generate new private key** (a JSON file).
6. `npx eas-cli credentials -p android` → pick the profile → **Google Service Account** → **Manage your Google Service Account Key for Push Notifications (FCM V1)** → upload that JSON. Repeat for each app id you build.
7. Build again. In the app, Settings → **Notifications** shows "Notifications are on" once the device is registered.

### 6.5 Google Play (later)

`npx eas-cli build -p android --profile store` makes the AAB, and `npx eas-cli submit -p android --profile store` uploads it. That needs a Google Play developer account, a privacy policy, and a store listing.

---

## 7. What it costs (estimates)

| Item | Production | Staging |
|---|---|---|
| Fly machine | shared-cpu-1x, 1 GB, always on: about $6/month | 512 MB, stopped when idle: well under $1/month |
| Neon | Launch plan, 0.25 CU always on (about 180 compute-hours at $0.106): about $19/month, plus storage at $0.35/GB-month | Free plan; it sleeps when the staging machine stops |
| Anthropic | Per use. On Haiku, a chat reply is about $0.002 and its memory extraction about $0.0007; the Settings screen shows today's total | Same, capped by the staging workspace limit |
| Voyage | Fractions of a cent per memory and per search | Optional |
| Expo builds | Free tier: a limited number of builds a month | Same |

Pricing pages: [Fly.io](https://fly.io/docs/about/pricing/), [Neon](https://neon.com/pricing).

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Deploy stops at the release command | A migration failed | Read the error in the output. Nothing was changed; fix and deploy again |
| Logs: `production settings are incomplete: …` | A required secret is missing or wrong | Set the named secret (`flyctl secrets set …`) |
| Deploy stops at the health check | The app crashed at startup | `flyctl logs -a <app>`; usually the line above |
| Every screen says "This Muse is private…" | Your email is not in `ACCESS_ALLOWED_EMAILS` | Add it (section 5.5). Compare the exact Google email |
| Google sign-in ends on `localhost:3000` | That build's scheme is not in Supabase's redirect URLs | Add `memory://**` (or `-staging`, `-dev`) (section 3.3) |
| "Could not reach the server" in the app | Wrong backend address in the build, or the Fly app is down | Check `EXPO_PUBLIC_API_URL` in `eas.json` matches the toml's `app`, and `curl …/health/ready` |
| Staging's first request takes 5–10 s | Its machine and database were asleep | Expected |
| A reply stops mid-way: "The connection dropped…" | Network drop | Reopen the chat; the server finished and stored the reply |
| 413 `REQUEST_TOO_LARGE` | Over 25 MB of files in one request | Send fewer or smaller files (at most 3 × 5 MB) |
| Neon: "compute time quota exceeded" | Production on the Free plan | Upgrade the project to Launch |
| No push on the phone | No Firebase setup, notifications off in Settings, or the phone's system setting | Section 6.4; Settings → Notifications; the phone's app settings |
| A schedule run says "interrupted" | A deploy or restart happened during it | Run it again (Tasks → Run) |
