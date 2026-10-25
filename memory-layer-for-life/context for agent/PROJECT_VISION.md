# Project Vision

## Thesis

Build a personal AI-powered Second Brain that turns unstructured thoughts into organized, connected, actionable knowledge and helps the user remember what matters and follow through.

The user should be able to dump information without choosing a folder or data model. The system does the organizing work while preserving the original evidence and allowing correction.

## Product loop

**CAPTURE → UNDERSTAND → CONNECT → UPDATE STATE → PRIORITIZE → ACT → OBSERVE → LEARN**

- Capture: accept raw thoughts and information from low-friction inputs.
- Understand: extract candidate facts, intentions, entities, events, and relationships.
- Connect: resolve recurring people, projects, goals, concepts, and source evidence.
- Update state: maintain current interpretations without destroying history.
- Prioritize: surface relevant tasks, open loops, goals, and context.
- Act: help plan, follow up, search, schedule, or execute user-approved actions.
- Observe: record what actually happened, not merely what was planned.
- Learn: use corrections and outcomes to improve future usefulness.

## Product character

This is not a generic SaaS dashboard, Notion clone, CRM, or chat wrapper. It should feel like a personal operating system for someone's mind: calm, focused, high information quality, excellent capture and retrieval, and useful proactive behavior.

## Real-world data shape

The primary source material includes a WhatsApp self-chat/export with mixed unstructured content such as:
- Tasks, intentions, commitments, deadlines, and follow-ups.
- Project ideas and ongoing projects.
- Technical notes, learning topics, links, and code-related information.
- Personal preferences, reflections, plans, and observations.
- People and relationship context.
- Purchases, expenses, and other potentially transactional information.
- Events, schedules, and contextual references.
- Repeated concepts, incomplete thoughts, and ambiguous references.

This is a messy, realistic corpus. Do not design only around clean synthetic notes. Inspect the actual export and dataset files before making claims about their exact structure.

## Core principles

1. **Capture without classification friction.** Users should not have to decide where a thought belongs.
2. **Preserve evidence.** Original source content remains available and is not silently mutated.
3. **Separate evidence from interpretation.** A raw message, extracted claim, canonical memory, and current state are different things.
4. **Make memory explainable.** Every important memory should trace to supporting or contradicting sources.
5. **Preserve uncertainty.** Ambiguous identity, time, intention, and meaning must remain ambiguous until resolved.
6. **Temporal awareness.** Remember when something was said, when it was valid, and whether it is current.
7. **Correction is a first-class feature.** Users must be able to correct wrong extraction and entity links.
8. **Idempotent and replayable processing.** Improvements to models/prompts must not corrupt history or create duplicates.
9. **Proactive, not intrusive.** Notifications should be contextual, valuable, and controllable.
10. **Action requires grounding and permission.** Suggestions and external actions are not the same; consequential actions need explicit authorization.
11. **Avoid fake certainty.** Never infer task completion merely from silence or an old intention.
12. **Start simple, preserve extensibility.** A modular monolith and PostgreSQL-first architecture are preferred until evidence demands more.

## Memory taxonomy

The system may need to represent:
- Episodic memory: events and experiences.
- Semantic memory: facts and knowledge.
- Working memory/context: currently relevant, temporary state, often derived.
- Procedural memory: how to do things.
- Preferences: likes, habits, constraints.
- Goals and aspirations.
- Projects.
- Tasks and commitments.
- Social/people memory and relationships.
- Decisions, rationales, alternatives.
- Ideas and hypotheses.
- Contextual memory: time, location, situation.
- Financial/transactional memory.
- Knowledge artifacts: links, documents, code, files, media.
- Open loops: unresolved questions, follow-ups, waiting items.

Not every type needs a dedicated table immediately. A common memory record can carry type and provenance; operationally complex domains (tasks, goals, transactions, notifications) should gain dedicated domain tables when their lifecycle warrants it. Working memory and life state may be derived views/projections rather than permanent facts.

## Main product capabilities (long-term vision)

- Universal dump/capture.
- Inbox and review queue.
- Source-preserving extraction.
- Entity resolution and cross-message linking.
- Structured memory browser.
- Hybrid search across exact terms and semantic meaning.
- Related memories and backlinks.
- Project, goal, task, and open-loop tracking.
- Temporal timeline and historical state.
- Current life-state summary.
- Daily brief and contextual reminders.
- Planner and accountability workflows.
- Proactive insights and pattern detection.
- People/relationship context.
- Knowledge artifact and document retrieval.
- User feedback/correction loop.
- Future integrations (e.g. messaging, calendar, email, files, browser) only as needed.

## Product UX principles

- Persistent, prominent “Dump anything…” composer.
- Home answers: “What is on my mind?”, “What needs attention?”, “What should I continue?”
- Use meaningful lists and information hierarchy rather than a wall of cards.
- Display source, time, processing status, and confidence/uncertainty where relevant.
- Allow inspect/edit/accept/reject/retry actions on extracted information.
- Show why a memory or recommendation is being surfaced.
- Search results should show snippets and source context.
- Keyboard navigation and responsive mobile capture are important.
- Avoid generic AI gradients, excessive cards, decorative charts, and meaningless metrics.

## Success criteria

The product should reliably preserve incoming information, produce grounded structured memories, retrieve useful past context, make open loops visible, and help the user take better next actions without inventing facts or overwhelming them.
