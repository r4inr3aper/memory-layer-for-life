/**
 * Shared Navigation Targets
 */

import { router } from 'expo-router';

/** Opens the chat tab on a thread (main or side). */
export function openChatThread(threadId: string) {
  router.navigate({ pathname: '/(tabs)/chat', params: { thread_id: threadId } });
}

/** Opens the chat tab with `prompt` in the message input, ready to edit and send. */
export function openChatWithPrefill(prompt: string) {
  router.navigate({ pathname: '/(tabs)/chat', params: { prefill: prompt } });
}
