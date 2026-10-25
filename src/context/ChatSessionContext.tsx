/**
 * Chat Session Context
 *
 * Shares the thread open in the chat tab with the header's 3-dots menu: the chat screen
 * reports its thread once resolved, and reloads its messages when the menu asks it to
 * (for example after clearing the chat).
 */

import type { ThreadKind } from '@/lib/api/types';
import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

export interface ActiveThread {
  id: string;
  kind: ThreadKind;
}

interface ChatSessionContextValue {
  /** The thread open in the chat tab, once resolved. */
  activeThread: ActiveThread | null;
  setActiveThread: (thread: ActiveThread | null) => void;
  /** Changes whenever the open chat should reload its messages. */
  reloadSignal: number;
  requestReload: () => void;
}

const ChatSessionContext = createContext<ChatSessionContextValue>({
  activeThread: null,
  setActiveThread: () => {},
  reloadSignal: 0,
  requestReload: () => {},
});

export function ChatSessionProvider({ children }: { children: React.ReactNode }) {
  const [activeThread, setActiveThreadState] = useState<ActiveThread | null>(null);
  const [reloadSignal, setReloadSignal] = useState(0);

  // Keeps the same object when nothing changed, so consumers do not re-render.
  const setActiveThread = useCallback((thread: ActiveThread | null) => {
    setActiveThreadState((current) =>
      current?.id === thread?.id && current?.kind === thread?.kind ? current : thread
    );
  }, []);

  const requestReload = useCallback(() => setReloadSignal((signal) => signal + 1), []);

  const value = useMemo(
    () => ({ activeThread, setActiveThread, reloadSignal, requestReload }),
    [activeThread, setActiveThread, reloadSignal, requestReload]
  );

  return <ChatSessionContext.Provider value={value}>{children}</ChatSessionContext.Provider>;
}

export function useChatSession(): ChatSessionContextValue {
  return useContext(ChatSessionContext);
}
