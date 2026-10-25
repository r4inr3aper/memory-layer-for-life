/**
 * Chat Attachment Rules
 *
 * The backend accepts up to 3 files of at most 5 MB each, as JPEG, PNG, GIF, WebP, or PDF.
 * Checking here first gives a clear message instead of a refused message.
 */

import type { AttachmentMediaType } from '@/lib/api/types';

export const MAX_ATTACHMENTS = 3;
export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

export const ALLOWED_ATTACHMENT_TYPES: readonly AttachmentMediaType[] = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/pdf',
];

const TYPE_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  gif: 'image/gif',
  webp: 'image/webp',
  pdf: 'application/pdf',
  heic: 'image/heic',
  heif: 'image/heif',
};

/** What the picker reports about a file. */
export interface PickedFileInfo {
  name: string;
  /** Bytes; unknown on some platforms until the file is read. */
  size?: number | null;
  mimeType?: string | null;
}

export type AttachmentCheck =
  | { ok: true; mediaType: AttachmentMediaType }
  | { ok: false; reason: string };

/**
 * The file's media type in the form the backend expects: lowercase, `image/jpg` as
 * `image/jpeg`, and taken from the extension when the picker reports none.
 */
export function normalizeMediaType(mimeType: string | null | undefined, name: string): string {
  const type = (mimeType ?? '').split(';')[0].trim().toLowerCase();
  if (type === 'image/jpg' || type === 'image/pjpeg') {
    return 'image/jpeg';
  }
  if (type && type !== 'application/octet-stream') {
    return type;
  }
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  return TYPE_BY_EXTENSION[extension] ?? type;
}

export function isAllowedAttachmentType(type: string): type is AttachmentMediaType {
  return (ALLOWED_ATTACHMENT_TYPES as readonly string[]).includes(type);
}

/** Checks one file's type and size. */
export function checkAttachment(file: PickedFileInfo): AttachmentCheck {
  const mediaType = normalizeMediaType(file.mimeType, file.name);

  if (mediaType === 'image/heic' || mediaType === 'image/heif') {
    return {
      ok: false,
      reason: `${file.name} is a HEIC photo, which can't be sent. Share it as JPEG or PNG instead.`,
    };
  }
  if (!isAllowedAttachmentType(mediaType)) {
    return {
      ok: false,
      reason: `${file.name} can't be sent. Attach images (JPEG, PNG, GIF, WebP) or PDFs.`,
    };
  }
  if (typeof file.size === 'number' && file.size > MAX_ATTACHMENT_BYTES) {
    return { ok: false, reason: `${file.name} is larger than 5 MB.` };
  }
  return { ok: true, mediaType };
}

export interface AttachmentSelection<T extends PickedFileInfo> {
  accepted: { file: T; mediaType: AttachmentMediaType }[];
  /** One message per file left out, in pick order. */
  rejected: string[];
}

/**
 * Splits newly picked files into those that can be attached, given how many are already
 * attached, and messages for the rest.
 */
export function selectAttachments<T extends PickedFileInfo>(
  files: readonly T[],
  alreadyAttached: number
): AttachmentSelection<T> {
  const accepted: AttachmentSelection<T>['accepted'] = [];
  const rejected: string[] = [];
  let skippedForCount = 0;

  for (const file of files) {
    const check = checkAttachment(file);
    if (!check.ok) {
      rejected.push(check.reason);
    } else if (alreadyAttached + accepted.length >= MAX_ATTACHMENTS) {
      skippedForCount += 1;
    } else {
      accepted.push({ file, mediaType: check.mediaType });
    }
  }

  if (skippedForCount > 0) {
    rejected.push(
      `You can attach up to ${MAX_ATTACHMENTS} files. ${skippedForCount} ${
        skippedForCount === 1 ? 'file was' : 'files were'
      } left out.`
    );
  }

  return { accepted, rejected };
}

/** "1.2 MB" or "640 KB". */
export function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
