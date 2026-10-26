/**
 * Memory Display Helpers
 *
 * Labels, grouping, and wording for the user's memories, their history, and the review
 * inbox. Everything here is pure, so screens stay thin and the wording is tested.
 */

import type {
  HeldBack,
  MemoryEvent,
  MemoryItem,
  MemoryStatus,
  SuggestionKind,
} from '@/lib/api/types';

const MEMORY_TYPE_LABELS: Record<string, string> = {
  semantic_fact: 'Fact',
  episodic_event: 'Event',
  preference: 'Preference',
  intention: 'Intention',
  task: 'Task',
  commitment: 'Commitment',
  goal: 'Goal',
  project: 'Project',
  decision: 'Decision',
  idea: 'Idea',
  open_loop: 'Open loop',
  plan: 'Plan',
  note: 'Note',
  reflection: 'Reflection',
  resource: 'Resource',
  financial_note: 'Money',
};

/** The kinds offered when writing or editing a memory, most useful first. */
export const MEMORY_TYPE_CHOICES = [
  'note',
  'semantic_fact',
  'preference',
  'goal',
  'task',
  'plan',
  'idea',
  'episodic_event',
  'reflection',
  'financial_note',
] as const;

/** The backend's limit on a memory's text. */
export const MEMORY_CONTENT_MAX_LENGTH = 2000;

/** "Fact" for semantic_fact; a readable fallback for a type added later. */
export function memoryTypeLabel(memoryType: string): string {
  const known = MEMORY_TYPE_LABELS[memoryType];
  if (known) {
    return known;
  }
  const words = memoryType.split('_').filter(Boolean).join(' ');
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Memory';
}

const STATUS_LABELS: Record<MemoryStatus, string> = {
  proposed: 'To review',
  active: 'Accepted',
  superseded: 'Replaced',
  retracted: 'Marked wrong',
};

export function memoryStatusLabel(status: MemoryStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export interface MemorySection {
  title: string;
  data: MemoryItem[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Which section a moment belongs to, relative to `now`, in the phone's timezone. */
export function timelineTitle(isoTime: string, now: Date = new Date()): string {
  const moment = new Date(isoTime);
  const days = Math.round((startOfDay(now) - startOfDay(moment)) / DAY_MS);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'This week';
  return moment.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

/**
 * Memories (newest saved first) in sections: Today, Yesterday, This week, then one per
 * month. A memory goes where it was saved, so pages loaded later extend the last section
 * instead of reshuffling earlier ones.
 */
export function groupMemoriesByTime(
  memories: readonly MemoryItem[],
  now: Date = new Date()
): MemorySection[] {
  const sections: MemorySection[] = [];
  for (const memory of memories) {
    const title = timelineTitle(memory.created_at, now);
    const last = sections[sections.length - 1];
    if (last && last.title === title) {
      last.data.push(memory);
    } else {
      sections.push({ title, data: [memory] });
    }
  }
  return sections;
}

function quoted(value: unknown): string {
  return typeof value === 'string' ? `"${value}"` : 'another memory';
}

/** One line of a memory's history, as the user reads it. */
export function historyText(event: MemoryEvent): string {
  const details = event.details;
  switch (event.action) {
    case 'created':
      return details.processing_run_id
        ? 'You saved it from a message Cooper held back'
        : 'You wrote it';
    case 'accepted':
      // The pipeline accepts what it is sure of: confident, not sensitive, your own words.
      return details.by === 'pipeline' ? 'Saved on its own: Cooper was sure' : 'You accepted it';
    case 'retracted':
      return 'You marked it as wrong';
    case 'restored':
      return 'You restored it';
    case 'edited': {
      const changes = (details.changes ?? {}) as Record<string, { to?: unknown }>;
      const parts: string[] = [];
      if (changes.memory_type && typeof changes.memory_type.to === 'string') {
        parts.push(`Kind changed to ${memoryTypeLabel(changes.memory_type.to)}`);
      }
      if (changes.sensitive) {
        parts.push(changes.sensitive.to ? 'Marked sensitive' : 'No longer marked sensitive');
      }
      return parts.length ? parts.join(' · ') : 'You edited it';
    }
    case 'corrected':
      return `You corrected it. It said: ${quoted(details.previous_content)}`;
    case 'superseded':
      if (details.reason === 'corrected') return 'Replaced by your corrected version';
      if (details.reason === 'merged') return 'Merged into another memory';
      return 'Replaced by a newer memory';
    case 'merged':
      return `Merged with ${quoted(details.content)}`;
    case 'replaced':
      return `Replaced ${quoted(details.content)}`;
    case 'suggestion_dismissed':
      return 'You kept it apart from a similar memory';
    case 'mentioned_again':
      return `You said it again: ${quoted(details.content)}`;
    default:
      return 'Changed';
  }
}

export function suggestionText(kind: SuggestionKind): string {
  return kind === 'duplicate'
    ? 'These look like the same memory.'
    : 'These are about the same thing and may not both be true.';
}

export function heldBackReasonText(reason: HeldBack['reason']): string {
  return reason === 'unclear'
    ? "Cooper wasn't sure there was anything to remember here."
    : "Cooper couldn't read this one reliably.";
}

/** What to prefill when saving a held-back message as a memory: its text, trimmed. */
export function heldBackDraft(heldBack: HeldBack): string {
  return heldBack.messages
    .map((message) => message.content.trim())
    .filter(Boolean)
    .join(' ')
    .slice(0, MEMORY_CONTENT_MAX_LENGTH);
}

/** The editor's problem with a memory's text, or null when it can be saved. */
export function validateMemoryContent(content: string): string | null {
  const text = content.trim();
  if (!text) return 'Write what Cooper should remember.';
  if (text.length > MEMORY_CONTENT_MAX_LENGTH) {
    return `Keep it under ${MEMORY_CONTENT_MAX_LENGTH} characters.`;
  }
  return null;
}
