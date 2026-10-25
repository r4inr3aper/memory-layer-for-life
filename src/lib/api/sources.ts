/**
 * Memory Sources API: WhatsApp chat imports, photos and PDFs, and connected apps (Google
 * Calendar) whose items become memories.
 */

import { apiRequest } from '@/lib/api/client';
import type { ChatImport, FileMemoryResult, SourceApp, StartImportBody } from '@/lib/api/types';

/** Reads an export (.txt or .zip, base64) and returns what importing it would mean. */
export function previewImport(fileName: string, dataBase64: string): Promise<ChatImport> {
  return apiRequest<ChatImport>('/me/imports/whatsapp', {
    method: 'POST',
    body: { file_name: fileName, data_base64: dataBase64 },
  });
}

/** Queues the chat's conversations for the memory pipeline: one extraction each. */
export function startImport(importId: string, body: StartImportBody): Promise<ChatImport> {
  return apiRequest<ChatImport>(`/me/imports/${encodeURIComponent(importId)}/start`, {
    method: 'POST',
    body,
  });
}

export function listImports(signal?: AbortSignal): Promise<ChatImport[]> {
  return apiRequest<ChatImport[]>('/me/imports', { signal });
}

export function getImport(importId: string, signal?: AbortSignal): Promise<ChatImport> {
  return apiRequest<ChatImport>(`/me/imports/${encodeURIComponent(importId)}`, { signal });
}

/** Reads a photo or PDF (one of today's prompts); memories follow in the background. */
export function memoryFromFile(
  fileName: string,
  mediaType: string,
  dataBase64: string
): Promise<FileMemoryResult> {
  return apiRequest<FileMemoryResult>('/me/memories/from-file', {
    method: 'POST',
    body: { file_name: fileName, media_type: mediaType, data_base64: dataBase64 },
  });
}

export function listSources(signal?: AbortSignal): Promise<SourceApp[]> {
  return apiRequest<SourceApp[]>('/me/sources', { signal });
}

/** Turning a source on syncs it at once; a failure comes back as an `ApiError`. */
export function setSourceEnabled(app: string, enabled: boolean): Promise<SourceApp> {
  return apiRequest<SourceApp>(`/me/sources/${encodeURIComponent(app)}`, {
    method: 'PATCH',
    body: { enabled },
  });
}

export function syncSource(app: string): Promise<SourceApp> {
  return apiRequest<SourceApp>(`/me/sources/${encodeURIComponent(app)}/sync`, {
    method: 'POST',
  });
}
