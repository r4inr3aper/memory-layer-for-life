/**
 * Documents API: files the user uploads for Cooper to read when relevant, such as a resume.
 * The text and the file are kept, so Cooper can also attach the file to an email; deleting
 * one removes both, and Cooper can no longer read or send it.
 */

import { apiRequest } from '@/lib/api/client';
import type {
  DocumentDetail,
  DocumentFile,
  UploadDocumentBody,
  UploadedDocument,
  UserDocument,
} from '@/lib/api/types';

/** The resume first, then the most recently changed. */
export function listDocuments(signal?: AbortSignal): Promise<UserDocument[]> {
  return apiRequest<UserDocument[]>('/me/documents', { signal });
}

/** Reads the file's text on the server. The same file again returns the stored document. */
export function uploadDocument(body: UploadDocumentBody): Promise<UploadedDocument> {
  return apiRequest<UploadedDocument>('/me/documents', { method: 'POST', body });
}

export function getDocument(documentId: string, signal?: AbortSignal): Promise<DocumentDetail> {
  return apiRequest<DocumentDetail>(`/me/documents/${encodeURIComponent(documentId)}`, {
    signal,
  });
}

/** The original file, to open or share. Not found for files of which only the text was kept. */
export function getDocumentFile(documentId: string, signal?: AbortSignal): Promise<DocumentFile> {
  return apiRequest<DocumentFile>(`/me/documents/${encodeURIComponent(documentId)}/file`, {
    signal,
  });
}

/** Rename it, or mark it as (or no longer as) the resume; marking unmarks the previous one. */
export function updateDocument(
  documentId: string,
  changes: { title?: string; is_resume?: boolean }
): Promise<UserDocument> {
  return apiRequest<UserDocument>(`/me/documents/${encodeURIComponent(documentId)}`, {
    method: 'PATCH',
    body: changes,
  });
}

export function deleteDocument(documentId: string): Promise<void> {
  return apiRequest<void>(`/me/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
  });
}
