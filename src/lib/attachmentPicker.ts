/**
 * Chat Attachment Picker
 *
 * Lets the user pick images and PDFs, checks them against the backend's limits, and reads
 * the accepted ones as base64 for `SendMessageBody.attachments`.
 */

import * as DocumentPicker from 'expo-document-picker';
import { File as FsFile } from 'expo-file-system';
import { Platform } from 'react-native';
import type { AttachmentInput } from '@/lib/api/types';
import { MAX_ATTACHMENT_BYTES, selectAttachments } from '@/lib/attachments';

/** A file attached to the message being written, ready to send. */
export interface PendingAttachment extends AttachmentInput {
  /** Local key for the chip; never sent. */
  id: string;
  size: number;
}

export interface PickAttachmentsResult {
  attachments: PendingAttachment[];
  /** User-facing reasons for files that were left out. */
  errors: string[];
}

let nextAttachmentId = 0;

/** Opens the picker. Resolves with nothing picked when the user cancels. */
export async function pickAttachments(alreadyAttached: number): Promise<PickAttachmentsResult> {
  const result = await DocumentPicker.getDocumentAsync({
    // `image/*` rather than the exact types, so a HEIC photo gets a clear message
    // instead of being silently unselectable.
    type: ['image/*', 'application/pdf'],
    multiple: true,
    copyToCacheDirectory: true,
    base64: false,
  });
  if (result.canceled) {
    return { attachments: [], errors: [] };
  }

  const files = result.assets.map((asset) => ({ ...asset, size: asset.size ?? fileSize(asset) }));
  const { accepted, rejected } = selectAttachments(files, alreadyAttached);
  const errors = [...rejected];
  const attachments: PendingAttachment[] = [];

  for (const { file, mediaType } of accepted) {
    try {
      const data = await readBase64(file);
      const size = file.size ?? base64ByteLength(data);
      if (size > MAX_ATTACHMENT_BYTES) {
        errors.push(`${file.name} is larger than 5 MB.`);
        continue;
      }
      nextAttachmentId += 1;
      attachments.push({
        id: `attachment-${nextAttachmentId}`,
        name: file.name,
        media_type: mediaType,
        data,
        size,
      });
    } catch (error) {
      console.warn('[attachments] Could not read a picked file:', error);
      errors.push(`${file.name} could not be read.`);
    }
  }

  return { attachments, errors };
}

function fileSize(asset: DocumentPicker.DocumentPickerAsset): number | undefined {
  if (Platform.OS === 'web') {
    return asset.file?.size;
  }
  try {
    return new FsFile(asset.uri).size;
  } catch {
    return undefined;
  }
}

/** The file's bytes as base64, without a `data:` prefix. */
export async function readBase64(asset: DocumentPicker.DocumentPickerAsset): Promise<string> {
  if (Platform.OS === 'web') {
    if (!asset.file) {
      throw new Error('The browser did not provide the file');
    }
    const dataUrl = await readAsDataUrl(asset.file);
    return dataUrl.slice(dataUrl.indexOf(',') + 1);
  }
  return new FsFile(asset.uri).base64();
}

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}

function base64ByteLength(data: string): number {
  const padding = data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0;
  return Math.floor((data.length * 3) / 4) - padding;
}
