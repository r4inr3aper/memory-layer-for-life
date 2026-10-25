/**
 * Signed-in User API: profile, assistant personalization, usage, notifications,
 * feedback, data export, and account deletion. Memories are in `memories.ts`.
 */

import { apiRequest } from '@/lib/api/client';
import type {
  AccountDeletion,
  FeedbackBody,
  FeedbackResult,
  Me,
  RegisterPushTokenBody,
  UpdateMeBody,
  Usage,
  UsageGranularity,
  UsageHistory,
} from '@/lib/api/types';

/** The signed-in user. The backend creates the user record on its first request. */
export function getMe(signal?: AbortSignal): Promise<Me> {
  return apiRequest<Me>('/me', { signal });
}

/** Saves assistant personalization or the notification setting. Only sent fields change. */
export function updateMe(body: UpdateMeBody): Promise<Me> {
  return apiRequest<Me>('/me', { method: 'PATCH', body });
}

/** Today's usage against the daily prompt limit. */
export function getUsage(signal?: AbortSignal): Promise<Usage> {
  return apiRequest<Usage>('/me/usage', { signal });
}

/** Prompts and estimated cost per day, week, or month, for the usage chart. */
export function getUsageHistory(
  granularity: UsageGranularity,
  signal?: AbortSignal
): Promise<UsageHistory> {
  return apiRequest<UsageHistory>('/me/usage/history', { query: { granularity }, signal });
}

/**
 * Everything the backend holds for the user, as one document: account, memories with
 * their evidence and history, people, chats, schedules, connected apps, and usage.
 */
export function getMyExport(signal?: AbortSignal): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>('/me/export', { signal });
}

/** Registers this device's Expo push token. Idempotent. */
export function registerPushToken(body: RegisterPushTokenBody): Promise<void> {
  return apiRequest<void>('/me/push-tokens', { method: 'POST', body });
}

/** Stops push notifications to this device. */
export function unregisterPushToken(token: string, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/me/push-tokens/${encodeURIComponent(token)}`, {
    method: 'DELETE',
    signal,
  });
}

export function sendFeedback(body: FeedbackBody): Promise<FeedbackResult> {
  return apiRequest<FeedbackResult>('/feedback', { method: 'POST', body });
}

/**
 * Deletes the account: revokes connected apps, deletes all data, and deletes the
 * Supabase sign-in when the backend is configured to. Cannot be undone.
 */
export function deleteAccount(): Promise<AccountDeletion> {
  return apiRequest<AccountDeletion>('/me', { method: 'DELETE' });
}
