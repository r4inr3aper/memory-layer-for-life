# Run Locally on Windows (No Docker)

This guide runs the Second Brain backend and its test console on Windows without Docker. PostgreSQL runs from a portable folder in your user profile, so nothing needs admin rights and nothing is installed as a Windows service. If you prefer Docker, see the Docker commands in [README.md](README.md).

All commands are PowerShell and are run from the project root.

Already set up on this machine? Skip to [Everyday use](#everyday-use).

## What you get

| Address | What it is |
|---|---|
| <http://localhost:8000> | The test console: single test calls, evaluations, usage and cost, the pipeline, and the Phase 1 results |
| <http://localhost:8000/docs> | Interactive API documentation |
| <http://localhost:8000/api/v1/health/ready> | Health check |

## Prerequisites

- Windows 10 or 11. Both ship `curl.exe` and `tar.exe`, which step 2 uses.
- Python 3.12 or newer on your PATH. Check with `python --version`.
- About 500 MB of free disk space.
- Optional: an Anthropic API key with credit. The API and the console start without one. A key is needed for everything that calls a model: test calls, processing captured notes, and evaluations.
- Not needed: Node.js. The console is already built in `frontend\dist`. Node is only needed to change the console, see [Change the console](#change-the-console).

What the setup puts on your machine:

| What | Where |
|---|---|
| Python packages | `.venv\` inside the project |
| PostgreSQL 16 binaries, data, and log | `%LOCALAPPDATA%\second-brain-postgres\` |
| `uv` package manager | your per-user Python scripts folder |

## One-time setup

### 1. Install Python dependencies

```powershell
python -m pip install --user uv
python -m uv sync --all-extras
```

This creates `.venv\` from `uv.lock`. If the project came with a `.venv` built on another computer, `uv` replaces it.

### 2. Download portable PostgreSQL 16

```powershell
$pg = "$env:LOCALAPPDATA\second-brain-postgres"
New-Item -ItemType Directory -Force $pg | Out-Null
curl.exe -L -o "$env:TEMP\pg16.zip" "https://get.enterprisedb.com/postgresql/postgresql-16.14-1-windows-x64-binaries.zip"
tar.exe -xf "$env:TEMP\pg16.zip" -C $pg pgsql/bin pgsql/lib pgsql/share pgsql/include
Remove-Item "$env:TEMP\pg16.zip"
& "$pg\pgsql\bin\postgres.exe" --version
```

The download is about 330 MB. The `tar` command extracts only the server and its headers (needed to build pgvector in step 3a), and skips the bundled pgAdmin. The last line should print `postgres (PostgreSQL) 16.14`.

Any 16.x build works. Other versions are listed at <https://www.enterprisedb.com/download-postgresql-binaries>.

### 3. Create and start the database

```powershell
$pg = "$env:LOCALAPPDATA\second-brain-postgres"

# Create the cluster with the project's dev credentials
Set-Content -Path "$pg\pw.txt" -Value "brain_dev_password" -NoNewline -Encoding ascii
& "$pg\pgsql\bin\initdb.exe" -D "$pg\data" -U brain --pwfile="$pg\pw.txt" -A scram-sha-256 -E UTF8 --locale=C
Remove-Item "$pg\pw.txt"

# Start the server
& "$pg\pgsql\bin\pg_ctl.exe" start -D "$pg\data" -l "$pg\postgres.log"

# Create the app database and the test database
$env:PGPASSWORD = "brain_dev_password"
& "$pg\pgsql\bin\createdb.exe" -h localhost -U brain second_brain
& "$pg\pgsql\bin\createdb.exe" -h localhost -U brain second_brain_test
Remove-Item Env:PGPASSWORD
```

Notes on these choices:

- The user `brain`, the password, and the database names match [compose.yaml](compose.yaml) and the default `DATABASE_URL`, so no connection settings need to change.
- `-E UTF8` matters. Without it, Windows creates the cluster in a legacy code page that cannot store emoji or most non-Latin text.
- The server listens on `localhost:5432` only. It is not reachable from other machines.

### 3a. Install pgvector

Memory retrieval stores embeddings with the pgvector extension, and the migrations create it, so they fail without it. The portable PostgreSQL does not include it (pg_trgm, the other extension retrieval uses, is included). Build it once from its official source. This needs git, the "Desktop development with C++" workload of Visual Studio Build Tools, and PostgreSQL's headers in `pgsql\include` (step 2 extracts them; an older install without them can extract just `pgsql/include` from the same archive):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_pgvector_windows.ps1
& "$env:LOCALAPPDATA\second-brain-postgres\pgsql\bin\pg_ctl.exe" restart -D "$env:LOCALAPPDATA\second-brain-postgres\data"
```

Hosted databases such as Neon already provide pgvector.

### 4. Configure the environment

```powershell
Copy-Item .env.example .env
```

Then open `.env` and check these lines:

| Setting | What to do |
|---|---|
| `ANTHROPIC_API_KEY` | With a key: replace the placeholder so the line reads `ANTHROPIC_API_KEY=<your key>`. Without a key: delete the line. Leaving the placeholder in makes the app treat a fake key as real. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` is the default and the most accurate. `claude-haiku-5-5` costs about a tenth. In the Phase 1 evaluation Haiku passed 119 to 120 of 124 cases and Sonnet 122. |
| `DEFAULT_TIMEZONE` | Set it to the timezone you write your notes in, for example `Asia/Kolkata`. It decides which day a word like "tomorrow" means, and how the console groups cost by day. |
| `DATABASE_URL` | Leave it as it is for the local database. For a hosted one, see [Use a hosted database](#use-a-hosted-database). |
| `VOYAGE_API_KEY` | Optional. With a Voyage AI key, memory search also finds memories by meaning, and the API embeds new memories in the background. Without one, search uses words and names. After adding a key to a store with existing memories, either let the running API catch up by itself, or run `.\.venv\Scripts\python.exe -m scripts.index_memories` once. |

`.env` is listed in `.gitignore`. Keep your key out of version control and out of chat windows. Restart the API after every change to `.env`.

### 5. Apply database migrations

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

This creates all tables. Run it again after every update of the code. It does nothing when the database is already up to date.

### 6. Optional: load earlier evaluation results

If the folder `eval_reports\` holds reports of earlier evaluation runs, store them in the database so the console can show them:

```powershell
.\.venv\Scripts\python.exe -m scripts.import_eval_reports
```

It calls no model, and it can be run again safely: a report that is already stored is skipped.

## Everyday use

### Start

PostgreSQL does not start with Windows. Start it after each reboot, then start the API:

```powershell
$pg = "$env:LOCALAPPDATA\second-brain-postgres"
& "$pg\pgsql\bin\pg_ctl.exe" start -D "$pg\data" -l "$pg\postgres.log"

.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

`--reload` restarts the server when you edit code. The API keeps the terminal busy until you stop it.

If `DATABASE_URL` points at a hosted database, the local PostgreSQL is only needed for running tests, and you can skip the first two lines.

### Open the console

Open <http://localhost:8000>.

| Screen | Use it to |
|---|---|
| Overview | See estimated cost per day, usage by model, failed calls, the latest evaluation, and what the pipeline holds |
| Playground | Make one test call and see exactly what comes back, and in what format |
| Evaluations | See every evaluation run, open one case by case, and start a new run |
| Model calls | Read the log of every call to the model: tokens, cost, duration, result |
| Pipeline | See captured notes, how their processing went, and the memories that came out |
| Phase 1 results | See the scores by model and read the Phase 1 report |

The top bar shows whether the API answers and whether a key is configured. **Check connection** makes one tiny model call, which is logged and costs a fraction of a cent.

Everything the console shows is read from the database. With an empty database the screens say so and tell you what to do.

### Make a single test call

1. Open **Playground**.
2. Type a note. **Add a message to this unit** adds further messages that are read together with the first, as one thought.
3. Choose a model and an effort.
4. Leave **Save through the pipeline** off. That is a dry run: the model is called and its answer is checked, and nothing is stored as a message or a memory.
5. Press **Run test call**. The estimated cost is shown next to the button.
6. Read the result in the tabs: **Memories**, **Validated JSON**, **Raw model output**, **Model call** (tokens, cost, duration), and **Input**.

**Output format** shows the contract every answer must satisfy. One test call costs about a tenth of a cent on Haiku and about 2 cents on Sonnet.

Without a key the button is switched off and the screen says "No API key is configured, so no call can be made."

### Capture a real note

In the Playground, turn **Save through the pipeline** on and press **Capture and process**. The note is stored as a real message and becomes proposed memories. Look at it on the **Pipeline** screen.

The same through the API:

```powershell
$body = '{"messages":[{"source":"api_input","content":"Call the bank about the card on Friday"}]}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/ingestion/units -ContentType "application/json" -Body $body
```

A captured note is processed right away when a key is configured. Without a key it waits in the queue. To process waiting notes later:

```powershell
.\.venv\Scripts\python.exe -m scripts.process_pending
```

### Run an evaluation

An evaluation sends the cases of `golden.jsonl` to the model and scores every answer. **It sends those notes to Anthropic and it costs money:** about 0.10 US dollars for all 124 cases on Haiku and about 1.03 on Sonnet.

From the console: **Evaluations**, then **Start evaluation**. Choose all cases or some, read the estimate, and start. The run appears in the list and fills in while it runs.

From a terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_golden_eval
```

| Option | Meaning |
|---|---|
| `--model claude-haiku-5-5` | Extraction model. Defaults to `ANTHROPIC_MODEL`. |
| `--effort medium` | Extraction effort: `low`, `medium`, `high`, `xhigh`, or `max`. |
| `--cases task_001 task_002` | Only these cases. |
| `--judge-model claude-sonnet-5-5` | Model that judges the answers. Defaults to the extraction model. |
| `--concurrency 6` | Cases processed at a time. |

Either way the run is stored in the database and every call goes into the call log. The terminal command also writes `eval_reports\<timestamp>\report.json` and `report.md`.

### Check that it works

Run this in a second terminal:

```powershell
curl.exe http://localhost:8000/api/v1/health/ready
```

A healthy setup returns:

```json
{"status":"ready","database":"connected","details":null}
```

To confirm that your Anthropic key and model work, press **Check connection** in the console, or run:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_anthropic_connection
```

It sends one small request to the Anthropic API, which is billed to your key and logged in the database like every other call. When everything is in order it prints a line such as `SUCCESS: Connected to Anthropic (claude-haiku-5-5)`, followed by the tokens, the estimated cost, and the duration.

### Stop

Press `Ctrl+C` in the API terminal. Then stop the database:

```powershell
$pg = "$env:LOCALAPPDATA\second-brain-postgres"
& "$pg\pgsql\bin\pg_ctl.exe" stop -D "$pg\data"
```

To see whether the database is running, use the same command with `status` in place of `stop`.

## Use a hosted database

The application can use a hosted PostgreSQL, for example to share one set of data between two computers. Set `DATABASE_URL` in `.env` in this form:

```
postgresql+asyncpg://USER:PASSWORD@HOST/DBNAME?ssl=require
```

Three rules:

- The scheme must be `postgresql+asyncpg://`. A plain `postgresql://` does not work.
- Use `ssl=require`. The options `sslmode=require` and `channel_binding=require`, which some providers put in their connection string, are rejected.
- Use the direct host, not a pooled one. On Neon that is the host without `-pooler`. On Supabase, a session pooler (port 5432) also works; a transaction pooler (port 6543) does not.

Then apply the migrations once with `.\.venv\Scripts\python.exe -m alembic upgrade head` and restart the API.

Requests take longer the farther away the database is. With a database on another continent a console page takes between a fraction of a second and a few seconds.

The tests never use this database. They always use the local `second_brain_test`.

## Optional: use the Supabase database

The application database is the hosted PostgreSQL on Neon (see the section above). To move it to the Supabase project's PostgreSQL instead, mind two points of Supabase's own.

1. **The connection string.** In Supabase, open the project, then **Connect**. Use the **Direct connection** (port 5432), or the **Session pooler** (also port 5432) on a network without IPv6. Never the Transaction pooler on port 6543: it cannot keep the prepared statements asyncpg uses. Change the scheme and add `ssl=require`:

   ```
   DATABASE_URL=postgresql+asyncpg://postgres:YOUR_DB_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?ssl=require
   ```

   The password is the database password from **Project Settings > Database**, not an API key. Characters such as `@`, `#`, or `/` in it must be URL-encoded.

2. **Apply the migrations** once, from the project folder:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

   Revision 005 turns on row level security for every table. Supabase serves the public schema through its Data API to anyone with the project's publishable key, which is built into the mobile app; without row level security that key could read and change every table. The API connects as the tables' owner and is not restricted. Every future table needs row level security too: `tests/integration/test_row_level_security.py` fails otherwise.

Data in a previous database is not copied over. Evaluation reports can be loaded again with `python -m scripts.import_eval_reports`.

## Serve the mobile app

The app finds the API on the same computer as the Expo dev server, at port 8000.

1. Put the Supabase project in `.env` so the API accepts the app's sign-ins:

   ```
   SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
   ```

   The API checks the app's access tokens against the project's public signing keys; signing in needs no Supabase secret key. Add `SUPABASE_SECRET_KEY` (Supabase > Project Settings > API Keys, `sb_secret_...`) only so that deleting an account in the app also deletes the user's Supabase sign-in. Without it, deletion removes all the user's data here and reports `identity_deleted: false`.

   The daily prompt limit and push notifications work with their defaults (40 prompts per user per UTC day, push on). See `.env.example` to change them. To give one user a different limit, for example yourself while testing:

   ```sql
   UPDATE app_users SET daily_prompt_limit = 500 WHERE email = 'you@example.com';  -- 0: unlimited
   ```

2. Start the API so the phone can reach it, which `make dev-lan` also does:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   Windows may ask whether Python may accept connections on private networks; allow it. Only do this on a network you trust: the memory and console routes have no sign-in, and `--host 0.0.0.0` makes them reachable from every device on the network.

3. Start the app from the parent folder with `npx expo start`. Its `.env` needs only `EXPO_PUBLIC_SUPABASE_URL` and `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY`; see `docs/BACKEND.md` there.

Cooper needs `ANTHROPIC_API_KEY`. Connected apps need `COMPOSIO_API_KEY` and the browser needs `BROWSERBASE_API_KEY`; without them those tools are simply not offered. Schedules run inside the API while `SCHEDULER_ENABLED` is true, which is the default.

## Tests and other commands

`make` is usually not installed on Windows. These are the direct equivalents of the [Makefile](Makefile) targets:

| Makefile target | PowerShell command |
|---|---|
| `make install` | `python -m uv sync --all-extras` |
| `make dev` | `.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000` |
| `make worker` | `.\.venv\Scripts\python.exe -m scripts.process_pending` |
| `make migrate` | `.\.venv\Scripts\alembic.exe upgrade head` |
| `make migrate-down` | `.\.venv\Scripts\alembic.exe downgrade -1` |
| `make migration msg="x"` | `.\.venv\Scripts\alembic.exe revision --autogenerate -m "x"` |
| `make test` | `.\.venv\Scripts\pytest.exe tests -q` |
| `make test-unit` | `.\.venv\Scripts\pytest.exe tests/unit -v` |
| `make test-contract` | `.\.venv\Scripts\pytest.exe tests/contract -v` |
| `make test-golden` | `.\.venv\Scripts\pytest.exe tests/golden tests/integration/test_golden_pipeline.py -v` |
| `make test-integration` | `.\.venv\Scripts\pytest.exe tests/integration -v` |
| `make coverage` | `.\.venv\Scripts\coverage.exe run -m pytest tests -q`, then `.\.venv\Scripts\coverage.exe report` |
| `make lint` | `.\.venv\Scripts\ruff.exe check .` |
| `make format` | `.\.venv\Scripts\ruff.exe format .` |
| `make typecheck` | `.\.venv\Scripts\mypy.exe` |
| `make eval` | `.\.venv\Scripts\python.exe -m scripts.run_golden_eval` |
| `make import-eval-reports` | `.\.venv\Scripts\python.exe -m scripts.import_eval_reports` |
| `make connection-check` | `.\.venv\Scripts\python.exe -m scripts.check_anthropic_connection` |

Test status on 12 October 2026:

- All four suites pass: 887 tests (unit 373, contract 16, golden 140, integration 358).
- The unit and contract suites need no database. The golden suite reads `golden.jsonl`.
- The integration suite needs the local PostgreSQL to be running. It uses the database `second_brain_test` only, builds it with the real migrations, and empties it. It never touches the application database, whatever `.env` says.
- Never set `TEST_DATABASE_URL` to a database that holds data you want to keep. The tests empty it.
- The whole suite takes a few minutes. On a machine with little free memory, close heavy applications first and run nothing else heavy at the same time.
- No test calls a model. Tests cost nothing.

## Change the console

The source of the console is in `frontend\`. The built page in `frontend\dist` is what the API serves, and it is all you need to use the console. This section is only for changing it.

`frontend\dist` is not kept in version control. A fresh copy of the project has no console until it is built once, or until the folder is copied from a machine that has it.

You need Node.js 20.19 or newer. A portable copy needs no admin rights. This machine already has one in `%LOCALAPPDATA%\second-brain-node\`. On another machine:

```powershell
$node = "$env:LOCALAPPDATA\second-brain-node"
New-Item -ItemType Directory -Force $node | Out-Null
curl.exe -L -o "$env:TEMP\node.zip" "https://nodejs.org/dist/v24.21.0/node-v24.21.0-win-x64.zip"
tar.exe -xf "$env:TEMP\node.zip" -C $node
Remove-Item "$env:TEMP\node.zip"
```

In every new terminal, put Node on the path and work from the `frontend` folder:

```powershell
$env:Path = "$env:LOCALAPPDATA\second-brain-node\node-v24.21.0-win-x64;$env:Path"
cd frontend
```

| Command | What it does |
|---|---|
| `npm install` | Installs the packages. Needed once, and again after `package.json` changes. |
| `npm run build` | Type check, then build into `frontend\dist`. |
| `npm run dev` | Development server on <http://localhost:5173>. It needs the API on port 8000. |
| `npm run check` | Type check, lint, and unit tests. |
| `npm run api-types` | Regenerates `src\api\schema.d.ts` from `openapi.json`. |

When the API itself changed, refresh `frontend\openapi.json` first, with the API running: `curl.exe -o openapi.json http://localhost:8000/openapi.json`.

Restart the API after the first build, because it looks for `frontend\dist` only when it starts. Later builds show up on the next page reload.

**On this laptop, do a clean install first.** An interrupted installation left some packages in `frontend\node_modules` damaged. Until that is repaired, `npm run build`, `npm run dev`, and `npm run check` fail here. The console itself still works, because the built page in `frontend\dist` is already there. To repair it, close heavy applications, then run from the project root:

```powershell
Remove-Item -Recurse -Force frontend\node_modules
cd frontend
npm install
```

If `npm install` complains about the lock file, delete `frontend\package-lock.json` and run it again.

Two packages, `react-router` and `recharts`, are still listed in `package.json` and are no longer used by the code. After the clean install, remove them with `npm uninstall react-router recharts`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No Python at '...'` when running anything in `.venv` | The `.venv` was created on another computer | Run `python -m uv sync --all-extras` again |
| `Permission denied` while installing `uv` | Python is installed in a folder you cannot write to | Use the `--user` flag, as in step 1 |
| `/api/v1/health/ready` returns 503 | The database is not reachable | Start PostgreSQL as shown in [Everyday use](#everyday-use), or check `DATABASE_URL` |
| `pg_ctl start` fails, and `postgres.log` mentions the port | Another program already uses port 5432, often a Docker container or another PostgreSQL | Stop the other program. Find it with `netstat -ano` and look for `:5432` |
| PostgreSQL stops by itself, and its log mentions error 1450 | Windows ran out of memory | Close heavy applications and start PostgreSQL again. It recovers by itself |
| <http://localhost:8000> shows `Not Found` | `frontend\dist` does not exist, or the API was started before it was built | Build the console, see [Change the console](#change-the-console), then restart the API |
| Console screens show an error, and the API log shows a missing table or column | The database is behind the code | Run `.\.venv\Scripts\alembic.exe upgrade head` |
| The console says **No API key** and test calls are switched off | `ANTHROPIC_API_KEY` is missing in `.env` | Add the key and restart the API |
| The connectivity check prints `FAILED` and says the API key was rejected | `ANTHROPIC_API_KEY` in `.env` is wrong or still the placeholder | Paste a valid key, restart the API, and check again |
| A call fails with `EXTRACTION_PROVIDER_BILLING`: "The Anthropic account has no credit left or has a billing problem." | The Anthropic account has no credit | Add credit in the Anthropic console. Nothing needs to change here |
| An evaluation shows cases as **not evaluated** | The provider rejected calls during the run, for example for lack of credit | Fix the cause and start the run again. Such cases count as neither passed nor failed |
| The Evaluations screen says the dataset is unavailable | `golden.jsonl` is not at the project root, or `EVALUATION_DATASET_PATH` points elsewhere | Put the file in place or correct the setting, then restart the API |
| Console pages take seconds to load | The database is hosted far away | Expected. See [Use a hosted database](#use-a-hosted-database) |
| The API still runs old code after an edit | The server was started without `--reload` | Stop it with `Ctrl+C` and start it again |

The database log is at `%LOCALAPPDATA%\second-brain-postgres\postgres.log`.

## Remove the local database

This deletes PostgreSQL and all data stored in it.

```powershell
$pg = "$env:LOCALAPPDATA\second-brain-postgres"
& "$pg\pgsql\bin\pg_ctl.exe" stop -D "$pg\data"
Remove-Item -Recurse -Force $pg
```
