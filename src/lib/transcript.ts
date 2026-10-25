/**
 * Chat Transcripts
 *
 * A readable plain-text copy of a thread, for sharing: "You: ..." and "{assistant}: ...".
 */

import { Platform, Share } from 'react-native';
import { isAbortError } from '@/lib/api/client';
import { listMessages } from '@/lib/api/threads';
import type { ChatMessage } from '@/lib/api/types';

const PAGE_LIMIT = 200;
const MAX_TRANSCRIPT_MESSAGES = 2000;

/** One paragraph per message, oldest first. Empty messages are left out. */
export function buildTranscript(messages: readonly ChatMessage[], assistantName: string): string {
  return messages
    .map((message) => {
      const speaker = message.role === 'user' ? 'You' : assistantName;
      const fileNames = message.metadata?.attachments?.map((file) => file.name) ?? [];
      const parts = [
        message.content.trim(),
        fileNames.length ? `[Attached: ${fileNames.join(', ')}]` : '',
      ].filter(Boolean);
      return parts.length ? `${speaker}: ${parts.join('\n')}` : '';
    })
    .filter(Boolean)
    .join('\n\n');
}

/** Every message of a thread (up to a generous cap), oldest first. */
export async function listAllMessages(threadId: string): Promise<ChatMessage[]> {
  const pages: ChatMessage[][] = [];
  let loaded = 0;

  for (;;) {
    const page = await listMessages(threadId, { limit: PAGE_LIMIT, offset: loaded });
    pages.unshift(page.items);
    loaded += page.items.length;
    if (page.items.length === 0 || loaded >= page.total || loaded >= MAX_TRANSCRIPT_MESSAGES) {
      break;
    }
  }

  return pages.flat();
}

/**
 * Opens the system share sheet with the transcript. Browsers without a share sheet get
 * the text copied to the clipboard instead. Resolves to what happened.
 */
export async function shareTranscript(
  transcript: string,
  title: string
): Promise<'shared' | 'dismissed' | 'copied'> {
  try {
    const result = await Share.share({ message: transcript, title }, { subject: title });
    return result.action === Share.dismissedAction ? 'dismissed' : 'shared';
  } catch (error) {
    if (Platform.OS !== 'web') {
      throw error;
    }
    // The user closed the browser's share sheet.
    if (isAbortError(error)) {
      return 'dismissed';
    }
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      throw error;
    }
    await navigator.clipboard.writeText(transcript);
    return 'copied';
  }
}
