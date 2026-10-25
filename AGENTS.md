# Zoop - Developer & Agent Guide

This is an Expo/React Native application for **Zoop** (and AI companion **Cooper**) — an autonomous AI agent application tailored for recurring tasks, automated workflows, chat companion interactions, and scheduled operations.

---

## 🚀 Project Overview

- **App Name:** Zoop (package `com.museai.app`, URL scheme `memory`)
- **Core Concept:** Autonomous AI Agent & Chat Companion for Recurring Tasks, Goals, and Automated Workflows
- **Platform:** iOS, Android, and Web (Universal React Native)
- **Current Phase:** Full UI on Expo Router tabs, backed by the FastAPI backend in `memory-layer-for-life/` (chat with streamed replies, schedules, connected apps). The app has no server code of its own.

---

## 🛠️ Tech Stack

- **Framework:** [Expo](https://docs.expo.dev/) (SDK 58)
- **Runtime:** React Native 0.88.0 / React 19.3.0
- **Router:** [Expo Router](https://docs.expo.dev/router/introduction/) (File-based navigation in `src/app/`)
- **Vector Icons:** `@hugeicons/react-native` & `@hugeicons/core-free-icons`
- **Vectors & SVG:** `react-native-svg`
- **Design Tokens:** Centralized in `src/constants/colors.ts`
- **Safe Area:** `react-native-safe-area-context`
- **Sign-in:** Supabase Auth (Google) via `@supabase/supabase-js`, used for authentication only
- **Backend:** FastAPI + PostgreSQL (Neon) in `memory-layer-for-life/`; Cooper runs there on Claude Haiku
- **Streaming:** `expo/fetch` for the chat reply stream (React Native's global `fetch` cannot stream)

---

## 🎨 Design System & Color Tokens (`src/constants/colors.ts`)

Always reference and add color definitions in `src/constants/colors.ts`. Never hardcode ad-hoc hex values inside components.

| Token | Hex / Value | Purpose |
|---|---|---|
| `Colors.primary` | `#2563EB` | Primary brand blue |
| `Colors.chatBubbleUser` | `#E8C4B4` | Warm peach terracotta user chat bubble |
| `Colors.chatBubbleAi` | `#EEF0F2` | Soft light gray agent message bubble |
| `Colors.tabActiveBg` | `#E6E8EA` | Active tab pill capsule background in dock |
| `Colors.iconDark` | `#1E2022` | Dark charcoal for icons and typography |
| `Colors.iconMuted` | `#9E9E9E` | Secondary gray for placeholder and timestamps |
| `Colors.statusBlue` | `#0066FF` | Online indicator dot on header drawer button |
| `Colors.white` | `#FFFFFF` | Main background & floating capsules |

---

## 🔌 Backend & Data Rules

- **All data goes through the backend API** (`src/lib/api/*`). Never query Supabase tables, call Edge Functions, or add Expo API routes (`+api.ts`): server logic belongs in `memory-layer-for-life/`.
- **Supabase is for sign-in only.** `src/lib/supabase.ts` provides the session and `getAccessToken()`; `apiRequest()` sends the token as `Authorization: Bearer`.
- **Only three env vars reach the app:** `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and optionally `EXPO_PUBLIC_API_URL` (read in `src/lib/env.ts`). Never put a secret in an `EXPO_PUBLIC_*` variable; backend secrets live in `memory-layer-for-life/.env`.
- **Wire types mirror the backend exactly** (`src/lib/api/types.ts`, snake_case). Map them to UI types at the screen (`toUiMessage()` in `src/types/index.ts`).
- **Show `ApiError.message` to users**: the backend writes those messages for people.
- The contract is documented in `docs/BACKEND.md` and served live at `/docs` on the backend.
- The whole-system guide (how to run, code map, status, what is left) is `docs/PROJECT_GUIDE.md`. Keep it current when you change architecture or finish an item it lists.
- Deployment (environments, Fly.io, secrets, app builds) is `docs/DEPLOYMENT.md`; every feature with its tests, known issues, and the memory roadmap is `docs/FEATURE_GUIDE.md`. Keep both current when you change what they describe.
- **App variants:** `APP_VARIANT` (development, staging, production) picks the app's name, package, and URL scheme in `app.config.ts`. Never hard-code the scheme; build redirect URLs with `Linking.createURL`.

---

## 📁 Clean Directory Structure & Architecture

```
muse_ai_clone/
├── AGENTS.md                  # Project & agent guidelines
├── docs/BACKEND.md            # How the app talks to the backend
├── memory-layer-for-life/     # FastAPI backend (Python); excluded from Metro and tsc
├── metro.config.js            # Keeps Metro from crawling the backend
├── app.json / app.config.ts   # App config; app.config.ts adds per-build settings
├── eas.json                   # EAS build profiles: local, staging, production (APKs), store (AAB)
├── package.json               # Dependencies & scripts
├── assets/
│   └── images/
│       └── cooper_mascot.jpg  # 3D character mascot avatar portrait
├── src/
│   ├── app/                   # Expo Router file-based screens
│   │   ├── _layout.tsx        # Root Stack navigator & ThemeProvider
│   │   ├── index.tsx          # Google Sign-in onboarding screen (Self-contained)
│   │   ├── home.tsx           # Compatibility redirect to /(tabs)/chat
│   │   ├── tools.tsx          # Tools & Connections (Composio apps via the backend)
│   │   └── (tabs)/            # Dedicated 5-Tab Routing & Layout
│   │       ├── _layout.tsx    # Master Tab Layout (AppHeader + Native Tabs + Modals)
│   │       ├── index.tsx      # Tab index redirect to /chat
│   │       ├── chat.tsx       # 1. Chat Tab: Messages list, peach/gray bubbles, input pill
│   │       ├── feed.tsx       # 2. Feed Tab: Minimalist autonomous intelligence feed
│   │       ├── ideas.tsx      # 3. Ideas Tab: 1-tap pre-built automation templates
│   │       ├── tasks.tsx      # 4. Tasks Tab: Scheduled goals & recurring routine manager
│   │       └── settings.tsx   # 5. Settings Tab: Quota card, groups, and integrated sheets
│   ├── components/            # Core Shared UI Layout Components
│   │   ├── common/            # Header, Mascot, Drawer, Customizer & Settings Modals
│   │   └── tools/             # Tool card & manage modal
│   ├── lib/
│   │   ├── env.ts             # The EXPO_PUBLIC_* variables and the API URL
│   │   ├── supabase.ts        # Supabase client, sign-in only
│   │   └── api/               # Backend client: threads, chatStream, schedules, tools, me
│   ├── types/                 # UI types (+ API-to-UI mappers)
│   └── constants/
│       ├── colors.ts          # Central color palette
│       ├── dummyData.ts       # Initial chat & sample workflows
│       └── theme.ts           # Spacing and typography
```

---

## ⚡ Useful Commands

```bash
# Start the Expo development server
npx expo start

# Typecheck the whole project
npx tsc --noEmit

# Install compatible packages (ALWAYS use this instead of npm i / yarn add)
npx expo install <package-name>

# Build an installable Android app on EAS (docs/DEPLOYMENT.md section 6)
npx eas-cli build -p android --profile production

# Deploy the backend (from memory-layer-for-life/; docs/DEPLOYMENT.md)
.\deploy\push-image.ps1 -Image docker.io/<user>/muse-api   # free setup (Render)
.\deploy\deploy.ps1 staging                                 # full setup (Fly.io)

# Backend (from memory-layer-for-life/): migrate, then serve it to phones on the network
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Backend checks
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check . ; .\.venv\Scripts\python.exe -m mypy
```
