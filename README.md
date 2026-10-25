<img width="1672" height="941" alt="Zoop App Tutorial" src="https://github.com/user-attachments/assets/79585d78-3fc4-4673-936e-cd7c14fa04dc" />

# 🤖 Zoop

A pixel-perfect, universal React Native application for **Zoop** and companion **Cooper** — an autonomous AI agent for recurring tasks, workflows, and goals.

Built with **Expo (SDK 58)**, **React Native 0.88**, **Expo Router**, and **TypeScript**.

---

## ✨ Features

- **Google Sign-In Authentication:** Beautiful onboarding screen with official 4-color SVG Google sign-in button.
- **Header & 3D Character Mascot:** Sticky top header featuring Cooper's 3D portrait, floating name pill, 2-line menu with unread indicator dot, and 3-dots action sheet.
- **AI Chat With Connected Tools:** Cooper (Claude, on the backend) streams replies token by token, can run Browserbase browser tasks you watch live, and uses your connected Composio apps. History is stored on the server.
- **Stadium Floating Dock:** Bottom capsule dock switching between **Chat**, **Feed**, **Ideas**, **Tasks**, and **Settings**.
- **Slide-in Session Drawer:** Main chat shortcut, searchable side chat history with unread indicators, and bottom compose toolbar.
- **Agent Personalization Modal:** Live preview editor for agent name, role subtitle, 5 emblem icons, and 6 aura theme colors.
- **Autonomous Tasks & Goals:** Cooper proposes a schedule in chat; once you confirm it, the backend runs it on time (in your timezone) and posts the result to chat or delivers it to Slack, email, and more. Run any schedule on demand.
- **Settings & Connectors:** Connect, check, reconnect, and disconnect Composio-backed apps such as Gmail, Slack, and Google Calendar.

---

## 📚 Complete Codebase Documentation

**Start here:** [`docs/PROJECT_GUIDE.md`](./docs/PROJECT_GUIDE.md): how to run the app and backend, where the code is, what is implemented, and what is left.

For an exhaustive, file-by-file breakdown explaining the architecture, dependencies, data flow, and documented code snippets for every file, see:

👉 [**`docs/CODEBASE_EXPLANATION.md`**](./docs/CODEBASE_EXPLANATION.md)

How the app talks to its backend (environment, API, reply stream, schedules, connections):

👉 [**`docs/BACKEND.md`**](./docs/BACKEND.md)

The backend itself, a FastAPI service in [`memory-layer-for-life/`](./memory-layer-for-life/README.md), has its own setup guide: [`RUN_LOCALLY.md`](./memory-layer-for-life/RUN_LOCALLY.md).

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure and start the backend

The app needs the backend running. Follow [`memory-layer-for-life/RUN_LOCALLY.md`](./memory-layer-for-life/RUN_LOCALLY.md), section "Serve the mobile app". The data lives in the backend's PostgreSQL (Neon); Supabase is used for sign-in only.

The app's own `.env` has only public values:

```bash
EXPO_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
# Optional: defaults to this computer on port 8000 in development
# EXPO_PUBLIC_API_URL=http://192.168.1.20:8000
```

### 3. Run the Development Server

```bash
# Start Expo Metro bundler
npm run start

# Run on iOS simulator
npm run ios

# Run on Android emulator
npm run android

# Run in Web browser
npm run web
```

### 4. Type Checking

```bash
npx tsc --noEmit
```

---

## 🛠️ Tech Stack

- **Framework:** [Expo](https://docs.expo.dev/) (SDK 58)
- **Runtime:** React Native 0.88.0 / React 19.3.0
- **Router:** [Expo Router](https://docs.expo.dev/router/introduction/) (File-based in `src/app/`)
- **Icons:** `@hugeicons/react-native` & `@hugeicons/core-free-icons`
- **Vectors:** `react-native-svg`
- **Safe Area:** `react-native-safe-area-context`
- **Auth:** Supabase Auth (Google sign-in only)
- **Backend:** FastAPI + PostgreSQL + Claude in [`memory-layer-for-life/`](./memory-layer-for-life/)
