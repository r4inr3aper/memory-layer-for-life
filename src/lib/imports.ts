/**
 * Chat Import Helpers
 *
 * How many conversations an import will extract with the user's choices, what that costs,
 * and the "from when" choices. Pure, so the numbers shown before starting are tested.
 */

import type { ChatImport } from '@/lib/api/types';
import { addDays } from '@/lib/life';
import { formatCost } from '@/lib/usageChart';

export const MAX_IMPORT_CONVERSATIONS = 300;
export const DEFAULT_IMPORT_CONVERSATIONS = 200;

export interface SinceChoice {
  label: string;
  /** YYYY-MM-DD, or null for everything. */
  value: string | null;
}

export function sinceChoices(today: string): SinceChoice[] {
  return [
    { label: 'Everything', value: null },
    { label: 'Last year', value: addDays(today, -365) },
    { label: 'Last 3 months', value: addDays(today, -91) },
    { label: 'Last month', value: addDays(today, -30) },
  ];
}

/**
 * The conversations an import would take, before the date filter (which the server
 * applies): those the chosen person took part in, or all of them, capped.
 */
export function plannedConversations(
  chatImport: ChatImport,
  me: string | null,
  onlyMine: boolean,
  cap: number = DEFAULT_IMPORT_CONVERSATIONS
): number {
  const person = chatImport.participants.find((participant) => participant.name === me);
  const available = onlyMine ? (person?.conversations ?? 0) : chatImport.all_conversations;
  return Math.min(available, cap);
}

/** "Up to 120 extractions, about ₹4.80", or without the price when it is unknown. */
export function importEstimate(chatImport: ChatImport, conversations: number): string {
  const count = `Up to ${conversations} ${conversations === 1 ? 'extraction' : 'extractions'}`;
  if (chatImport.cost_per_conversation === null) return count;
  const total = Number(chatImport.cost_per_conversation) * conversations;
  return `${count}, about ${formatCost(total, chatImport.currency)}`;
}

/** "45 of 120 done, 3 memories so far" while the pipeline works. */
export function importProgressText(chatImport: ChatImport): string {
  const progress = chatImport.progress;
  if (!progress) return 'Not started';
  const total = progress.done + progress.failed + progress.waiting;
  const memories = `${progress.memories} ${progress.memories === 1 ? 'memory' : 'memories'}`;
  if (progress.waiting === 0) {
    return progress.failed
      ? `Finished: ${memories}; ${progress.failed} could not be read`
      : `Finished: ${memories}`;
  }
  return `${progress.done} of ${total} done, ${memories} so far`;
}
