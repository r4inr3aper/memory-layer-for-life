/**
 * Schedules API
 */

import { apiRequest } from '@/lib/api/client';
import type {
  CreateScheduleBody,
  Page,
  PageParams,
  Schedule,
  ScheduleRun,
  ScheduleStatus,
  UpdateScheduleBody,
} from '@/lib/api/types';

const RUN_POLL_INTERVAL_MS = 2000;
const RUN_POLL_TIMEOUT_MS = 5 * 60 * 1000;

/** Schedules, newest first, each with its run count and latest result. */
export function listSchedules(
  params: PageParams = {},
  signal?: AbortSignal
): Promise<Page<Schedule>> {
  return apiRequest<Page<Schedule>>('/schedules', { query: { ...params }, signal });
}

/** Creates a schedule from the user's own form. Chat results go to the main thread. */
export function createSchedule(body: CreateScheduleBody): Promise<Schedule> {
  return apiRequest<Schedule>('/schedules', { method: 'POST', body });
}

export function getSchedule(scheduleId: string, signal?: AbortSignal): Promise<Schedule> {
  return apiRequest<Schedule>(schedulePath(scheduleId), { signal });
}

/** Edits a schedule; only the fields sent change. A cancelled schedule cannot be edited. */
export function updateSchedule(scheduleId: string, body: UpdateScheduleBody): Promise<Schedule> {
  return apiRequest<Schedule>(schedulePath(scheduleId), { method: 'PATCH', body });
}

/** Pauses, resumes, or cancels a schedule. Cancelling is final. */
export function updateScheduleStatus(
  scheduleId: string,
  status: ScheduleStatus
): Promise<Schedule> {
  return updateSchedule(scheduleId, { status });
}

/** Deletes a schedule and its run history. 409 while a run is in progress. */
export function deleteSchedule(scheduleId: string): Promise<void> {
  return apiRequest<void>(schedulePath(scheduleId), { method: 'DELETE' });
}

/** A schedule's runs, newest first, including skipped slots. */
export function listScheduleRuns(
  scheduleId: string,
  params: PageParams = {},
  signal?: AbortSignal
): Promise<Page<ScheduleRun>> {
  return apiRequest<Page<ScheduleRun>>(`${schedulePath(scheduleId)}/runs`, {
    query: { ...params },
    signal,
  });
}

/** Starts a run now, in the background. 409 when the schedule is already running. */
export function startScheduleRun(scheduleId: string): Promise<ScheduleRun> {
  return apiRequest<ScheduleRun>(`${schedulePath(scheduleId)}/runs`, { method: 'POST' });
}

export function getScheduleRun(
  scheduleId: string,
  runId: string,
  signal?: AbortSignal
): Promise<ScheduleRun> {
  return apiRequest<ScheduleRun>(`${schedulePath(scheduleId)}/runs/${encodeURIComponent(runId)}`, {
    signal,
  });
}

/**
 * Polls a run until it is no longer `running`. Resolves with the finished run, or with
 * the last one seen (still `running`) once `timeoutMs` has passed.
 */
export async function waitForScheduleRun(
  scheduleId: string,
  run: ScheduleRun,
  options: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {}
): Promise<ScheduleRun> {
  const { intervalMs = RUN_POLL_INTERVAL_MS, timeoutMs = RUN_POLL_TIMEOUT_MS, signal } = options;
  const deadline = Date.now() + timeoutMs;
  let latest = run;

  while (latest.status === 'running' && Date.now() < deadline) {
    await delay(intervalMs, signal);
    latest = await getScheduleRun(scheduleId, latest.id, signal);
  }

  return latest;
}

function schedulePath(scheduleId: string): string {
  return `/schedules/${encodeURIComponent(scheduleId)}`;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abortError = () => Object.assign(new Error('Aborted'), { name: 'AbortError' });

    if (signal?.aborted) {
      reject(abortError());
      return;
    }

    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}
