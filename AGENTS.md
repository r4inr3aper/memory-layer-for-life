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

## 🎨 Design System (iOS design language)

The app looks and feels like an Apple app: the system font in iOS text styles, inset-grouped lists on a gray background, white cards, hairline separators, system blue as the tint, continuous corners, and motion that answers the finger at once. The rules come from Emil Kowalski's design-engineering skills (`apple-design`, `animate-expo`). Light appearance only (`app.json`).

**Tokens.** Never hardcode a hex value in a component; add a token instead.

- `src/constants/colors.ts`: use the semantic iOS tokens: `tint`, `systemBackground` (white screens such as Chat), `groupedBackground` (`#F2F2F7`, behind lists, settings, Today), `secondaryGroupedBackground` (white cells and cards), `label` / `secondaryLabel` / `tertiaryLabel`, `fill` … `quaternaryFill` (control fills), `separator`, `cellPressed`, `system*` colors (`systemRed` for destructive, `systemGreen` for success), `scrim`, `hud`. The older names (`primary`, `textSecondary`, `iconDark`, …) map onto the same palette and still work.
- `src/constants/theme.ts`: `Typography` (iOS text styles: `largeTitle` 34, `title1` 28, `title2` 22, `title3` 20, `headline` 17 semibold, `body` 17, `callout` 16, `subheadline` 15, `footnote` 13, `caption1` 12, `caption2` 11; tracking is size-specific per platform), `Radius` (`sm` 8, `md` 12, `lg` 16 for cards, `sheet` 24, `pill`), `continuous` (spread it next to any radius for squircle corners), `Hairline`, `ScreenMargin` (16), `Motion` (curves, durations, springs), `Elevation` (`floating` for menus and toasts, `raised` for a segmented thumb).

**Primitives** (`src/components/ui`, import from `@/components/ui`):

| Component | Use |
| --- | --- |
| `AppText` | All text: `variant` (a Typography key) and `color` (`primary`, `secondary`, `tertiary`, `tint`, `destructive`, `success`, `inverse`, or a color). |
| `PressableScale` | Every tappable surface that is not a list row: scales to 0.97 on press-in over 120 ms (a Reanimated CSS transition), dims instead with Reduce Motion. |
| `Button` | `filled` (the one primary action), `tinted`, `gray`, `plain`, `destructive`; sizes `large` 50, `medium` 44, `small` 32 capsule; `loading`, `icon`, `block`. |
| `IconButton` | Round glyph buttons in bars (`filled`) or inside content (`plain`, `tinted`); 44 pt touch target whatever the visual size. |
| `ListSection` + `ListRow` | Settings-style inset-grouped lists: header (uppercase footnote), footer, rows with an `icon` tile, `subtitle`, `value`, `accessory` (`chevron`, `check`, a switch, anything), `destructive`, `action` (a centered tinted row that is a button), `subtitleColor` (a status), `selected`/`expanded` (announced to VoiceOver), `accessibilityHint`. Rows highlight while pressed; they do not scale. |
| `Card` | A white rounded surface on the grouped background for content that is not a row; pressable cards scale to 0.98. No borders, no shadows. |
| `SegmentedControl` | iOS segmented control with a sliding thumb and a selection haptic; optional `badge` counts. |
| `AppSwitch` | The platform switch in iOS green, with a selection haptic. |
| `BottomSheet` | Sheets inside a screen (editors, pickers, menus): spring in, drag the grabber or title bar to dismiss with momentum, rubber-band at the top, Cancel and Save/Done in the title bar, `scrollable` for long forms, keyboard-aware. Use it instead of a raw `Modal`. |
| `EmptyState` | A glyph in a soft circle, a title naming what is missing, one sentence, at most one action; `compact` inside a section. |
| `ScreenHeader`, `LargeTitle`, `useScrollY` | The navigation bar of pushed screens. With `LargeTitle` at the top of the content and `scrollY` from `useScrollY()` (on an `Animated.ScrollView`/`Animated.FlatList`), the bar's small title and hairline appear only once the large title scrolls under it. |

**Haptics** (`src/lib/haptics.ts`, `haptic.selection()`, `.light()`, `.medium()`, `.success()`, `.warning()`, `.error()`): one per user action, in the same frame as the visual, never the only feedback. A selection tick when a value steps; light when something commits or snaps home; success or error when an operation the user waited on finishes. Never on scroll, tab switches, toasts, or entrance animations.

**Motion rules.**
- Tab switches, keyboard, scrolling, and toggles in lists never animate beyond the platform's own behavior.
- Press feedback: 100–150 ms, strong ease-out (`Motion.css.easeOut`), as a CSS transition, never a worklet.
- Only `transform` and `opacity` animate (an absolutely positioned childless element, like a segmented thumb, may animate `width`). Never animate from `scale(0)`; start at 0.95 with opacity 0.
- Never ease-in. Entering and leaving: `Motion.easeOut`; moving across the screen: `Motion.easeInOut`; anything a finger moved: a spring with the gesture's velocity (`Motion.spring`).
- Layout-animation builders (`FadeIn…`) live at module scope. Never put `entering` on rows of a `FlatList`.
- Use Reanimated, never core `Animated` or `LayoutAnimation`; `.get()`/`.set()` on shared values, never during render; `scheduleOnRN`, not `runOnJS`.
- Respect Reduce Motion (`useReducedMotion`): cross-fade instead of slide or scale.
- Screens are pushed with the native stack's own transition (`src/app/_layout.tsx`); never rebuild a screen transition in JS.

**Layout.** List-like screens use `groupedBackground` with `ListSection`s and `Card`s; the chat stays white. Screen margins are 16. Touch targets are at least 44 pt (`hitSlop` on small visuals). Copy is short and specific; destructive actions confirm through `confirmAsync`, and everything else is undoable or harmless.

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
