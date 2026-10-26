/**
 * Document Picker
 *
 * Lets the user pick one PDF, Word document, or text file for My files, checks it against
 * the backend's limits, and reads it as base64 for `uploadDocument`.
 */

import * as DocumentPicker from 'expo-document-picker';
import { File as FsFile } from 'expo-file-system';
import { Platform } from 'react-native';
import type { DocumentMediaType, UploadDocumentBody } from '@/lib/api/types';
import { readBase64 } from '@/lib/attachmentPicker';

/** The backend's DOCUMENT_MAX_BYTES. */
export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;

const DOCX: DocumentMediaType =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

/** Media types by file extension, for pickers that report none or a vague one. */
const BY_EXTENSION: Record<string, DocumentMediaType> = {
  pdf: 'application/pdf',
  docx: DOCX,
  txt: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
};

const PICKER_TYPES = ['application/pdf', DOCX, 'text/plain', 'text/markdown', 'text/*'];

/** The media type the backend takes for a file, or null when it takes none. */
export function documentMediaType(name: string, reported?: string | null): DocumentMediaType | null {
  const known = Object.values(BY_EXTENSION);
  if (reported && (known as string[]).includes(reported)) {
    return reported as DocumentMediaType;
  }
  if (reported === 'text/x-markdown') return 'text/markdown';
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  return BY_EXTENSION[extension] ?? null;
}

/**
 * Opens the picker for one document. Resolves with null when the user cancels; rejects
 * with an Error whose message can be shown when the file cannot be used.
 */
export async function pickDocument(): Promise<UploadDocumentBody | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: PICKER_TYPES,
    multiple: false,
    copyToCacheDirectory: true,
    base64: false,
  });
  if (result.canceled || result.assets.length === 0) {
    return null;
  }
  const asset = result.assets[0];
  const mediaType = documentMediaType(asset.name, asset.mimeType);
  if (!mediaType) {
    throw new Error(`${asset.name} is not a PDF, Word document (.docx), or text file.`);
  }
  const size = asset.size ?? fileSize(asset);
  if (size !== undefined && size > MAX_DOCUMENT_BYTES) {
    throw new Error(`${asset.name} is larger than 10 MB.`);
  }
  const data = await readBase64(asset);
  return { name: asset.name, media_type: mediaType, data };
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
