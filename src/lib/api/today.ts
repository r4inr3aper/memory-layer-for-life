/**
 * Today API: the Feed's cards (next actions, promises, meetings, something to pick up
 * again, memories to confirm), computed by the backend from the user's own records.
 */

import { apiRequest } from '@/lib/api/client';
import type { TodayCards } from '@/lib/api/types';

export function getToday(signal?: AbortSignal): Promise<TodayCards> {
  return apiRequest<TodayCards>('/me/today', { signal });
}
