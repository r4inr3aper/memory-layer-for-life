/**
 * How the app describes the user's files and links (Files & links).
 */

import type { LinkKind, SavedLink, UserDocument } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';

/** The kind of file, as a short word. */
export function documentKind(mediaType: string): string {
  if (mediaType === 'application/pdf') return 'PDF';
  if (mediaType.includes('wordprocessingml')) return 'Word';
  if (mediaType === 'text/markdown') return 'Markdown';
  return 'Text';
}

/** A size as people read it: "820 KB", "1.4 MB". */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One line under a document's title: its kind, length, and when it was added. */
export function documentMeta(document: UserDocument, now: Date = new Date()): string {
  const parts = [documentKind(document.media_type)];
  if (document.page_count) {
    parts.push(`${document.page_count} ${document.page_count === 1 ? 'page' : 'pages'}`);
  }
  if (document.extraction === 'vision') {
    parts.push('scanned');
  }
  const added = formatRelativeTime(document.created_at, now);
  if (added) {
    parts.push(`added ${added}`);
  }
  return parts.join(' · ');
}

// --- Links ---------------------------------------------------------------------------

export const LINK_KINDS: readonly { kind: LinkKind; label: string }[] = [
  { kind: 'resume', label: 'Resume' },
  { kind: 'portfolio', label: 'Portfolio' },
  { kind: 'linkedin', label: 'LinkedIn' },
  { kind: 'github', label: 'GitHub' },
  { kind: 'website', label: 'Website' },
  { kind: 'other', label: 'Other' },
];

export function linkKindLabel(kind: LinkKind): string {
  return LINK_KINDS.find((item) => item.kind === kind)?.label ?? 'Link';
}

/** A link's address without the scheme and a trailing slash, as people read it. */
export function displayUrl(link: Pick<SavedLink, 'url'>): string {
  return link.url.replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/\/$/, '');
}
