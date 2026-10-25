/**
 * Chat Tab Screen ('/(tabs)/chat')
 *
 * Minimalist, clean conversational companion UI:
 * - Scrollable message thread (main thread, or the side thread in `thread_id`)
 * - Assistant replies streamed from the backend API and rendered as Markdown
 * - The latest messages first, with "Load earlier messages" for long threads
 * - Image and PDF attachments, and voice dictation, in the input pill
 * - The input rides on top of the keyboard, frame by frame (`useChatKeyboard`)
 * - `prefill` route param (from Ideas): put in the input once, never sent automatically
 */

import { Colors } from '@/constants/colors';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { useChatSession, type ActiveThread } from '@/context/ChatSessionContext';
import { showToast } from '@/context/ToastContext';
import { streamReply } from '@/lib/api/chatStream';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import {
  confirmProposal,
  dismissProposal,
  ensureMainThread,
  getThread,
  listMessages,
} from '@/lib/api/threads';
import type { ChatStreamEvent, SendMessageBody, Thread } from '@/lib/api/types';
import { pickAttachments, type PendingAttachment } from '@/lib/attachmentPicker';
import { MAX_ATTACHMENTS } from '@/lib/attachments';
import { formatScheduleRule, formatTimezone } from '@/lib/formatSchedule';
import { useChatKeyboard } from '@/hooks/useChatKeyboard';
import { useVoiceInput } from '@/hooks/useVoiceInput';
import { ChatMessage, formatMessageTime, toUiMessage } from '@/types';
import { BriefCard, ReminderCard } from '@/components/chat/LifeCards';
import { ChatBrowserPreview } from '@/components/common/ChatBrowserPreview';
import { AttachmentChips } from '@/components/chat/AttachmentChips';
import { MarkdownText } from '@/components/chat/MarkdownText';
import {
  Add01Icon,
  Attachment01Icon,
  Link02Icon,
  Mic01Icon,
  SentIcon,
} from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  Keyboard,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import Animated from 'react-native-reanimated';

const MESSAGE_PAGE_LIMIT = 50;
const THINKING_TEXT = 'Thinking...';
const TYPING_TEXT = 'AI is typing...';
const NO_REPLY_TEXT = 'No Response from AI agent, Try Again';
const LOCAL_ID_PREFIX = 'local-';

export default function ChatScreen() {
  const router = useRouter();
  const { profile } = useAgentProfile();
  const { setActiveThread, reloadSignal } = useChatSession();

  const [thread, setThread] = useState<ActiveThread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // The thread `messages` belong to; until the open thread's messages load, none show.
  const [loadedThreadId, setLoadedThreadId] = useState<string | null>(null);
  const [hasEarlier, setHasEarlier] = useState(false);
  const [isLoadingEarlier, setIsLoadingEarlier] = useState(false);
  const [inputText, setInputText] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [isPicking, setIsPicking] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [typingText, setTypingText] = useState(TYPING_TEXT);

  const {
    scrollRef: scrollViewRef,
    areaRef: chatAreaRef,
    onScrollViewLayout,
    trackContentHeight,
    inputStyle: keyboardInputStyle,
    spacerStyle: keyboardSpacerStyle,
  } = useChatKeyboard();
  const streamAbortRef = useRef<AbortController | null>(null);
  const currentThreadIdRef = useRef<string | null>(null);
  // Scroll bookkeeping that keeps the view in place when older messages are added on top.
  const scrollYRef = useRef(0);
  const contentHeightRef = useRef(0);
  const prependAnchorRef = useRef<{
    contentHeight: number;
    scrollY: number;
  } | null>(null);
  // The input text when dictation started; the transcript is added after it.
  const voiceBaseTextRef = useRef('');

  const { thread_id, prefill } = useLocalSearchParams<{
    thread_id?: string;
    prefill?: string;
  }>();
  const routeThreadId = typeof thread_id === 'string' && thread_id ? thread_id : null;
  const routePrefill = typeof prefill === 'string' && prefill ? prefill : undefined;

  const threadId = thread?.id ?? null;
  const visibleMessages = loadedThreadId === threadId ? messages : [];

  // Put a prompt from the route (e.g. an idea) in the input once per navigation; the
  // effect below then clears the param so it is not applied again.
  const [appliedPrefill, setAppliedPrefill] = useState<string | undefined>(undefined);
  if (routePrefill !== appliedPrefill) {
    setAppliedPrefill(routePrefill);
    if (routePrefill) {
      setInputText(routePrefill);
    }
  }

  useEffect(() => {
    if (routePrefill) {
      router.setParams({ prefill: undefined });
    }
  }, [routePrefill, router]);

  const voice = useVoiceInput((transcript) => {
    const base = voiceBaseTextRef.current;
    setInputText(base ? `${base} ${transcript}` : transcript);
  });

  // Resolve the thread: the one in the route, otherwise the user's main thread.
  useEffect(() => {
    const controller = new AbortController();
    resolveThread(routeThreadId, controller.signal)
      .then((resolved) => {
        const next: ActiveThread = { id: resolved.id, kind: resolved.kind };
        setThread(next);
        setActiveThread(next);
      })
      .catch((error) => {
        if (isAbortError(error, controller.signal)) return;
        console.error('Failed to open chat:', error);
        showToast(getErrorMessage(error, 'Could not open the chat'));
      });

    return () => controller.abort();
  }, [routeThreadId, setActiveThread]);

  // The header menu acts on the open thread only while this screen exists.
  useEffect(() => () => setActiveThread(null), [setActiveThread]);

  useEffect(() => {
    currentThreadIdRef.current = threadId;
  }, [threadId]);

  // Messages also arrive while this screen is not looking: a scheduled result, a reminder,
  // the daily brief, or a reply that finished after the connection dropped. Check again
  // whenever the screen comes back into focus (a Feed row, the drawer) or the app returns
  // to the foreground (a notification tap). The first focus is the initial load itself.
  const [refreshCount, setRefreshCount] = useState(0);
  const requestRefresh = useCallback(() => setRefreshCount((count) => count + 1), []);
  const hasFocusedRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (hasFocusedRef.current) requestRefresh();
      hasFocusedRef.current = true;
    }, [requestRefresh])
  );
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') requestRefresh();
    });
    return () => subscription.remove();
  }, [requestRefresh]);

  const isSendingRef = useRef(false);
  useEffect(() => {
    isSendingRef.current = isSending;
  }, [isSending]);
  // The thread and clear-count the shown messages were fully loaded for.
  const loadedKeyRef = useRef<string | null>(null);

  // Load the thread's latest messages: in full when the thread opens or the header menu
  // asks (e.g. cleared), and as a check for newer ones on a refresh. A reply streaming in
  // brings its own messages, so a refresh then waits for the next one.
  useEffect(() => {
    if (!threadId) return;
    const key = `${threadId}:${reloadSignal}`;
    const isRefresh = loadedKeyRef.current === key;
    if (isRefresh && isSendingRef.current) return;

    const controller = new AbortController();
    listMessages(threadId, { limit: MESSAGE_PAGE_LIMIT }, controller.signal)
      .then((page) => {
        const latest = page.items.map(toUiMessage);
        if (isRefresh) {
          if (!isSendingRef.current) {
            setMessages((prev) => withNewerMessages(prev, latest));
          }
          return;
        }
        prependAnchorRef.current = null;
        setMessages(latest);
        setHasEarlier(page.total > page.items.length);
        setLoadedThreadId(threadId);
        loadedKeyRef.current = key;
      })
      .catch((error) => {
        if (isAbortError(error, controller.signal)) return;
        if (isRefresh) {
          console.warn('Failed to check for new messages:', error);
          return;
        }
        console.error('Failed to load messages:', error);
        showToast(getErrorMessage(error, 'Could not load messages'));
      });

    return () => controller.abort();
  }, [threadId, reloadSignal, refreshCount]);

  // Stop any reply still streaming into a thread the user left.
  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      setIsSending(false);
    };
  }, [threadId]);

  useEffect(() => {
    // Older messages were just added on top: keep the reading position instead.
    if (prependAnchorRef.current) return;
    scrollViewRef.current?.scrollToEnd({ animated: true });
  }, [messages, scrollViewRef]);

  const updateMessage = (messageId: string, update: (msg: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((msg) => (msg.id === messageId ? update(msg) : msg)));
  };

  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    scrollYRef.current = event.nativeEvent.contentOffset.y;
  };

  const handleContentSizeChange = (_width: number, height: number) => {
    const anchor = prependAnchorRef.current;
    if (anchor) {
      prependAnchorRef.current = null;
      scrollViewRef.current?.scrollTo({
        y: Math.max(0, anchor.scrollY + height - anchor.contentHeight),
        animated: false,
      });
    }
    contentHeightRef.current = height;
    trackContentHeight(height);
  };

  /** Prepends the page of messages before the ones loaded, keeping the scroll position. */
  const handleLoadEarlier = async () => {
    if (!threadId || isLoadingEarlier) return;

    // The server pages back from the newest message; skip every stored one already shown.
    const storedCount = messages.filter(isStoredMessage).length;
    setIsLoadingEarlier(true);
    try {
      const page = await listMessages(threadId, {
        limit: MESSAGE_PAGE_LIMIT,
        offset: storedCount,
      });
      if (currentThreadIdRef.current !== threadId) return;

      const shownIds = new Set(messages.map((msg) => msg.id));
      const older = page.items.filter((msg) => !shownIds.has(msg.id)).map(toUiMessage);
      if (older.length > 0) {
        prependAnchorRef.current = {
          contentHeight: contentHeightRef.current,
          scrollY: scrollYRef.current,
        };
        setMessages((prev) => {
          const prevIds = new Set(prev.map((msg) => msg.id));
          return [...older.filter((msg) => !prevIds.has(msg.id)), ...prev];
        });
      }
      setHasEarlier(page.total > storedCount + page.items.length);
    } catch (error) {
      console.error('Failed to load earlier messages:', error);
      showToast(getErrorMessage(error, 'Could not load earlier messages'));
    } finally {
      setIsLoadingEarlier(false);
    }
  };

  const handleAttachPress = async () => {
    if (isPicking || isSending) return;
    if (attachments.length >= MAX_ATTACHMENTS) {
      showToast(`You can attach up to ${MAX_ATTACHMENTS} files.`);
      return;
    }

    setIsPicking(true);
    try {
      const picked = await pickAttachments(attachments.length);
      if (picked.attachments.length > 0) {
        setAttachments((prev) => [...prev, ...picked.attachments].slice(0, MAX_ATTACHMENTS));
      }
      if (picked.errors.length > 0) {
        const more = picked.errors.length - 1;
        showToast(more > 0 ? `${picked.errors[0]} (+${more} more)` : picked.errors[0], 4000);
      }
    } catch (error) {
      console.error('Failed to pick files:', error);
      showToast(getErrorMessage(error, 'Could not open the file picker'));
    } finally {
      setIsPicking(false);
    }
  };

  const handleRemoveAttachment = (attachmentId: string) => {
    setAttachments((prev) => prev.filter((attachment) => attachment.id !== attachmentId));
  };

  const handleMicPress = () => {
    if (!voice.isListening) {
      voiceBaseTextRef.current = inputText.trim();
    }
    voice.toggle();
  };

  const handleSend = async () => {
    const text = inputText.trim();
    const files = attachments;
    if ((!text && files.length === 0) || isSending) return;

    // Until the thread's messages are shown, a sent message would be invisible, or wiped
    // when they arrive; a failed load is retried here.
    if (!threadId || loadedThreadId !== threadId) {
      showToast('The chat is still loading. Try again in a moment.');
      if (threadId) requestRefresh();
      return;
    }

    if (voice.isListening) {
      voice.toggle();
    }

    const localId = Date.now();
    const userMessageId = `${LOCAL_ID_PREFIX}user-${localId}`;
    const agentMessageId = `${LOCAL_ID_PREFIX}agent-${localId}`;
    const timestamp = formatMessageTime();

    setMessages((prev) => [
      ...prev,
      {
        id: userMessageId,
        sender: 'user',
        text,
        timestamp,
        pending: true,
        attachments: files.length
          ? files.map((file) => ({
              name: file.name,
              mediaType: file.media_type,
              sizeBytes: file.size,
            }))
          : undefined,
      },
      {
        id: agentMessageId,
        sender: 'agent',
        text: THINKING_TEXT,
        timestamp,
        pending: true,
        streaming: true,
      },
    ]);
    setInputText('');
    setAttachments([]);
    setTypingText(TYPING_TEXT);
    setIsSending(true);

    const controller = new AbortController();
    streamAbortRef.current = controller;
    let isStored = false;
    let hasReplyText = false;
    let isFinished = false;

    const updateReply = (update: (msg: ChatMessage) => ChatMessage) =>
      updateMessage(agentMessageId, update);

    const handleEvent = (event: ChatStreamEvent) => {
      switch (event.type) {
        case 'turn_started':
          isStored = true;
          updateMessage(userMessageId, () => toUiMessage(event.user_message));
          break;
        case 'text_delta': {
          const isFirstDelta = !hasReplyText;
          hasReplyText = true;
          setTypingText(TYPING_TEXT);
          updateReply((msg) => ({
            ...msg,
            text: isFirstDelta ? event.text : msg.text + event.text,
          }));
          break;
        }
        case 'tool_started': {
          const activity = `${event.label}...`;
          setTypingText(activity);
          if (!hasReplyText) {
            updateReply((msg) => ({ ...msg, text: activity }));
          }
          break;
        }
        case 'browser':
          updateReply((msg) => ({
            ...msg,
            browserPreview: event.browser_preview,
          }));
          break;
        case 'connect_link':
          updateReply((msg) => ({ ...msg, connectCta: event.connect_link }));
          break;
        case 'final':
          isFinished = true;
          updateReply(() => toUiMessage(event.message));
          break;
        case 'error':
          isFinished = true;
          updateReply((msg) => ({
            ...msg,
            text: event.message,
            pending: false,
            streaming: false,
          }));
          showToast(event.message);
          break;
      }
    };

    const body: SendMessageBody = {
      content: text,
      timezone: getDeviceTimezone(),
    };
    if (files.length > 0) {
      body.attachments = files.map(({ name, media_type, data }) => ({
        name,
        media_type,
        data,
      }));
    }

    try {
      await streamReply(threadId, body, handleEvent, controller.signal);

      if (!isFinished) {
        updateReply((msg) => ({
          ...msg,
          text: hasReplyText ? msg.text : NO_REPLY_TEXT,
          streaming: false,
        }));
      }
    } catch (error) {
      if (isAbortError(error, controller.signal)) return;

      console.error('Error sending message:', error);
      // Includes the daily prompt limit: the server's message says what to do.
      const errorMessage = getErrorMessage(error, 'Failed to send message');
      if (!isStored) {
        // The server refused the message before storing it: take both bubbles back and
        // return the text and files to the input, so nothing unsaved looks sent.
        setMessages((prev) =>
          prev.filter((msg) => msg.id !== userMessageId && msg.id !== agentMessageId)
        );
        setInputText((current) => current || text);
        setAttachments((current) => (current.length > 0 ? current : files));
      } else {
        updateReply((msg) => ({
          ...msg,
          text: errorMessage,
          pending: false,
          streaming: false,
        }));
      }
      showToast(errorMessage, 3500);
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
        setIsSending(false);
      }
    }
  };

  const handleOpenConnectLink = async (connectUrl: string, toolName: string) => {
    try {
      showToast(`Opening ${toolName} connection...`);
      if (Platform.OS === 'web') {
        window.open(connectUrl, '_blank');
      } else {
        await WebBrowser.openAuthSessionAsync(connectUrl);
      }
    } catch (error) {
      showToast(getErrorMessage(error, `Could not open ${toolName} connection`));
    }
  };

  const handleConfirmSchedule = async (messageId: string) => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!threadId || message?.scheduleProposal?.status !== 'pending') return;

    updateMessage(messageId, (msg) => ({
      ...msg,
      scheduleAction: 'confirming',
      scheduleError: undefined,
    }));

    try {
      const result = await confirmProposal(threadId, messageId);
      updateMessage(messageId, () => toUiMessage(result.message));
      showToast('Schedule created');
    } catch (error) {
      console.error('Failed to create schedule:', error);
      const errorMessage = getErrorMessage(error, 'Could not create schedule');
      updateMessage(messageId, (msg) => ({
        ...msg,
        scheduleAction: undefined,
        scheduleError: errorMessage,
      }));
      showToast(errorMessage);
    }
  };

  /** Dismisses a pending proposal. Resolves to whether it worked. */
  const dismissSchedule = async (messageId: string): Promise<boolean> => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!threadId || message?.scheduleProposal?.status !== 'pending') return false;

    updateMessage(messageId, (msg) => ({
      ...msg,
      scheduleAction: 'dismissing',
      scheduleError: undefined,
    }));

    try {
      const updated = await dismissProposal(threadId, messageId);
      updateMessage(messageId, () => toUiMessage(updated));
      return true;
    } catch (error) {
      console.error('Failed to dismiss schedule:', error);
      const errorMessage = getErrorMessage(error, 'Could not cancel the schedule');
      updateMessage(messageId, (msg) => ({
        ...msg,
        scheduleAction: undefined,
        scheduleError: errorMessage,
      }));
      showToast(errorMessage);
      return false;
    }
  };

  const handleCancelSchedule = (messageId: string) => {
    void dismissSchedule(messageId);
  };

  const handleEditSchedule = async (messageId: string) => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!message?.scheduleProposal) return;

    setInputText(message.scheduleProposal.original_prompt);
    if (await dismissSchedule(messageId)) {
      showToast('Edit the request, then send it again.');
    }
  };

  const hasDraft = inputText.trim().length > 0 || attachments.length > 0;
  // While dictating, the right button stays the microphone so a tap stops listening.
  const showSendButton = hasDraft && !voice.isListening;

  return (
    <Animated.View ref={chatAreaRef} style={styles.container}>
      <View style={styles.content}>
        {/* Scrollable Messages Thread */}
        <Animated.ScrollView
          ref={scrollViewRef}
          onLayout={onScrollViewLayout}
          style={styles.scrollArea}
          contentContainerStyle={styles.scrollContent}
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          onScroll={handleScroll}
          scrollEventThrottle={32}
          onContentSizeChange={handleContentSizeChange}>
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <View style={styles.scrollInner}>
              {/* Older messages, a page at a time */}
              {hasEarlier && visibleMessages.length > 0 ? (
                <TouchableOpacity
                  style={styles.loadEarlierBtn}
                  onPress={handleLoadEarlier}
                  disabled={isLoadingEarlier}
                  activeOpacity={0.75}
                  accessibilityRole="button">
                  {isLoadingEarlier ? (
                    <ActivityIndicator size="small" color={Colors.primary} />
                  ) : (
                    <Text style={styles.loadEarlierText}>Load earlier messages</Text>
                  )}
                </TouchableOpacity>
              ) : null}

              {/* Centered Date Badge */}
              <View style={styles.dateBadgeContainer}>
                <View style={styles.dateBadge}>
                  <Text style={styles.dateBadgeText}>Today</Text>
                </View>
              </View>

              {/* Messages */}
              {visibleMessages.map((msg) => {
                const isUser = msg.sender === 'user';
                return (
                  <TouchableOpacity
                    key={msg.id}
                    activeOpacity={0.9}
                    onPress={() => showToast(msg.text)}
                    style={[
                      styles.messageRow,
                      isUser ? styles.userMessageRow : styles.agentMessageRow,
                    ]}>
                    <View style={[styles.bubble, isUser ? styles.userBubble : styles.agentBubble]}>
                      {isUser ? (
                        msg.text ? (
                          <Text style={[styles.bubbleText, styles.userBubbleText]}>{msg.text}</Text>
                        ) : null
                      ) : (
                        <MarkdownText text={msg.text} />
                      )}

                      {msg.attachments?.length ? (
                        <View
                          style={[styles.attachmentList, !msg.text && styles.attachmentListOnly]}>
                          {msg.attachments.map((file, index) => (
                            <View key={`${file.name}-${index}`} style={styles.attachmentNote}>
                              <HugeiconsIcon
                                icon={Attachment01Icon}
                                size={14}
                                color={isUser ? Colors.chatBubbleUserText : Colors.iconDark}
                                strokeWidth={2}
                              />
                              <Text
                                style={[styles.attachmentNoteText, isUser && styles.userBubbleText]}
                                numberOfLines={1}>
                                {file.name}
                              </Text>
                            </View>
                          ))}
                        </View>
                      ) : null}

                      {!isUser && msg.connectCta ? (
                        <View style={styles.connectCard}>
                          <View style={styles.connectIcon}>
                            <HugeiconsIcon
                              icon={Link02Icon}
                              size={20}
                              color={Colors.primary}
                              strokeWidth={2}
                            />
                          </View>
                          <View style={styles.connectBody}>
                            <Text style={styles.connectTitle}>
                              Connect {msg.connectCta.tool_name}
                            </Text>
                            <Text style={styles.connectSubtitle}>
                              Complete authorization, then send done.
                            </Text>
                          </View>
                          <TouchableOpacity
                            style={styles.connectButton}
                            onPress={() =>
                              handleOpenConnectLink(
                                msg.connectCta!.connect_url,
                                msg.connectCta!.tool_name
                              )
                            }
                            activeOpacity={0.8}>
                            <Text style={styles.connectButtonText}>Connect</Text>
                          </TouchableOpacity>
                        </View>
                      ) : null}

                      {!isUser && msg.browserPreview ? (
                        <ChatBrowserPreview browserPreview={msg.browserPreview} />
                      ) : null}

                      {!isUser && msg.reminder ? <ReminderCard note={msg.reminder} /> : null}

                      {!isUser && msg.brief && msg.brief.follow_ups.length ? (
                        <BriefCard note={msg.brief} />
                      ) : null}

                      {!isUser && msg.scheduleProposal ? (
                        <View style={styles.scheduleCard}>
                          <Text style={styles.scheduleTitle}>Schedule this task?</Text>
                          <View style={styles.scheduleDetailRow}>
                            <Text style={styles.scheduleLabel}>Task</Text>
                            <Text style={styles.scheduleValue}>{msg.scheduleProposal.title}</Text>
                          </View>
                          <View style={styles.scheduleDetailRow}>
                            <Text style={styles.scheduleLabel}>When</Text>
                            <Text style={styles.scheduleValue}>
                              {`${formatScheduleRule(msg.scheduleProposal)} (${formatTimezone(
                                msg.scheduleProposal.timezone
                              )})`}
                            </Text>
                          </View>
                          <View style={styles.scheduleDetailRow}>
                            <Text style={styles.scheduleLabel}>Does</Text>
                            <Text style={styles.scheduleValue} numberOfLines={4}>
                              {msg.scheduleProposal.task}
                            </Text>
                          </View>
                          <View style={styles.scheduleDetailRow}>
                            <Text style={styles.scheduleLabel}>Delivery</Text>
                            <Text style={styles.scheduleValue}>
                              {formatDeliveryLabel(msg.scheduleProposal.delivery)}
                              {msg.scheduleProposal.delivery_target
                                ? ` · ${msg.scheduleProposal.delivery_target}`
                                : ''}
                            </Text>
                          </View>
                          <Text style={styles.scheduleSummary}>{msg.scheduleProposal.summary}</Text>

                          {msg.scheduleError ? (
                            <Text style={styles.scheduleError}>{msg.scheduleError}</Text>
                          ) : null}

                          <View style={styles.scheduleActions}>
                            <TouchableOpacity
                              style={[
                                styles.scheduleButton,
                                styles.schedulePrimaryButton,
                                !canActOnProposal(msg) && styles.scheduleButtonDisabled,
                              ]}
                              disabled={!canActOnProposal(msg)}
                              onPress={() => handleConfirmSchedule(msg.id)}
                              activeOpacity={0.8}>
                              <Text style={styles.schedulePrimaryButtonText}>
                                {msg.scheduleAction === 'confirming'
                                  ? 'Saving...'
                                  : msg.scheduleProposal.status === 'confirmed'
                                    ? 'Confirmed'
                                    : msg.scheduleProposal.status === 'dismissed'
                                      ? 'Cancelled'
                                      : 'Confirm'}
                              </Text>
                            </TouchableOpacity>
                            <TouchableOpacity
                              style={styles.scheduleButton}
                              disabled={!canActOnProposal(msg)}
                              onPress={() => handleEditSchedule(msg.id)}
                              activeOpacity={0.8}>
                              <Text style={styles.scheduleButtonText}>Edit</Text>
                            </TouchableOpacity>
                            <TouchableOpacity
                              style={styles.scheduleButton}
                              disabled={!canActOnProposal(msg)}
                              onPress={() => handleCancelSchedule(msg.id)}
                              activeOpacity={0.8}>
                              <Text style={styles.scheduleButtonText}>Cancel</Text>
                            </TouchableOpacity>
                          </View>
                        </View>
                      ) : null}
                    </View>
                  </TouchableOpacity>
                );
              })}

              {isSending && (
                <Text style={styles.typingText}>
                  <ActivityIndicator /> {typingText}
                </Text>
              )}
            </View>
          </TouchableWithoutFeedback>
          {/* As tall as the keyboard reaches over the list, so every message can be
                scrolled above the input while the keyboard is open. */}
          <Animated.View style={keyboardSpacerStyle} />
        </Animated.ScrollView>

        {/* Floating Input Pill, carried on top of the keyboard */}
        <Animated.View style={[styles.inputWrapper, keyboardInputStyle]}>
          <AttachmentChips attachments={attachments} onRemove={handleRemoveAttachment} />

          <View style={styles.inputBar}>
            {/* Plus Attach Button */}
            <TouchableOpacity
              style={styles.circleBtn}
              onPress={handleAttachPress}
              disabled={isPicking}
              activeOpacity={0.7}
              accessibilityRole="button"
              accessibilityLabel="Attach images or PDFs">
              {isPicking ? (
                <ActivityIndicator size="small" color={Colors.iconDark} />
              ) : (
                <HugeiconsIcon
                  icon={Add01Icon}
                  size={20}
                  color={Colors.iconDark}
                  strokeWidth={2.2}
                />
              )}
            </TouchableOpacity>

            {/* Prompt Text Input */}
            <TextInput
              style={styles.textInput}
              value={inputText}
              onChangeText={setInputText}
              placeholder={
                voice.isListening
                  ? 'Listening...'
                  : `Ask ${profile.name} to read emails, send Slack msgs, or schedule meetings...`
              }
              placeholderTextColor={Colors.iconMuted}
              returnKeyType="send"
              onSubmitEditing={handleSend}
            />

            {/* Right Action: Voice or Send */}
            {showSendButton ? (
              <TouchableOpacity
                style={[styles.circleBtn, styles.sendBtn]}
                onPress={handleSend}
                activeOpacity={0.8}
                accessibilityRole="button"
                accessibilityLabel="Send message">
                <HugeiconsIcon icon={SentIcon} size={18} color={Colors.white} strokeWidth={2.4} />
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[styles.circleBtn, voice.isListening && styles.micListeningBtn]}
                onPress={handleMicPress}
                activeOpacity={0.7}
                accessibilityRole="button"
                accessibilityLabel={voice.isListening ? 'Stop voice input' : 'Voice input'}
                accessibilityState={{ selected: voice.isListening }}>
                <HugeiconsIcon
                  icon={Mic01Icon}
                  size={20}
                  color={voice.isListening ? Colors.white : Colors.iconDark}
                  strokeWidth={2}
                />
              </TouchableOpacity>
            )}
          </View>
        </Animated.View>
      </View>
    </Animated.View>
  );
}

/** The thread in the route (falling back to the main thread when it is gone), or main. */
async function resolveThread(routeThreadId: string | null, signal: AbortSignal): Promise<Thread> {
  if (routeThreadId) {
    try {
      return await getThread(routeThreadId, signal);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        throw error;
      }
      showToast('That chat no longer exists. Opening the main chat.');
    }
  }
  return ensureMainThread(signal);
}

/** Stored on the server, as opposed to an optimistic bubble or a local error reply. */
function isStoredMessage(msg: ChatMessage) {
  return !msg.id.startsWith(LOCAL_ID_PREFIX);
}

/**
 * The shown messages with any stored ones that arrived since added at the end. When
 * something new arrived, unsaved placeholders go (e.g. a bubble saying the connection
 * dropped, now that the stored reply is here). Nothing new: the same array, so the list
 * does not re-render or scroll.
 */
function withNewerMessages(shown: ChatMessage[], latest: ChatMessage[]): ChatMessage[] {
  const shownIds = new Set(shown.map((msg) => msg.id));
  const added = latest.filter((msg) => !shownIds.has(msg.id));
  if (added.length === 0) return shown;
  return [...shown.filter(isStoredMessage), ...added];
}

function formatDeliveryLabel(delivery?: string | null) {
  return (
    (delivery || 'chat')
      .split(/[_-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ') || 'Chat'
  );
}

/** The schedule card's buttons work only on a stored, pending proposal with no request in flight. */
function canActOnProposal(msg: ChatMessage) {
  return msg.scheduleProposal?.status === 'pending' && !msg.scheduleAction && !msg.pending;
}

/** IANA timezone of the device, sent with each message for times and schedules. */
function getDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  content: {
    flex: 1,
    justifyContent: 'space-between',
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    flexGrow: 1,
  },
  scrollInner: {
    flexGrow: 1,
  },
  dateBadgeContainer: {
    alignItems: 'center',
    marginVertical: 14,
  },
  dateBadge: {
    backgroundColor: Colors.dateBadgeBg,
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 12,
  },
  dateBadgeText: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.dateBadgeText,
  },
  messageRow: {
    marginBottom: 12,
    width: '100%',
    flexDirection: 'row',
  },
  userMessageRow: {
    justifyContent: 'flex-end',
  },
  agentMessageRow: {
    justifyContent: 'flex-start',
  },
  bubble: {
    maxWidth: '85%',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 20,
  },
  userBubble: {
    backgroundColor: Colors.chatBubbleUser,
    borderBottomRightRadius: 6,
  },
  agentBubble: {
    backgroundColor: Colors.chatBubbleAi,
    borderBottomLeftRadius: 6,
  },
  bubbleText: {
    fontSize: 15.5,
    lineHeight: 22,
    letterSpacing: -0.1,
  },
  userBubbleText: {
    color: Colors.chatBubbleUserText,
    fontWeight: '500',
  },
  loadEarlierBtn: {
    alignSelf: 'center',
    minHeight: 32,
    justifyContent: 'center',
    paddingHorizontal: 14,
    paddingVertical: 6,
    marginTop: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
    backgroundColor: Colors.white,
  },
  loadEarlierText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: Colors.primary,
  },
  attachmentList: {
    marginTop: 8,
    gap: 4,
  },
  attachmentListOnly: {
    marginTop: 0,
  },
  attachmentNote: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  attachmentNoteText: {
    flexShrink: 1,
    fontSize: 13,
    color: Colors.iconDark,
  },
  typingText: {
    fontStyle: 'italic',
    color: Colors.iconMuted,
    textAlign: 'left',
    marginTop: 8,
  },
  micListeningBtn: {
    backgroundColor: Colors.primary,
  },
  inputWrapper: {
    paddingHorizontal: 16,
    paddingBottom: Platform.OS === 'ios' ? 12 : 10,
    paddingTop: 6,
    backgroundColor: Colors.white,
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.inputBarBg,
    borderRadius: 26,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  circleBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtn: {
    backgroundColor: Colors.iconDark,
  },
  textInput: {
    flex: 1,
    fontSize: 14.5,
    color: Colors.iconDark,
    paddingHorizontal: 10,
    paddingVertical: Platform.OS === 'ios' ? 8 : 4,
  },
  connectCard: {
    marginTop: 12,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
    flexDirection: 'row',
    alignItems: 'center',
  },
  connectIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primarySubtle,
    marginRight: 10,
  },
  connectBody: {
    flex: 1,
    marginRight: 10,
  },
  connectTitle: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  connectSubtitle: {
    fontSize: 12,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  connectButton: {
    backgroundColor: Colors.primary,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  connectButtonText: {
    color: Colors.white,
    fontSize: 12.5,
    fontWeight: '700',
  },
  scheduleCard: {
    marginTop: 12,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
  },
  scheduleTitle: {
    fontSize: 14,
    fontWeight: '800',
    color: Colors.iconDark,
    marginBottom: 10,
  },
  scheduleDetailRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  scheduleLabel: {
    width: 64,
    fontSize: 12,
    fontWeight: '700',
    color: Colors.textSecondary,
  },
  scheduleValue: {
    flex: 1,
    fontSize: 13,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  scheduleSummary: {
    fontSize: 12.5,
    lineHeight: 18,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  scheduleError: {
    fontSize: 12.5,
    lineHeight: 18,
    color: Colors.error,
    marginTop: 8,
  },
  scheduleActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  scheduleButton: {
    minHeight: 34,
    borderRadius: 10,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
  },
  schedulePrimaryButton: {
    borderColor: Colors.primary,
    backgroundColor: Colors.primary,
  },
  scheduleButtonDisabled: {
    opacity: 0.65,
  },
  scheduleButtonText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  schedulePrimaryButtonText: {
    fontSize: 12.5,
    fontWeight: '800',
    color: Colors.white,
  },
});
