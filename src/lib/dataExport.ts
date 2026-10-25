/**
 * Data Export
 *
 * Saves everything the backend holds for the user (`GET /me/export`) as one JSON file
 * and hands it to the platform: the share sheet on a phone (save to Files, send by mail,
 * and so on), a download in a browser.
 */

import { Platform } from 'react-native';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { getMyExport } from '@/lib/api/me';

/** `zoop-export-2026-10-24.json` for the day the export was made. */
export function exportFileName(exportedAt: string | undefined, now: Date = new Date()): string {
  const day =
    exportedAt && /^\d{4}-\d{2}-\d{2}/.test(exportedAt)
      ? exportedAt.slice(0, 10)
      : now.toISOString().slice(0, 10);
  return `zoop-export-${day}.json`;
}

/** Fetches the export and offers it to the user. Throws an `ApiError` when it fails. */
export async function exportMyData(): Promise<void> {
  const document = await getMyExport();
  const name = exportFileName(
    typeof document.exported_at === 'string' ? document.exported_at : undefined
  );
  const text = JSON.stringify(document, null, 2);

  if (Platform.OS === 'web') {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const link = window.document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
    return;
  }

  const file = new File(Paths.cache, name);
  file.create({ overwrite: true });
  await file.write(text);
  if (!(await Sharing.isAvailableAsync())) {
    throw new Error('Sharing is not available on this device.');
  }
  await Sharing.shareAsync(file.uri, {
    mimeType: 'application/json',
    UTI: 'public.json',
    dialogTitle: 'Save your Zoop data',
  });
}
