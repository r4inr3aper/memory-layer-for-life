/**
 * Threads & Messages API
 */

import { apiRequest } from "@/lib/api/client";
import type {
    ChatMessage,
    ConfirmProposalResult,
    CreateThreadBody,
    Page,
    PageParams,
    Thread,
    ThreadKind,
} from "@/lib/api/types";

/** Threads with the most recent activity first. */
export function listThreads(
  params: PageParams & { kind?: ThreadKind } = {},
  signal?: AbortSignal,
): Promise<Page<Thread>> {
  return apiRequest<Page<Thread>>("/threads", { query: { ...params }, signal });
}

/** Starts a side thread. Without a title, the server names it from the first message. */
export function createSideThread(title?: string): Promise<Thread> {
  const body: CreateThreadBody = title ? { title } : {};
  return apiRequest<Thread>("/threads", { method: "POST", body });
}

/** The user's main thread, created on first use. Idempotent. */
export function ensureMainThread(signal?: AbortSignal): Promise<Thread> {
  return apiRequest<Thread>("/threads/main", { method: "POST", signal });
}

export function getThread(
  threadId: string,
  signal?: AbortSignal,
): Promise<Thread> {
  return apiRequest<Thread>(threadPath(threadId), { signal });
}

/** Deletes every message of a thread and keeps the thread. 409 while a reply runs. */
export function clearMessages(threadId: string): Promise<void> {
  return apiRequest<void>(`${threadPath(threadId)}/messages`, {
    method: "DELETE",
  });
}

/** Deletes a side thread and its messages. The main thread cannot be deleted (409). */
export function deleteThread(threadId: string): Promise<void> {
  return apiRequest<void>(threadPath(threadId), { method: "DELETE" });
}

/** The most recent `limit` messages of a thread, oldest first. */
export function listMessages(
  threadId: string,
  params: PageParams = {},
  signal?: AbortSignal,
): Promise<Page<ChatMessage>> {
  return apiRequest<Page<ChatMessage>>(`${threadPath(threadId)}/messages`, {
    query: { ...params },
    signal,
  });
}

/** Creates the schedule a message proposed and marks the proposal confirmed. */
export function confirmProposal(
  threadId: string,
  messageId: string,
): Promise<ConfirmProposalResult> {
  return apiRequest<ConfirmProposalResult>(
    `${proposalPath(threadId, messageId)}/confirm`,
    {
      method: "POST",
    },
  );
}

/** Marks a message's schedule proposal dismissed and returns the updated message. */
export function dismissProposal(
  threadId: string,
  messageId: string,
): Promise<ChatMessage> {
  return apiRequest<ChatMessage>(
    `${proposalPath(threadId, messageId)}/dismiss`,
    {
      method: "POST",
    },
  );
}

/** Sends a prepared job application email draft and returns the updated message card. */
export function sendJobApplicationDraft(
  threadId: string,
  messageId: string,
): Promise<ChatMessage> {
  return apiRequest<ChatMessage>(`${jobDraftPath(threadId, messageId)}/send`, {
    method: "POST",
  });
}

export function threadPath(threadId: string): string {
  return `/threads/${encodeURIComponent(threadId)}`;
}

function proposalPath(threadId: string, messageId: string): string {
  return `${threadPath(threadId)}/messages/${encodeURIComponent(messageId)}/proposal`;
}

function jobDraftPath(threadId: string, messageId: string): string {
  return `${threadPath(threadId)}/messages/${encodeURIComponent(messageId)}/job-application`;
}
