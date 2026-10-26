/**
 * Links API: links the user saves for Cooper to share for them, such as their resume on
 * Google Drive or their portfolio. Cooper puts them in emails by address; nothing is
 * fetched from them.
 */

import { apiRequest } from '@/lib/api/client';
import type { LinkKind, SavedLink, SavedLinkResult, SaveLinkBody } from '@/lib/api/types';

/** The resume link first, then the most recently changed. */
export function listLinks(signal?: AbortSignal): Promise<SavedLink[]> {
  return apiRequest<SavedLink[]>('/me/links', { signal });
}

/** Saves a link; the same address again updates the saved one. */
export function saveLink(body: SaveLinkBody): Promise<SavedLinkResult> {
  return apiRequest<SavedLinkResult>('/me/links', { method: 'POST', body });
}

/** Marking a link as the resume makes the previous resume link a plain link. */
export function updateLink(
  linkId: string,
  changes: { url?: string; title?: string; kind?: LinkKind }
): Promise<SavedLink> {
  return apiRequest<SavedLink>(`/me/links/${encodeURIComponent(linkId)}`, {
    method: 'PATCH',
    body: changes,
  });
}

export function deleteLink(linkId: string): Promise<void> {
  return apiRequest<void>(`/me/links/${encodeURIComponent(linkId)}`, { method: 'DELETE' });
}
