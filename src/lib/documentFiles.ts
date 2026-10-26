/**
 * Opening a kept file (Files & links): it is downloaded and handed to the platform, the
 * share sheet on a phone (open in another app, save to Files, send), a download in a
 * browser.
 */

import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { Platform } from 'react-native';
import { getDocumentFile } from '@/lib/api/documents';
import type { UserDocument } from '@/lib/api/types';

/** Throws an `ApiError` (or an Error with a message to show) when it cannot. */
export async function shareDocumentFile(document: Pick<UserDocument, 'id' | 'title'>): Promise<void> {
  const file = await getDocumentFile(document.id);
  if (Platform.OS === 'web') {
    const link = window.document.createElement('a');
    link.href = `data:${file.media_type};base64,${file.data}`;
    link.download = file.name;
    link.click();
    return;
  }
  const copy = new File(Paths.cache, file.name);
  copy.create({ overwrite: true });
  await copy.write(file.data, { encoding: 'base64' });
  if (!(await Sharing.isAvailableAsync())) {
    throw new Error('Sharing is not available on this device.');
  }
  await Sharing.shareAsync(copy.uri, { mimeType: file.media_type, dialogTitle: document.title });
}
