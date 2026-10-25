/**
 * Activity API: what the assistant did on its own (finished scheduled runs).
 */

import { apiRequest } from '@/lib/api/client';
import type { ActivityItem, Page, PageParams } from '@/lib/api/types';

/** Finished scheduled runs, newest first. */
export function listActivity(
  params: PageParams = {},
  signal?: AbortSignal
): Promise<Page<ActivityItem>> {
  return apiRequest<Page<ActivityItem>>('/activity', { query: { ...params }, signal });
}
