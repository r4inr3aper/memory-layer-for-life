# Product UX and Information Architecture

## Design direction

Premium, focused, editorial, dark-first UI. The product should feel like a personal operating system, not a generic SaaS dashboard, Notion clone, or ChatGPT wrapper.

Use typography, spacing, hierarchy, subtle borders, restraint, and useful density. Avoid overuse of gradients/glows, glassmorphism, giant cards, meaningless charts, decorative widgets, and repetitive rounded containers.

## Core shell

Sidebar:
- Home
- Inbox
- Tasks
- Projects
- Goals
- Ideas
- Knowledge
- People
- Timeline
- Insights

Also include quick capture, global search, command palette, settings, and profile/context controls as appropriate.

Mobile must prioritize capture, search, today's priorities, and navigation; do not simply shrink the desktop sidebar.

## Home

Home should answer:
1. What is on my mind?
2. What needs attention?
3. What should I continue?

Potential sections:
- Persistent “Dump anything…” composer.
- Today’s priorities.
- Open loops: unfinished tasks, follow-ups, unresolved decisions, waiting items.
- Continue where you left off: active projects/learning.
- Recently captured feed with processing state.
- Memory resurfacing with explanation of relevance.

Use lists, dividers, and selective panels rather than every item becoming a large card.

## Inbox

- Original text and capture timestamp.
- Processing status.
- Suggested type/entities/tasks when available.
- Accept, edit, reject/dismiss, defer, retry actions.
- Inspect source before changing derived data.
- Filters: all, unprocessed, needs review, processed.
- Make uncertainty visible.

## Tasks

List-first view with status, priority, due date, project, and filters for today/upcoming/overdue/completed. Completion/rescheduling must be functional. Distinguish explicit deadlines from suggestions.

## Projects and goals

Project overview: status, goal, next action, recent activity, linked notes, blockers/staleness. Goals: outcomes, milestones, related projects, and defensible progress. Do not invent completion percentages.

## Ideas, knowledge, people, timeline

- Ideas: searchable, linked to source notes, concepts, and status.
- Knowledge: searchable notes/memories with provenance, related concepts, backlinks.
- People: lightweight context, interaction history, things to remember, follow-ups; not a sales CRM.
- Timeline: captured thoughts, events, decisions, project changes, and completed actions chronologically.

## AI interaction

AI should be contextual and subordinate to the user's work. Useful actions include summarize, extract tasks, find related memories, explain connection, suggest next actions, and show source. Distinguish retrieved evidence from generated suggestions. Never fake successful processing if no backend integration exists.

## Interaction quality

- All visible controls work.
- Useful loading, empty, error, success, and review states.
- Search and filters update results.
- Keyboard shortcuts and focus states.
- Accessible contrast and labels.
- Responsive desktop/tablet/mobile.
- Reusable components and consistent design tokens.
- Realistic, interconnected seed data if backend is unavailable.
- UI must communicate true integration status.

## UI implementation strategy

Build in dependency order:
1. Shell/design system.
2. Home + capture.
3. Inbox + review.
4. Tasks/projects/goals/ideas.
5. Knowledge/people/timeline/search.
6. Responsive/accessibility polish.
7. End-to-end audit.

Prioritize exceptional capture → inbox behavior over superficial implementations of every screen.
