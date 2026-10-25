/**
 * Insights API: what the user's memories show over time, and feedback on it.
 */

import { apiRequest } from '@/lib/api/client';
import type { Insight, InsightKind } from '@/lib/api/types';

/** Strongest first; those marked not useful are left out for their period. */
export async function listInsights(signal?: AbortSignal): Promise<Insight[]> {
  const result = await apiRequest<{ items: Insight[] }>('/me/insights', { signal });
  return result.items;
}

/** A later answer replaces an earlier one; not useful hides the insight for its period. */
export function sendInsightFeedback(
  key: string,
  kind: InsightKind,
  useful: boolean
): Promise<void> {
  return apiRequest<void>('/me/insights/feedback', {
    method: 'POST',
    body: { key, kind, useful },
  });
}
