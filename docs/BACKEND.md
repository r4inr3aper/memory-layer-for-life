# Backend Integration

The app has no server code of its own. Everything that needs a secret, a database, or a model runs in the FastAPI backend in [`memory-layer-for-life/`](../memory-layer-for-life/README.md). The app signs users in with Supabase Auth and sends their access token to that backend.

```
┌──────────────── Expo app ────────────────┐        ┌──────────── memory-layer-for-life (FastAPI) ────────────┐
│ Supabase Auth (Google)  → access token   │ Bearer │ verifies the token (Supabase JWKS)                      │
│ src/lib/api/*  ─────────────────────────────────► │ threads · messages · schedules · app connections        │
│ chat reply stream (NDJSON, expo/fetch)   │ ◄───── │ Cooper on Claude, Composio, Browserbase, scheduler      │
└──────────────────────────────────────────┘        │ PostgreSQL on Neon (row level security on every table)  │
                                                    └─────────────────────────────────────────────────────────┘
```

What moved where:

| Before                                                                                                                        | Now                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Expo API routes (`src/app/api/*`) running OpenAI Agents, Composio, Browserbase                                                | `POST /api/v1/threads/{id}/messages` on the backend, Cooper on Claude                        |
| Screens querying Supabase tables (`chat_threads`, `chat_messages`, `tools`, `user_tool_connections`, `scheduled_agent_tasks`) | Backend endpoints over the backend's own database (Neon); the app never reads a database     |
| Supabase Edge Function `agent-run` + `pg_cron`                                                                                | Backend scheduler loop (or `python -m scripts.run_schedules`)                                |
| Client saved both sides of the chat                                                                                           | Server stores the user message and the reply; the reply is saved even if the app disconnects |
| Schedule intent parsed by a separate OpenAI call per message                                                                  | Cooper calls a `propose_schedule` tool; nothing is created until the user confirms the card  |

## Environment

The app reads exactly three variables, from `.env` in the project root. Expo only exposes `EXPO_PUBLIC_*` variables, and only these three are used:

```bash
EXPO_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
# Optional in development: defaults to the Expo dev server's host on port 8000.
EXPO_PUBLIC_API_URL=http://192.168.1.20:8000
```

The publishable key is public by design: it only lets the app sign in. The data lives in a separate PostgreSQL database on Neon that only the backend can reach. Never put the Supabase secret key, a database password, or a provider API key in an `EXPO_PUBLIC_*` variable.

## Running both halves

1. Start the backend so a phone on the same Wi-Fi can reach it (see [RUN_LOCALLY.md](../memory-layer-for-life/RUN_LOCALLY.md) for the one-time setup):

   ```powershell
   cd memory-layer-for-life
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. Start the app: `npx expo start`. On a phone, the API URL defaults to the dev server's host on port 8000, so it works without `EXPO_PUBLIC_API_URL` when both run on the same computer.

   **Google sign-in in Expo Go needs a hostname, not an IP.** Supabase Auth refuses any redirect address whose host is a raw IP (`exp://192.168.1.2:8081/...`), even when it is on the allow-list, and sends the user to the Site URL (`localhost:3000`) instead. Serve the app under a hostname with `.env.local` (Expo refuses this setting in `.env`):

   ```bash
   # .env.local — 192-168-1-2.nip.io resolves to 192.168.1.2; use your computer's address
   REACT_NATIVE_PACKAGER_HOSTNAME=192-168-1-2.nip.io
   ```

   Open `exp://192-168-1-2.nip.io:8081` in Expo Go, and allow `exp://**` under Supabase > Authentication > URL Configuration > Redirect URLs. The app then reaches the backend at `http://192-168-1-2.nip.io:8000` too.

3. Check the wiring: sign in, then open `http://<computer-ip>:8000/docs` and look for your request to `/api/v1/threads/main` in the backend log.

## Client modules

| Module                      | Purpose                                                                                                                    |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `src/lib/env.ts`            | Reads the three variables and derives the API URL                                                                          |
| `src/lib/supabase.ts`       | Supabase client for **auth only**; `getAccessToken()`                                                                      |
| `src/lib/api/client.ts`     | `apiRequest()`: bearer token, JSON, typed `ApiError` (`status`, `code`, `message`)                                         |
| `src/lib/api/types.ts`      | Wire types, exactly as the API sends them (snake_case)                                                                     |
| `src/lib/api/threads.ts`    | Threads, messages, schedule proposals                                                                                      |
| `src/lib/api/chatStream.ts` | `streamReply()`: the reply stream over `expo/fetch`                                                                        |
| `src/lib/api/schedules.ts`  | Schedules and runs, including run polling                                                                                  |
| `src/lib/api/tools.ts`      | App connections                                                                                                            |
| `src/lib/api/me.ts`         | The signed-in user: assistant profile, notification setting, usage, push tokens, feedback, data export, account deletion   |
| `src/lib/api/memories.ts`   | Memories: list, search, detail, write, correct, accept, retract, restore, merge, replace, delete; the review inbox; people |
| `src/lib/api/sources.ts`    | WhatsApp imports, photos and PDFs as memories, Google Calendar as a source                                                 |
| `src/lib/api/insights.ts`   | Insights for the Feed, and feedback on them                                                                                |
| `src/lib/api/life.ts`       | Life state: the to-do overview, done/drop/reopen, due dates and reminders, the brief preview, chat search                  |
| `src/lib/api/activity.ts`   | Finished scheduled runs, for the Feed                                                                                      |
| `src/lib/api/today.ts`      | The Feed's cards: next actions, promises, meetings, something to pick up again, memories to confirm                        |
| `src/lib/api/documents.ts`  | My files: documents the assistant reads (upload, list, show with text, mark the resume, delete)                            |

Error messages from the API (`ApiError.message`) are written for people and safe to show in a toast.

## API

All routes are under `/api/v1` and need `Authorization: Bearer <Supabase access token>`. The full, interactive contract is at `/docs` on the running backend.

| Area                   | Routes                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User                   | `GET /me`, `PATCH /me` (assistant name, subtitle, icon, color; notifications on or off), `DELETE /me` (delete the account), `GET /me/export` (all the user's data as a JSON attachment), `GET /me/usage`, `GET /me/usage/history`, `POST /me/push-tokens`, `DELETE /me/push-tokens/{token}`                                                                         |
| Memories               | `GET /me/memories` (`status` repeatable; default proposed and active; `order=oldest`), `POST /me/memories` (write one), `POST /me/memories/search`, `GET/PATCH/DELETE /me/memories/{id}`, `POST /me/memories/{id}/accept`, `.../retract`, `.../restore`, `.../merge`, `.../replace` (body `other_memory_id`)                                                        |
| Review                 | `GET /me/memories/review` (proposed count, suggestions, held-back messages), `POST /me/memories/review/accept` (`memory_ids`, up to 100), `POST /me/memories/review/dismiss`, `POST /me/memories/held-back/{run_id}/save`, `POST /me/memories/held-back/{run_id}/dismiss`                                                                                           |
| People                 | `GET /me/people` (`entity_type` filter), `GET /me/people/{id}`, `PATCH /me/people/{id}` (`name`), `POST /me/people/{id}/merge` (`other_person_id`)                                                                                                                                                                                                                  |
| Today                  | `GET /me/today` (the Feed's cards, computed without a model)                                                                                                                                                                                                                                                                                                         |
| Documents              | `GET /me/documents`, `POST /me/documents` (`name`, `media_type`, `data` base64: PDF, .docx, text, Markdown; 10 MB; the file is kept, 50 MB per user), `GET /me/documents/{id}` (with its text), `GET /me/documents/{id}/file` (the file, base64), `PATCH /me/documents/{id}` (`title`, `is_resume`), `DELETE /me/documents/{id}`                                     |
| Links                  | `GET /me/links`, `POST /me/links` (`url`, optional `title` and `kind`: resume, portfolio, linkedin, github, website, other), `PATCH /me/links/{id}`, `DELETE /me/links/{id}`. Cooper shares them by address and attaches kept files by reference (ADR-050)                                                                                                           |
| Life                   | `GET /me/life` (also `questions` and import `triage`), `GET /me/life/brief` (preview), `POST /me/memories/{id}/complete`, `.../drop`, `.../reopen`; due dates and reminders through `PATCH /me/memories/{id}` (`due_on`, `remind_at`, null clears) and `POST /me/memories`                                                                                                                                 |
| Chat search            | `POST /me/messages/search` with `{ "query": "..." }`                                                                                                                                                                                                                                                                                                                |
| Insights               | `GET /me/insights`, `POST /me/insights/feedback` (`key`, `kind`, `useful`)                                                                                                                                                                                                                                                                                          |
| Sources                | `POST /me/imports/whatsapp` (`file_name`, `data_base64`), `POST /me/imports/{id}/start` (`me`, `since`, `only_my_conversations`, `max_conversations`), `GET /me/imports`, `GET /me/imports/{id}`, `POST /me/memories/from-file` (`file_name`, `media_type`, `data_base64`), `GET /me/sources`, `PATCH /me/sources/{app}` (`enabled`), `POST /me/sources/{app}/sync` |
| Feedback               | `POST /feedback`                                                                                                                                                                                                                                                                                                                                                    |
| Threads                | `GET /threads`, `POST /threads` (side thread), `POST /threads/main` (get or create), `GET /threads/{id}`, `DELETE /threads/{id}`, `DELETE /threads/{id}/messages` (clear)                                                                                                                                                                                           |
| Messages               | `GET /threads/{id}/messages` (most recent, oldest first), `POST /threads/{id}/messages` (reply stream; text, files, or both)                                                                                                                                                                                                                                        |
| Proposals              | `POST /threads/{id}/messages/{message_id}/proposal/confirm`, `.../proposal/dismiss`                                                                                                                                                                                                                                                                                 |
| Job application drafts | `POST /threads/{id}/messages/{message_id}/job-application/send` (send the draft card's email through its configured app and update status)                                                                                                                                                                                                                          |
| Schedules              | `GET /schedules`, `POST /schedules` (from the app's form), `GET /schedules/{id}`, `PATCH /schedules/{id}` (edit, pause, resume, cancel), `DELETE /schedules/{id}`, `POST /schedules/{id}/runs` (run now), `GET /schedules/{id}/runs`, `GET /schedules/{id}/runs/{run_id}`                                                                                           |
| Activity               | `GET /activity` (finished scheduled runs, newest first, with the thread each result went to)                                                                                                                                                                                                                                                                        |
| Apps                   | `GET /tools`, `POST /tools/{slug}/connect`, `GET /tools/{slug}/connection`, `DELETE /tools/{slug}/connection`                                                                                                                                                                                                                                                       |

### The reply stream

`POST /threads/{id}/messages` with `{ "content": "...", "timezone": "Asia/Kolkata" }` answers with newline-delimited JSON:

| Event          | When                                                                                                                                                                           |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `turn_started` | The user message was stored (`user_message`)                                                                                                                                   |
| `text_delta`   | A piece of the reply text; append it                                                                                                                                           |
| `tool_started` | Cooper started a tool; `label` is what to show, e.g. "Browsing the web"                                                                                                        |
| `browser`      | A cloud browser started or changed state; `browser_preview.live_view_url` can be shown live                                                                                    |
| `connect_link` | An app needs connecting; show the Connect card                                                                                                                                 |
| `final`        | The stored reply (`message`), with its cards in `metadata`                                                                                                                     |
| `error`        | The turn failed; `message` says why. The user message stays stored                                                                                                             |
| _(blank line)_ | A keep-alive, sent every 15 s while the reply is quiet (a long browser task, say), so proxies in front of a hosted API keep the connection open. Skip it; `chatStream.ts` does |

A request the server refuses before streaming (404, 409 while a reply is running, 422, 429 over the daily prompt limit, 503) is a normal JSON error. React Native's global `fetch` cannot read a body incrementally, which is why `chatStream.ts` uses `expo/fetch`.

Assistant replies can also carry `metadata.job_application_draft`, a review card with the final email fields (`recipient_email`, `subject`, `body`, source LinkedIn URL, chosen app/tool, and status). Tapping Send calls the endpoint above; the backend executes the stored app action and writes the card status to `sent` or `failed`.

### Who may sign in, and request size

A deployment can list its users in `ACCESS_ALLOWED_EMAILS`. Anyone else who signs in gets 403 `ACCESS_NOT_ALLOWED` on every route, with a message saying the deployment is private; the API keeps nothing about them. Request bodies over `MAX_REQUEST_BYTES` (25 MB, room for three 5 MB files in base64) get 413 `REQUEST_TOO_LARGE` before they are read. Both use the usual error format, so the app shows `message`.

### Schedules

Cooper proposes a schedule as a card on its reply (`metadata.schedule_proposal`). Confirming creates the schedule exactly as proposed; the server reads the proposal from the stored message, not from the request. Each slot runs once even with several backend processes.

A rule is a time (`local_time`, HH:MM) in `timezone` with a `frequency`:

- `once` on `start_date`;
- `daily`;
- `weekly` on `weekdays` (one or more days);
- `monthly` on `day_of_month` (a shorter month runs on its last day);
- `interval`, every `interval_hours` (1 to 24) from `start_date` at `local_time` (default: starting today).

Responses include `next_run_local`, the next run as `YYYY-MM-DDTHH:MM` in the schedule's own timezone: show it as is, with the timezone. A one-time schedule becomes `completed` after its slot.

`PATCH` changes only the fields sent; to change the rule, send only what differs. `DELETE` removes the schedule and its history (409 while it is running).

Results can go only to chat or to an app the user has connected; anything else is refused with a message to show.

A slot found more than an hour late (when the backend was down), or due while an earlier run is still going, is skipped: it appears in the schedule's runs with `status: "skipped"` and an `error_message` saying why, but not in the Feed. Results delivered to chat appear as a new assistant message in the thread the schedule came from (`metadata.scheduled_run`). A run that delivers to an app (Slack, email, ...) may change data only in that app.

### App connections

The catalog is defined on the backend (`app/domain/tool_catalog.py`) and identified by slug (`gmail`, `slack`, ...). Connecting returns a Composio `connect_url` to open in the browser; afterwards `GET /tools/{slug}/connection` asks Composio for the result. Disconnecting removes every connected account of that app, because the assistant would otherwise keep using whichever one was left.

### Daily prompt limit

A prompt is a chat message the user sends or a scheduled run. Each user gets `ASSISTANT_DAILY_PROMPT_LIMIT` prompts (default 40) per UTC day, counted in the backend's `daily_usage` table; `app_users.daily_prompt_limit` overrides it for one user. Over the limit, sending answers 429 with `error_code` `QUOTA_EXCEEDED` and a message that says when more are available in the user's time ("... after 05:30 (Asia/Kolkata)"); nothing is stored. Show `message` to the user. A scheduled run over the limit fails with the same error and does not call the model. `GET /me/usage` returns the meter Settings shows: `prompts_used`, `prompt_limit` (null when unlimited), `prompts_remaining`, `resets_at`, and today's `estimated_cost_usd`. `GET /me/usage/history?granularity=day|week|month` returns prompts and estimated model cost for the last 14 days, 12 weeks, or 12 months (UTC; weeks start on Monday), oldest first, for the cost chart. There is no billing.

### Files in chat

`POST /threads/{id}/messages` accepts `attachments`: up to 3 images (JPEG, PNG, GIF, WebP) or PDFs of up to 5 MB each, as base64 without a `data:` prefix. `content` may then be empty. Claude sees the files with that message only; the server keeps their names, types, and sizes in `metadata.attachments`, not the files.

### Push notifications

When a scheduled run ends, the backend sends an Expo push notification to each device the user registered with `POST /me/push-tokens`, unless `notifications_enabled` is false. The notification's `data` holds `scheduled_task_id`, `run_id`, and, for results posted to chat, `thread_id`. Getting a push token needs an installed build of the app with an Expo project id (`eas init`); Expo Go on Android cannot receive push notifications.

### Deleting an account

`DELETE /me` revokes the user's connected apps in Composio, deletes everything the backend holds for them, and deletes their Supabase sign-in when the backend has `SUPABASE_SECRET_KEY`. The response says how many apps could not be revoked (`apps_not_disconnected`), so the app can tell the user to revoke those in each app, and whether the sign-in was deleted. Sign the user out afterwards.

### Managing memories (ADR-044)

Every memory carries `created_by` (`pipeline` or `user`) and `sensitive`.

- **Statuses:** `proposed` (saved from chat, not reviewed), `active` (accepted or written by the user), `superseded` (replaced by a newer version or merged into another memory), `retracted` (marked as wrong).
- **Detail:** `GET /me/memories/{id}` returns the messages the memory rests on, each with `thread_id` while that chat still exists. It also returns the people it mentions, `history` (oldest first), the versions it `replaced`, and, when superseded, `replaced_by_id`.
- **Corrections:** `PATCH` with new `content` creates a new version with its own id, so follow the `id` in the response. Kind (`memory_type`) and `sensitive` change in place.
- **Deleting:** `DELETE` removes the memory and the older versions it replaced, and returns `deleted`. Chat messages stay; deleting a chat likewise keeps its memories.
- **Review inbox:** `GET /me/memories/review` returns `proposed_count`; list those memories with `GET /me/memories?status=proposed`. It also returns `suggestions`:
  - `duplicate`: merge with `POST /me/memories/{newer}/merge`;
  - `conflict`: keep the newer with `POST .../{newer}/replace`;
  - keep both: `POST /me/memories/review/dismiss`.

  Its `held_back` list holds messages Cooper would not turn into memories on its own. `reason` is `unclear` or `unreadable`. Save a memory from one with `.../held-back/{run_id}/save`, or dismiss it.

- **Sensitive memories** are shown here and never sent to Cooper, scheduled runs, or any model.
- **Export:** `GET /me/export` returns everything, sensitive memories included, as one JSON document. The app saves it and opens the share sheet.

### New memory sources (ADR-047)

- **WhatsApp:**
  - `POST /me/imports/whatsapp` with the export (`.txt` or `.zip`, base64, up to 10 MB) returns the `participants` (messages and conversations each), `all_conversations`, and `cost_per_conversation` in `currency`. Nothing is imported yet.
  - `POST /me/imports/{id}/start` with `me` (one of the participants), and optionally `since`, `only_my_conversations` (default true), and `max_conversations` (default 200, at most 300, most recent kept), queues one extraction per conversation.
  - `GET /me/imports/{id}` returns `progress` (`done`, `failed`, `waiting`, `memories`).
  - The same file again returns the same preview, or 422 once it has been imported.
- **Photos and PDFs:** `POST /me/memories/from-file` uses one of today's prompts. It returns the `text` read from the file, and memories follow in the background. The same file again returns `created: false` without reading it again. Expect 502 when the file cannot be read, and 503 without a model key.
- **Google Calendar:**
  - `GET /me/sources` lists the apps that can be sources, with `enabled`, `last_synced_at`, and `error` (show it).
  - `PATCH /me/sources/googlecalendar` with `{ "enabled": true }` syncs at once. The next 14 days of events become plans in the To do list.

### Insights (ADR-046)

`GET /me/insights` returns `items`, strongest first. Each has a `key`, a `kind` (`money`, `people.top`, `people.quiet`, `follow_through`, `goal.quiet`, `theme`), `title`, `body`, the `memory_ids` it rests on, and where it leads (`target` is `person`, `memory`, `todo`, or `memories`, with `target_id`). They are computed from the user's memories without any model.

`POST /me/insights/feedback` with `{ key, kind, useful }` records the answer. `useful: false` hides that insight for its period. The Feed shows insights under "For you".

### Life state, reminders, and the daily brief (ADR-045)

Memories carry `state`, `due_on` (YYYY-MM-DD), `remind_at`, `closed_at`, and `close_reason` (`done` or `dropped`).

- **Overview:** `GET /me/life` returns open items grouped by when they are due, in the user's timezone: `overdue`, `due_today`, `upcoming` (7 days), `later`, `someday`. It also returns `goals`, `stale_ids` (untouched for 14 days), pending `reminders`, and `recently_done`.
- **Changing items:**
  - Close an item with `POST .../complete` or `.../drop`, and undo either with `.../reopen`.
  - Set or clear `due_on` and `remind_at` with `PATCH /me/memories/{id}`. `remind_at` needs a timezone offset and must be in the future.
  - A to-do written with `POST /me/memories` (`memory_type: task`, `plan`, or `goal`) starts open and may carry both fields.
- **Preferences (`PATCH /me`):**
  - `timezone` (the app sends the phone's after each sign-in);
  - `brief_enabled` and `brief_time` (HH:MM);
  - `reminders_enabled`;
  - `quiet_hours_start` and `quiet_hours_end` (send both, or both null).
- **What the backend posts to the main chat:**
  - A due reminder, with `metadata.reminder` (`memory_id`, `sensitive`). Show Done, In 1 hour, and Tomorrow.
  - The daily brief, at `brief_time`, with `metadata.brief.follow_ups` (items due yesterday). Show Done and Not yet; Not yet moves the item to today.

  Both are pushed, with `thread_id` and `message_id` in the notification's data. Quiet hours silence only the brief's push. A sensitive reminder never shows its text.

- **Chat search:** `POST /me/messages/search` returns `items` with `thread_id`, `thread_title`, `role`, and a `snippet` whose matches are wrapped in `<<` and `>>`.

### Memories from chats

Once a chat has been quiet for five minutes, what the user wrote since the last capture (never the assistant's replies, which travel only as context) is captured as one unit of memory evidence and processed by the memory pipeline (ADR-048); its memories then appear in `GET /me/memories` (newest first, paged), and each message of `GET /threads/{id}/messages` lists the memories it is evidence for in `saved_memories`, for the app's Undo. Greetings, thanks, approvals, and resends cost no model call. The same call names a side chat from its conversation; until then it is named from its first message. They are the user's only: the evidence, the people and places it mentions, and the memories carry the user as owner, and deleting the account deletes them. `PATCH /me` with `memory_capture_enabled: false` stops capture for the user. The app registers the phone for push after every sign-in (one permission prompt if notifications are on and it never asked) and unregisters it before signing out (ADR-042). Memories the pipeline is sure of (confident, not sensitive, the user's own words) are saved `active`; the rest stay `proposed` for review. A memory said again gets the new evidence instead of a duplicate. Cooper recalls them with its `search_memories` tool (shown as "Checking your memories"), and `POST /me/memories/search` with `{ "query": "..." }` searches them directly: each result carries the memory, the message it rests on (`sources[].evidence`), the people it names, and which kinds of match found it. The query goes in the body, never the URL. Without embeddings configured on the backend, search uses words and names only; `degraded: true` means the backend's embedding provider failed for this search. Costs are shown in `currency` (rupees by default): `GET /me/usage` returns `estimated_cost`, and the history returns `cost` per period and `total_cost`, converted from the USD amounts at the backend's fixed rate (`USAGE_CURRENCY_PER_USD`).
