# 📖 Zoop — Comprehensive Codebase & Architecture Guide

Welcome to the comprehensive technical documentation for **Zoop** (and autonomous companion **Cooper**). This document provides an exhaustive, file-by-file breakdown of the current architecture, explaining each module's responsibility, state flow, UI components, design tokens, and interactions across the application.

---

## 📑 Table of Contents

1. [Architectural Overview](#-architectural-overview)
2. [Codebase Tree & Directory Structure](#-codebase-tree--directory-structure)
3. [Exhaustive File-by-File Guide](#-exhaustive-file-by-file-guide)
   - [Root Configuration Files](#1-root-configuration-files)
   - [Navigation & Screens (`src/app/`)](#2-navigation--screens-srcapp)
   - [Common Layout & Navigation (`src/components/common/`)](#3-common-layout--navigation-srccomponentscommon)
   - [Global Context (`src/context/`)](#4-global-context-srccontext)
   - [Constants & Mock Datasets (`src/constants/`)](#5-constants--mock-datasets-srcconstants)
   - [Data Types & Interfaces (`src/types/`)](#6-data-types--interfaces-srctypes)
4. [Component Hierarchy & Data Flow](#-component-hierarchy--data-flow)
5. [Design System & Color Tokens](#-design-system--color-tokens)
6. [Commands & Developer Workflow](#-commands--developer-workflow)

---

## 🏛️ Architectural Overview

**Zoop** is a Universal React Native application built with **Expo (SDK 58)** and **React Native 0.88.0**. It runs seamlessly across iOS, Android, and Web browsers.

### Key Architectural Highlights:
- **Expo Router Tab Navigation:** Clean file-based routing with a dedicated `(tabs)` group for the 5 core tabs (`chat`, `feed`, `ideas`, `tasks`, `settings`).
- **Keyboard-Adaptive Chat UI:** Built with `KeyboardAvoidingView`, dynamic safe-area insets, auto-scrolling to recent messages, tap-outside dismissal, and native `tabBarHideOnKeyboard: true` support.
- **Backend-driven AI Agent:** The app has no server code. Chat, history, schedules, and app connections are served by the FastAPI backend in `memory-layer-for-life/`, where Cooper runs on Claude with Composio and Browserbase tools. Replies stream to the app as newline-delimited JSON. See [BACKEND.md](./BACKEND.md).
- **Supabase for sign-in only:** The app uses Supabase Auth (Google) and sends the access token to the backend. It never reads a database; the backend owns the data, in its own PostgreSQL database on Neon.
- **Centralized Design Tokens:** All colors, spacing, and typography are defined in `src/constants/colors.ts` and `src/constants/theme.ts`.
- **Modular Component Layout:** Clean shared headers, mascots, sliding session drawers, action sheets, and customization modals in `src/components/common/`.
- **Global Toast Notification Context:** Lightweight toast messaging in `src/context/ToastContext.tsx`.

---

## 🌲 Codebase Tree & Directory Structure

```
muse_ai_clone/
├── AGENTS.md                          # Agent rules and developer guidelines
├── README.md                          # Quick start and project overview
├── app.json                           # Expo app configuration & branding assets
├── docs/                              # Implementation documentation
│   ├── BACKEND.md                     # How the app talks to the backend (env, API, reply stream)
│   └── CODEBASE_EXPLANATION.md        # Complete file-by-file codebase guide (this file)
├── memory-layer-for-life/             # FastAPI backend (Python); excluded from Metro and tsc
├── metro.config.js                    # Keeps Metro from crawling the backend folder
├── package.json                       # Project dependencies & npm scripts
├── tsconfig.json                      # TypeScript compiler path aliases (@/*)
├── assets/                            # Static media and app icons
│   ├── expo.icon/                     # iOS App icon asset catalog
│   └── images/
│       ├── android-icon-*.png         # Android adaptive icon layers
│       ├── cooper_mascot.jpg          # 3D Cooper Mascot avatar portrait
│       ├── favicon.png                # Web browser favicon
│       ├── icon.png                   # Primary Expo application icon
│       └── splash-icon.png            # App launch splash screen emblem
└── src/
    ├── app/                           # Expo Router file-based screens
    │   ├── _layout.tsx                # Root layout, ThemeProvider, ToastProvider & Stack
    │   ├── index.tsx                  # Google Sign-in onboarding screen (Self-contained)
    │   ├── home.tsx                   # Compatibility redirect to /(tabs)/chat
    │   ├── tools.tsx                  # Tools & Connections screen
    │   └── (tabs)/                    # Dedicated 5-Tab Routing & Layout
    │       ├── _layout.tsx            # Master Tab Layout (AppHeader + Native Tabs + Modals)
    │       ├── index.tsx              # Tab index redirect to /chat
    │       ├── chat.tsx               # 1. Chat Tab: Message thread, peach/gray bubbles, input pill
    │       ├── feed.tsx               # 2. Feed Tab: Minimalist autonomous intelligence feed
    │       ├── ideas.tsx              # 3. Ideas Tab: 1-tap pre-built automation templates
    │       ├── tasks.tsx              # 4. Tasks Tab: Scheduled goals & recurring routine manager
    │       └── settings.tsx           # 5. Settings Tab: Quota card, groups, and integrated sheets
    ├── components/                    # Core Shared UI Layout Components
    │   └── common/                    # Header, Mascot, Drawer, Customizer & Settings Modals
    │       ├── AppHeader.tsx          # 3-col header (Menu + Blue dot, 3D Mascot, 3-dots)
    │       ├── MascotAvatar.tsx       # 3D mascot avatar portrait component
    │       ├── SidebarDrawer.tsx      # Slide-in session history & search drawer
    │       ├── SettingsMenuModal.tsx  # 3-dots contextual action sheet dropdown
    │       ├── EditAgentModal.tsx     # Minimal agent name and theme color editor modal
    │       └── index.ts               # Common components barrel export
    ├── context/                       # Global state & providers
    │   └── ToastContext.tsx           # Lightweight toast notification system
    ├── constants/                     # Global constants & data models
    │   ├── colors.ts                  # Centralized color palette tokens
    │   ├── theme.ts                   # Typography and spacing scale constants
    │   └── dummyData.ts               # Initial chat messages, side chats, & mock datasets
    ├── lib/
    │   ├── env.ts                     # The three EXPO_PUBLIC_* variables and the API URL
    │   ├── supabase.ts                # Supabase client for sign-in only
    │   ├── formatSchedule.ts          # "Every Monday at 9:00 AM"
    │   └── api/                       # Backend API client: threads, chat stream, schedules, tools
    └── types/                         # Core TypeScript interfaces & contracts
        ├── index.ts                   # UI types, and the API-to-UI chat message mapper
        └── tools.ts                   # App connection types (re-exported from the API types)
```

---

## 🔍 Exhaustive File-by-File Guide

---

### 1. Root Configuration Files

#### [`package.json`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/package.json)
- **Role:** Declares project metadata, dependencies, and execution scripts.
- **Key Dependencies:**
  - `expo` (SDK 58): Core application platform.
  - `expo-router`: File-based navigation.
  - `@hugeicons/react-native` & `@hugeicons/core-free-icons`: Icon pack.
  - `@supabase/supabase-js`: Supabase Auth (Google sign-in and session persistence) only.
  - `expo/fetch`: Streams the chat reply (React Native's global `fetch` cannot).
  - `react-native-safe-area-context`: Notched device inset handling.
  - `react-native-svg`: Vector rendering support.
- **Scripts:**
  - `npm run start` / `expo start`: Launches Metro development server.
  - `npm run ios`: Launches iOS simulator.
  - `npm run android`: Launches Android emulator.
  - `npm run web`: Launches Web browser development instance.

#### [`app.json`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/app.json)
- **Role:** Expo manifest setting app name (`muse_ai_clone`), slug, scheme (`museaiclone`), splash screens, icons, and router plugins.

#### [`tsconfig.json`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/tsconfig.json)
- **Role:** TypeScript path mapping aliases (`@/*` -> `./src/*`).

---

### 2. Navigation & Screens (`src/app/`)

#### [`src/app/_layout.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/_layout.tsx)
- **Role:** Root application shell.
- **Wrappers:**
  - `ThemeProvider`: Synchronizes dark/light color scheme.
  - `ToastProvider`: Provides global toast overlays across all screens.
  - `Stack`: Headerless root navigation stack (`index`, `(tabs)`, `home`).
  - `StatusBar`: Dark status bar icons.

#### [`src/app/index.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/index.tsx)
- **Role:** Google Sign-in onboarding screen.
- **Features:** Hero glowing logo, brand title, and pressable "Sign in with Google" button with loading feedback. Upon sign-in, replaces route with `/(tabs)/chat`.

#### [`src/app/home.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/home.tsx)
- **Role:** Compatibility redirect route redirecting `/home` to `/(tabs)/chat`.

#### [`src/app/(tabs)/_layout.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/_layout.tsx)
- **Role:** Master Tab Layout for the 5 application routes.
- **Components & Configuration:**
  - **AppHeader:** Sticky top header with drawer trigger, Cooper mascot avatar, agent name capsule pill, and 3-dots action trigger.
  - **Expo Router `<Tabs>`:** Built-in bottom tab bar with `tabBarHideOnKeyboard: true`, custom active pill capsule backgrounds (`#E6E8EA`), and HugeIcons.
  - **Modals:** Integrates `SidebarDrawer`, `SettingsMenuModal`, and `EditAgentModal`.

#### [`src/app/(tabs)/index.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/index.tsx)
- **Role:** Tab root index that redirects automatically to `/chat`.

#### [`src/app/(tabs)/chat.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/chat.tsx)
- **Role:** Primary conversational interface with Cooper AI.
- **Features:**
  - Message thread with peach terracotta user bubbles (`#E8C4B4`) and soft gray agent bubbles (`#EEF0F2`).
  - Centered date badge ("Today").
  - Floating prompt bar with attachment button, text input, and voice/send action toggle.
  - Replies stream in token by token from the backend; the server stores both messages.
  - Composio Connect CTA rendering when the agent needs a missing connected tool.
  - Schedule proposal cards: Confirm creates the schedule on the backend, Cancel dismisses it.
  - Live browser preview while a Browserbase task runs.
  - **Keyboard Handling:** Uses dynamic `KeyboardAvoidingView` vertical offset (`insets.top + 98` on iOS), keyboard listeners to auto-scroll to the bottom when focusing, and `TouchableWithoutFeedback` to dismiss keyboard on background tap.

#### [`src/app/(tabs)/feed.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/feed.tsx)
- **Role:** Minimalist autonomous activity and notification feed screen.

#### [`src/app/(tabs)/ideas.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/ideas.tsx)
- **Role:** Inspiration library featuring pre-built automation cards (AI Builder Cup, App Leaderboard, Shorts Series, Launch Post). Tapping any card displays a selection toast.

#### [`src/app/(tabs)/tasks.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/tasks.tsx)
- **Role:** Autonomous goal manager.
- **Features:**
  - Schedules loaded from the backend (`GET /schedules`), with run counts and the latest result.
  - Active/Paused status toggles (`PATCH /schedules/{id}`).
  - Run now: starts a background run (`POST /schedules/{id}/runs`) and polls it until it finishes.
  - "+ New" goal creation trigger.

#### [`src/app/(tabs)/settings.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/%28tabs%29/settings.tsx)
- **Role:** Comprehensive account settings, plan limits, and connectors hub.
- **Features:**
  - Free Plan progress card (11% used, 890 remaining credits).
  - Tools & Connections navigation for Composio-backed app connections.
  - Pricing & billing plans sheet.
  - Notifications, theme appearance, help & feedback, and sign-out actions.

#### [`src/app/tools.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/app/tools.tsx)
- **Role:** Tools & Connections screen.
- **Features:** Lists the backend's app catalog with the user's status, starts Composio OAuth linking through the backend, polls pending connections, and supports manage, reconnect, and disconnect.

#### `src/lib/api/`
- **Role:** The only way the app reaches data. One module per area (`threads`, `chatStream`, `schedules`, `tools`, `me`) over `client.ts`, which attaches the Supabase access token and turns failures into a typed `ApiError`. See [BACKEND.md](./BACKEND.md) for the contract.

---

### 3. Common Layout & Navigation (`src/components/common/`)

#### [`src/components/common/AppHeader.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/AppHeader.tsx)
- **Role:** Persistent top navigation bar.
- **Sub-elements:**
  - Left: Circular button with 2-line menu icon and active blue notification dot.
  - Center: Cooper 3D mascot avatar portrait with interactive floating name pill.
  - Right: Circular button with horizontal 3-dots icon for the settings dropdown.

#### [`src/components/common/MascotAvatar.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/MascotAvatar.tsx)
- **Role:** Clean circular image component rendering `cooper_mascot.jpg` with a customizable `size` prop.

#### [`src/components/common/SidebarDrawer.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/SidebarDrawer.tsx)
- **Role:** Sliding modal drawer for conversation history.
- **Features:**
  - "Main chat" quick-return capsule button.
  - Filterable "Side chats" list with unread blue indicator dots.
  - Bottom toolbar with settings shortcut, search input field, and new chat compose button.

#### [`src/components/common/SettingsMenuModal.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/SettingsMenuModal.tsx)
- **Role:** Top-right 3-dots action sheet dropdown.
- **Actions:** Edit Mascot & Avatar, Rename Agent, Export Chat, Clear Messages, Delete Chat (Destructive).

#### [`src/components/common/EditAgentModal.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/EditAgentModal.tsx)
- **Role:** Minimalist agent customization card.
- **Controls:** Avatar preview, Agent Name input, 6 theme accent color dots (Muse Blue, Indigo, Emerald, Amber, Violet, Rose), and Cancel / Save action buttons.

#### [`src/components/common/index.ts`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/components/common/index.ts)
- **Role:** Barrel export for common components.

---

### 4. Global Context (`src/context/`)

#### [`src/context/ToastContext.tsx`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/context/ToastContext.tsx)
- **Role:** Application-wide toast notification system.
- **Exports:** `ToastProvider`, `useToast()`, and standalone trigger `showToast(message: string)`.

---

### 5. Constants & Mock Datasets (`src/constants/`)

#### [`src/constants/colors.ts`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/constants/colors.ts)
- **Role:** Central design tokens and color definitions.

#### [`src/constants/theme.ts`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/constants/theme.ts)
- **Role:** System typography mappings (`Fonts`) and 8-point spacing scales (`Spacing`).

#### [`src/constants/dummyData.ts`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/constants/dummyData.ts)
- **Role:** Seed datasets for `INITIAL_CHAT_MESSAGES`, `SIDE_CHATS`, `IDEA_ITEMS`, `TASK_GOALS`, `SETTINGS_PLAN_DATA`, and `SETTINGS_CONNECTORS`.

---

### 6. Data Types & Interfaces (`src/types/`)

#### [`src/types/index.ts`](file:///Users/rahulsanarahulp/Documents/Projects/React%20Native/muse_ai_clone/src/types/index.ts)
- **Role:** Core TypeScript contracts:
  - `ChatMessage`
  - `SideChatItem`
  - `IdeaItem`
  - `TaskGoalItem` & `TaskStatus`
  - `ConnectorItem`
  - `PlanData`
  - `AgentProfile`
  - `TabKey` & `TabItem`

---

## 🔄 Component Hierarchy & Data Flow

```mermaid
graph TD
  RootLayout["src/app/_layout.tsx (ThemeProvider & Stack)"]
  
  SignInScreen["src/app/index.tsx (Sign In)"]
  TabLayout["src/app/(tabs)/_layout.tsx (Tabs Layout)"]
  
  RootLayout -->|Route: /| SignInScreen
  RootLayout -->|Route: /(tabs)| TabLayout
  
  TabLayout --> AppHeader["components/common/AppHeader"]
  AppHeader --> MascotAvatar["components/common/MascotAvatar"]
  
  TabLayout --> SidebarDrawer["components/common/SidebarDrawer"]
  TabLayout --> SettingsMenuModal["components/common/SettingsMenuModal"]
  TabLayout --> EditAgentModal["components/common/EditAgentModal"]
  
  TabLayout --> ChatScreen["(tabs)/chat.tsx"]
  TabLayout --> FeedScreen["(tabs)/feed.tsx"]
  TabLayout --> IdeasScreen["(tabs)/ideas.tsx"]
  TabLayout --> TasksScreen["(tabs)/tasks.tsx"]
  TabLayout --> SettingsScreen["(tabs)/settings.tsx"]
```

---

## 🎨 Design System & Color Tokens

| Design Token | Hex / Value | Purpose |
|---|---|---|
| `Colors.primary` | `#2563EB` | Main brand blue |
| `Colors.primaryDark` | `#1D4ED8` | Pressed / hover active state |
| `Colors.chatBubbleUser` | `#E8C4B4` | Warm peach terracotta user bubble |
| `Colors.chatBubbleAi` | `#EEF0F2` | Soft light gray agent message bubble |
| `Colors.tabActiveBg` | `#E6E8EA` | Active tab pill capsule in dock |
| `Colors.iconDark` | `#1E2022` | Dark charcoal for typography and active icons |
| `Colors.iconMuted` | `#9E9E9E` | Secondary gray for subtitles & timestamps |
| `Colors.statusBlue` | `#0066FF` | Online indicator dot on header drawer button |
| `Colors.white` | `#FFFFFF` | Main background & floating capsules |

---

## ⚡ Commands & Developer Workflow

```bash
# Start Metro development server
npm run start

# Run on iOS simulator
npm run ios

# Run on Android emulator
npm run android

# Run in Web browser
npm run web

# TypeScript type check (Zero errors guarantee)
npx tsc --noEmit
```
