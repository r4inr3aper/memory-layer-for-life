/**
 * Chat Tab Screen ('/(tabs)/chat')
 *
 * Minimalist, clean conversational companion UI:
 * - Scrollable message thread (main thread, or the side thread in `thread_id`)
 * - Assistant replies streamed from the backend API and rendered as Markdown
 * - The latest messages first, with "Load earlier messages" for long threads
 * - Looks like Messages: the user's bubbles in the tint, the assistant's in iMessage gray,
 *   tight within a run; cards (schedules, drafts, links) as grouped-gray iOS cards below
 * - Image and PDF attachments, and voice dictation, in the composer
 * - The composer rides on top of the keyboard, frame by frame (`useChatKeyboard`)
 * - `prefill` route param (from Ideas): put in the input once, never sent automatically
 * - Under the user's messages: what was remembered from them, with Undo, and "Save to My
 *   files" for a PDF sent from this device
 */

import { AttachmentChips } from "@/components/chat/AttachmentChips";
import { BriefCard, ReminderCard } from "@/components/chat/LifeCards";
import { MarkdownText } from "@/components/chat/MarkdownText";
import { ChatBrowserPreview } from "@/components/common/ChatBrowserPreview";
import { AppText, Button, Card, PressableScale } from "@/components/ui";
import { Colors } from "@/constants/colors";
import {
    Hairline,
    Motion,
    Radius,
    ScreenMargin,
    Typography,
    continuous,
} from "@/constants/theme";
import { useAgentProfile } from "@/context/AgentProfileContext";
import {
    useChatSession,
    type ActiveThread,
} from "@/context/ChatSessionContext";
import { showToast } from "@/context/ToastContext";
import { useChatKeyboard } from "@/hooks/useChatKeyboard";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { streamReply } from "@/lib/api/chatStream";
import { ApiError, getErrorMessage, isAbortError } from "@/lib/api/client";
import { uploadDocument } from "@/lib/api/documents";
import { changeMemoryStatus } from "@/lib/api/memories";
import {
    confirmProposal,
    dismissProposal,
    ensureMainThread,
    getThread,
    listMessages,
    sendJobApplicationDraft,
} from "@/lib/api/threads";
import type {
    ChatStreamEvent,
    DraftAttachment,
    SavedMemory,
    SendMessageBody,
    Thread,
} from "@/lib/api/types";
import {
    pickAttachments,
    type PendingAttachment,
} from "@/lib/attachmentPicker";
import { MAX_ATTACHMENTS, formatFileSize } from "@/lib/attachments";
import { formatScheduleRule, formatTimezone } from "@/lib/formatSchedule";
import { haptic } from "@/lib/haptics";
import { ChatMessage, formatMessageTime, toUiMessage } from "@/types";
import {
    Add01Icon,
    ArrowUp02Icon,
    Attachment01Icon,
    Brain01Icon,
    File01Icon,
    Link02Icon,
    Mic01Icon,
    Tick02Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react-native";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    ActivityIndicator,
    AppState,
    Keyboard,
    NativeScrollEvent,
    NativeSyntheticEvent,
    Platform,
    Pressable,
    StyleSheet,
    TextInput,
    View,
    type AccessibilityState,
} from "react-native";
import Animated, {
    LayoutAnimationConfig,
    withTiming,
    type EntryExitAnimationFunction,
} from "react-native-reanimated";

const MESSAGE_PAGE_LIMIT = 50;
const THINKING_TEXT = "Thinking...";
const TYPING_TEXT = "AI is typing...";
const NO_REPLY_TEXT = "No Response from AI agent, Try Again";
const LOCAL_ID_PREFIX = "local-";
const PDF_TYPE = "application/pdf";

// A press on a bubble waits this long before it shows, so a finger that lands on a bubble
// to scroll the thread does not make it shrink (iOS delays touches in scroll views too).
const BUBBLE_PRESS_DELAY = 100;

// The send button replacing the microphone (and back): a quick scale-up from 90% with a
// fade, on the strong ease-out. Reduce Motion skips it (withTiming's default).
const COMPOSER_ACTION_TIMING = {
  duration: Motion.duration.small,
  easing: Motion.easeOut,
};
const composerActionEntering: EntryExitAnimationFunction = () => {
  "worklet";
  return {
    initialValues: { opacity: 0, transform: [{ scale: 0.9 }] },
    animations: {
      opacity: withTiming(1, COMPOSER_ACTION_TIMING),
      transform: [{ scale: withTiming(1, COMPOSER_ACTION_TIMING) }],
    },
  };
};

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
  const [inputText, setInputText] = useState("");
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
  const voiceBaseTextRef = useRef("");

  const { thread_id, prefill } = useLocalSearchParams<{
    thread_id?: string;
    prefill?: string;
  }>();
  const routeThreadId =
    typeof thread_id === "string" && thread_id ? thread_id : null;
  const routePrefill =
    typeof prefill === "string" && prefill ? prefill : undefined;

  const threadId = thread?.id ?? null;
  const visibleMessages = loadedThreadId === threadId ? messages : [];

  // Put a prompt from the route (e.g. an idea) in the input once per navigation; the
  // effect below then clears the param so it is not applied again.
  const [appliedPrefill, setAppliedPrefill] = useState<string | undefined>(
    undefined,
  );
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
        console.error("Failed to open chat:", error);
        showToast(getErrorMessage(error, "Could not open the chat"));
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
  const requestRefresh = useCallback(
    () => setRefreshCount((count) => count + 1),
    [],
  );
  const hasFocusedRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (hasFocusedRef.current) requestRefresh();
      hasFocusedRef.current = true;
    }, [requestRefresh]),
  );
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") requestRefresh();
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
          console.warn("Failed to check for new messages:", error);
          return;
        }
        console.error("Failed to load messages:", error);
        showToast(getErrorMessage(error, "Could not load messages"));
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

  const updateMessage = (
    messageId: string,
    update: (msg: ChatMessage) => ChatMessage,
  ) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === messageId ? update(msg) : msg)),
    );
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
      const older = page.items
        .filter((msg) => !shownIds.has(msg.id))
        .map(toUiMessage);
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
      console.error("Failed to load earlier messages:", error);
      showToast(getErrorMessage(error, "Could not load earlier messages"));
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
        setAttachments((prev) =>
          [...prev, ...picked.attachments].slice(0, MAX_ATTACHMENTS),
        );
      }
      if (picked.errors.length > 0) {
        const more = picked.errors.length - 1;
        showToast(
          more > 0 ? `${picked.errors[0]} (+${more} more)` : picked.errors[0],
          4000,
        );
      }
    } catch (error) {
      console.error("Failed to pick files:", error);
      showToast(getErrorMessage(error, "Could not open the file picker"));
    } finally {
      setIsPicking(false);
    }
  };

  const handleRemoveAttachment = (attachmentId: string) => {
    setAttachments((prev) =>
      prev.filter((attachment) => attachment.id !== attachmentId),
    );
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
      showToast("The chat is still loading. Try again in a moment.");
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

    haptic.light();
    setMessages((prev) => [
      ...prev,
      {
        id: userMessageId,
        sender: "user",
        text,
        timestamp,
        pending: true,
        attachments: files.length
          ? files.map((file) => ({
              name: file.name,
              mediaType: file.media_type,
              sizeBytes: file.size,
              data: file.media_type === PDF_TYPE ? file.data : undefined,
            }))
          : undefined,
      },
      {
        id: agentMessageId,
        sender: "agent",
        text: THINKING_TEXT,
        timestamp,
        pending: true,
        streaming: true,
      },
    ]);
    setInputText("");
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
        case "turn_started":
          isStored = true;
          updateMessage(userMessageId, (local) =>
            withLocalFiles(toUiMessage(event.user_message), local),
          );
          break;
        case "text_delta": {
          const isFirstDelta = !hasReplyText;
          hasReplyText = true;
          setTypingText(TYPING_TEXT);
          updateReply((msg) => ({
            ...msg,
            text: isFirstDelta ? event.text : msg.text + event.text,
          }));
          break;
        }
        case "tool_started": {
          const activity = `${event.label}...`;
          setTypingText(activity);
          if (!hasReplyText) {
            updateReply((msg) => ({ ...msg, text: activity }));
          }
          break;
        }
        case "browser":
          updateReply((msg) => ({
            ...msg,
            browserPreview: event.browser_preview,
          }));
          break;
        case "connect_link":
          updateReply((msg) => ({ ...msg, connectCta: event.connect_link }));
          break;
        case "final":
          isFinished = true;
          updateReply(() => toUiMessage(event.message));
          break;
        case "error":
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

      console.error("Error sending message:", error);
      // Includes the daily prompt limit: the server's message says what to do.
      const errorMessage = getErrorMessage(error, "Failed to send message");
      if (!isStored) {
        // The server refused the message before storing it: take both bubbles back and
        // return the text and files to the input, so nothing unsaved looks sent.
        setMessages((prev) =>
          prev.filter(
            (msg) => msg.id !== userMessageId && msg.id !== agentMessageId,
          ),
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

  /** Forget a memory saved from a message: it is marked wrong and never used. */
  const handleUndoMemory = async (messageId: string, memory: SavedMemory) => {
    try {
      await changeMemoryStatus(memory.memory_id, "retract");
      updateMessage(messageId, (msg) => ({
        ...msg,
        savedMemories: msg.savedMemories?.filter(
          (item) => item.memory_id !== memory.memory_id,
        ),
      }));
      showToast(`${profile.name} won't use that.`);
    } catch (error) {
      showToast(getErrorMessage(error, "Could not undo"));
    }
  };

  /** Keep a PDF sent in this message in My files, for the assistant to read later. */
  const handleSaveToFiles = async (messageId: string, index: number) => {
    const file = messages.find((msg) => msg.id === messageId)?.attachments?.[index];
    if (!file?.data) return;
    try {
      const document = await uploadDocument({
        name: file.name,
        media_type: PDF_TYPE,
        data: file.data,
      });
      updateMessage(messageId, (msg) => ({
        ...msg,
        attachments: msg.attachments?.map((item, position) =>
          position === index ? { ...item, data: undefined, savedToFiles: true } : item,
        ),
      }));
      showToast(
        document.is_resume ? "Saved to My files as your resume" : "Saved to My files",
      );
    } catch (error) {
      showToast(getErrorMessage(error, "Could not save the file"), 4000);
    }
  };

  const handleOpenConnectLink = async (
    connectUrl: string,
    toolName: string,
  ) => {
    try {
      showToast(`Opening ${toolName} connection...`);
      if (Platform.OS === "web") {
        window.open(connectUrl, "_blank");
      } else {
        await WebBrowser.openAuthSessionAsync(connectUrl);
      }
    } catch (error) {
      showToast(
        getErrorMessage(error, `Could not open ${toolName} connection`),
      );
    }
  };

  const handleConfirmSchedule = async (messageId: string) => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!threadId || message?.scheduleProposal?.status !== "pending") return;

    updateMessage(messageId, (msg) => ({
      ...msg,
      scheduleAction: "confirming",
      scheduleError: undefined,
    }));

    try {
      const result = await confirmProposal(threadId, messageId);
      updateMessage(messageId, () => toUiMessage(result.message));
      haptic.success();
      showToast("Schedule created");
    } catch (error) {
      console.error("Failed to create schedule:", error);
      haptic.error();
      const errorMessage = getErrorMessage(error, "Could not create schedule");
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
    if (!threadId || message?.scheduleProposal?.status !== "pending")
      return false;

    updateMessage(messageId, (msg) => ({
      ...msg,
      scheduleAction: "dismissing",
      scheduleError: undefined,
    }));

    try {
      const updated = await dismissProposal(threadId, messageId);
      updateMessage(messageId, () => toUiMessage(updated));
      return true;
    } catch (error) {
      console.error("Failed to dismiss schedule:", error);
      const errorMessage = getErrorMessage(
        error,
        "Could not cancel the schedule",
      );
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

  const handleSendJobDraft = async (messageId: string) => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!threadId || !canSendJobDraft(message)) return;

    updateMessage(messageId, (msg) => ({
      ...msg,
      jobDraftAction: "sending",
      jobDraftError: undefined,
    }));

    try {
      const updated = await sendJobApplicationDraft(threadId, messageId);
      const ui = toUiMessage(updated);
      updateMessage(messageId, (msg) => ({
        ...ui,
        jobDraftError:
          ui.jobApplicationDraft?.status === "failed"
            ? (ui.jobApplicationDraft.error_message ?? undefined)
            : undefined,
      }));
      if (ui.jobApplicationDraft?.status === "sent") {
        haptic.success();
        showToast("Email sent");
      } else if (ui.jobApplicationDraft?.status === "failed") {
        haptic.error();
        showToast(
          ui.jobApplicationDraft.error_message || "Could not send the draft",
        );
      }
    } catch (error) {
      console.error("Failed to send job application draft:", error);
      haptic.error();
      const errorMessage = getErrorMessage(error, "Could not send the draft");
      updateMessage(messageId, (msg) => ({
        ...msg,
        jobDraftAction: undefined,
        jobDraftError: errorMessage,
      }));
      showToast(errorMessage);
    }
  };

  const handleEditSchedule = async (messageId: string) => {
    const message = messages.find((msg) => msg.id === messageId);
    if (!message?.scheduleProposal) return;

    setInputText(message.scheduleProposal.original_prompt);
    if (await dismissSchedule(messageId)) {
      showToast("Edit the request, then send it again.");
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
          keyboardDismissMode={
            Platform.OS === "ios" ? "interactive" : "on-drag"
          }
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          onScroll={handleScroll}
          scrollEventThrottle={32}
          onContentSizeChange={handleContentSizeChange}
        >
          <Pressable
            onPress={Keyboard.dismiss}
            accessible={false}
            style={styles.scrollInner}
          >
            {/* Older messages, a page at a time */}
            {hasEarlier && visibleMessages.length > 0 ? (
              <Button
                title="Load earlier messages"
                variant="plain"
                size="small"
                loading={isLoadingEarlier}
                onPress={handleLoadEarlier}
                containerStyle={styles.loadEarlier}
              />
            ) : null}

            {/* The day, as a caption above the thread */}
            <AppText
              variant="caption1"
              color="secondary"
              weight="600"
              align="center"
              style={styles.dateLabel}
            >
              Today
            </AppText>

            {/* Messages */}
            {visibleMessages.map((msg, index) => {
              const isUser = msg.sender === "user";
              const savable = isUser
                ? (msg.attachments ?? [])
                    .map((file, fileIndex) => ({ file, index: fileIndex }))
                    .filter(({ file }) => file.data || file.savedToFiles)
                : [];
              const hasCards = !isUser && hasMessageCards(msg);
              // A reply that is only a card shows no empty bubble above it.
              const showBubble =
                Boolean(msg.text || msg.attachments?.length) || !hasCards;
              const previous = index > 0 ? visibleMessages[index - 1] : null;
              const bubbleTextColor = isUser
                ? Colors.chatBubbleUserText
                : Colors.label;
              return (
                <View
                  key={msg.id}
                  style={[
                    styles.message,
                    isUser ? styles.userMessage : styles.agentMessage,
                    previous &&
                      (previous.sender === msg.sender
                        ? styles.messageSameSender
                        : styles.messageNewSender),
                  ]}
                >
                  {showBubble ? (
                    <PressableScale
                      onPress={() => showToast(msg.text)}
                      pressedScale={0.98}
                      hitSlop={0}
                      unstable_pressDelay={BUBBLE_PRESS_DELAY}
                      containerStyle={styles.bubbleTouch}
                      style={[
                        styles.bubble,
                        isUser ? styles.userBubble : styles.agentBubble,
                      ]}
                    >
                      {isUser ? (
                        msg.text ? (
                          <AppText color={Colors.chatBubbleUserText}>
                            {msg.text}
                          </AppText>
                        ) : null
                      ) : (
                        <MarkdownText text={msg.text} />
                      )}

                      {msg.attachments?.length ? (
                        <View
                          style={[
                            styles.bubbleFiles,
                            !msg.text && styles.bubbleFilesOnly,
                          ]}
                        >
                          {msg.attachments.map((file, fileIndex) => (
                            <View
                              key={`${file.name}-${fileIndex}`}
                              style={styles.bubbleFile}
                            >
                              <HugeiconsIcon
                                icon={Attachment01Icon}
                                size={14}
                                color={bubbleTextColor}
                                strokeWidth={2}
                              />
                              <AppText
                                variant="subheadline"
                                color={bubbleTextColor}
                                numberOfLines={1}
                                style={styles.flexShrink}
                              >
                                {file.name}
                              </AppText>
                            </View>
                          ))}
                        </View>
                      ) : null}
                    </PressableScale>
                  ) : null}

                  {hasCards ? (
                    <View
                      style={[
                        styles.cards,
                        showBubble && styles.cardsBelowBubble,
                      ]}
                    >
                      {msg.connectCta ? (
                        <ConnectCard
                          cta={msg.connectCta}
                          onConnect={handleOpenConnectLink}
                        />
                      ) : null}

                      {msg.browserPreview ? (
                        <ChatBrowserPreview
                          browserPreview={msg.browserPreview}
                        />
                      ) : null}

                      {msg.reminder ? (
                        <ReminderCard note={msg.reminder} />
                      ) : null}

                      {msg.brief && msg.brief.follow_ups.length ? (
                        <BriefCard note={msg.brief} />
                      ) : null}

                      {msg.scheduleProposal ? (
                        <ScheduleProposalCard
                          msg={msg}
                          proposal={msg.scheduleProposal}
                          onConfirm={() => handleConfirmSchedule(msg.id)}
                          onEdit={() => handleEditSchedule(msg.id)}
                          onCancel={() => handleCancelSchedule(msg.id)}
                        />
                      ) : null}

                      {msg.jobApplicationDraft ? (
                        <JobDraftCard
                          msg={msg}
                          draft={msg.jobApplicationDraft}
                          onSend={() => handleSendJobDraft(msg.id)}
                        />
                      ) : null}
                    </View>
                  ) : null}

                  {isUser && (msg.savedMemories?.length || savable.length) ? (
                    <View style={styles.extrasRow}>
                      {msg.savedMemories?.map((memory) => (
                        <View
                          key={memory.memory_id}
                          style={[styles.extraChip, continuous]}
                        >
                          <HugeiconsIcon
                            icon={Brain01Icon}
                            size={13}
                            color={Colors.secondaryLabel}
                            strokeWidth={2}
                          />
                          <PressableScale
                            onPress={() =>
                              router.push({
                                pathname: "/memories/[id]",
                                params: { id: memory.memory_id },
                              })
                            }
                            accessibilityRole="button"
                            accessibilityHint="Opens the memory"
                            containerStyle={styles.flexShrink}
                          >
                            <AppText
                              variant="footnote"
                              color="secondary"
                              numberOfLines={1}
                            >
                              {memory.status === "active" ? "Remembered" : "To review"}:{" "}
                              {memory.title}
                            </AppText>
                          </PressableScale>
                          <PressableScale
                            onPress={() => void handleUndoMemory(msg.id, memory)}
                            hitSlop={{ top: 8, bottom: 8, left: 6, right: 8 }}
                            accessibilityRole="button"
                            accessibilityLabel={`Forget ${memory.title}`}
                          >
                            <AppText variant="footnote" color="tint" weight="600">
                              Undo
                            </AppText>
                          </PressableScale>
                        </View>
                      ))}
                      {savable.map(({ file, index: fileIndex }) =>
                        file.savedToFiles ? (
                          <View
                            key={`save-${file.name}-${fileIndex}`}
                            style={[styles.extraChip, continuous]}
                          >
                            <HugeiconsIcon
                              icon={Tick02Icon}
                              size={13}
                              color={Colors.systemGreen}
                              strokeWidth={2.2}
                            />
                            <AppText
                              variant="footnote"
                              color="secondary"
                              numberOfLines={1}
                              style={styles.flexShrink}
                            >
                              In My files
                            </AppText>
                          </View>
                        ) : (
                          <PressableScale
                            key={`save-${file.name}-${fileIndex}`}
                            onPress={() =>
                              void handleSaveToFiles(msg.id, fileIndex)
                            }
                            accessibilityRole="button"
                            containerStyle={styles.extraChipTouch}
                            style={[styles.extraChip, continuous]}
                          >
                            <HugeiconsIcon
                              icon={File01Icon}
                              size={13}
                              color={Colors.tint}
                              strokeWidth={2}
                            />
                            <AppText
                              variant="footnote"
                              color="tint"
                              weight="600"
                              numberOfLines={1}
                              style={styles.flexShrink}
                            >
                              {`Save ${file.name} to My files`}
                            </AppText>
                          </PressableScale>
                        ),
                      )}
                    </View>
                  ) : null}
                </View>
              );
            })}

            {isSending ? (
              <View style={styles.typingRow}>
                <ActivityIndicator
                  size="small"
                  color={Colors.secondaryLabel}
                />
                <AppText variant="footnote" color="secondary">
                  {typingText}
                </AppText>
              </View>
            ) : null}
          </Pressable>
          {/* As tall as the keyboard reaches over the list, so every message can be
                scrolled above the input while the keyboard is open. */}
          <Animated.View style={keyboardSpacerStyle} />
        </Animated.ScrollView>

        {/* Composer, carried on top of the keyboard */}
        <Animated.View style={[styles.composer, keyboardInputStyle]}>
          <AttachmentChips
            attachments={attachments}
            onRemove={handleRemoveAttachment}
          />

          <LayoutAnimationConfig skipEntering>
            <View style={styles.composerRow}>
              {/* Attach images or PDFs */}
              <ComposerButton
                icon={Add01Icon}
                tone="fill"
                size={34}
                onPress={handleAttachPress}
                loading={isPicking}
                accessibilityLabel="Attach images or PDFs"
              />

              {/* The text field, with the microphone or the send button inside it */}
              <View style={[styles.field, continuous]}>
                <TextInput
                  style={styles.textInput}
                  value={inputText}
                  onChangeText={setInputText}
                  placeholder={
                    voice.isListening
                      ? "Listening..."
                      : `Ask ${profile.name} to read emails, send Slack msgs, or schedule meetings...`
                  }
                  placeholderTextColor={Colors.placeholder}
                  selectionColor={Colors.tint}
                  returnKeyType="send"
                  onSubmitEditing={handleSend}
                />

                {showSendButton ? (
                  <Animated.View key="send" entering={composerActionEntering}>
                    <ComposerButton
                      icon={ArrowUp02Icon}
                      tone="send"
                      size={30}
                      onPress={handleSend}
                      accessibilityLabel="Send message"
                    />
                  </Animated.View>
                ) : (
                  <Animated.View key="mic" entering={composerActionEntering}>
                    <ComposerButton
                      icon={Mic01Icon}
                      tone={voice.isListening ? "active" : "plain"}
                      size={30}
                      onPress={handleMicPress}
                      accessibilityLabel={
                        voice.isListening ? "Stop voice input" : "Voice input"
                      }
                      accessibilityState={{ selected: voice.isListening }}
                    />
                  </Animated.View>
                )}
              </View>
            </View>
          </LayoutAnimationConfig>
        </Animated.View>
      </View>
    </Animated.View>
  );
}

// --- Composer ---------------------------------------------------------------------------

type ComposerTone = "fill" | "plain" | "send" | "active";

const COMPOSER_TONES: Record<
  ComposerTone,
  { background: string; glyph: string; strokeWidth: number }
> = {
  // The attach button: a glyph on a light fill beside the field.
  fill: {
    background: Colors.tertiaryFill,
    glyph: Colors.secondaryLabel,
    strokeWidth: 2.2,
  },
  // The microphone inside the field.
  plain: {
    background: "transparent",
    glyph: Colors.secondaryLabel,
    strokeWidth: 2,
  },
  // The send button: white up-arrow on the tint, as in Messages.
  send: { background: Colors.tint, glyph: Colors.white, strokeWidth: 2.5 },
  // The microphone while listening.
  active: { background: Colors.tint, glyph: Colors.white, strokeWidth: 2 },
};

/**
 * A round glyph button in the composer. `IconButton` has neither a loading state nor
 * `accessibilityState`, which the attach and microphone buttons need, so this one is
 * built on `PressableScale` the same way (44 pt touch target whatever its size).
 */
function ComposerButton({
  icon,
  tone,
  size,
  onPress,
  loading = false,
  accessibilityLabel,
  accessibilityState,
}: {
  icon: IconSvgElement;
  tone: ComposerTone;
  size: number;
  onPress: () => void;
  loading?: boolean;
  accessibilityLabel: string;
  accessibilityState?: AccessibilityState;
}) {
  const palette = COMPOSER_TONES[tone];
  const slop = Math.max(0, (44 - size) / 2);
  return (
    <PressableScale
      onPress={loading ? undefined : onPress}
      hitSlop={{ top: slop, bottom: slop, left: slop, right: slop }}
      pressedScale={0.92}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ ...accessibilityState, busy: loading }}
      style={[
        styles.composerButton,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: palette.background,
        },
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={palette.glyph} />
      ) : (
        <HugeiconsIcon
          icon={icon}
          size={Math.round(size * 0.6)}
          color={palette.glyph}
          strokeWidth={palette.strokeWidth}
        />
      )}
    </PressableScale>
  );
}

// --- Cards under the assistant's messages -----------------------------------------------

type ConnectCta = NonNullable<ChatMessage["connectCta"]>;
type ScheduleProposal = NonNullable<ChatMessage["scheduleProposal"]>;
type JobDraft = NonNullable<ChatMessage["jobApplicationDraft"]>;

function hasMessageCards(msg: ChatMessage) {
  return Boolean(
    msg.connectCta ||
      msg.browserPreview ||
      msg.reminder ||
      msg.brief?.follow_ups.length ||
      msg.scheduleProposal ||
      msg.jobApplicationDraft,
  );
}

function ConnectCard({
  cta,
  onConnect,
}: {
  cta: ConnectCta;
  onConnect: (connectUrl: string, toolName: string) => void;
}) {
  return (
    <Card style={[styles.card, styles.connectCard]}>
      <View style={[styles.connectIcon, continuous]}>
        <HugeiconsIcon
          icon={Link02Icon}
          size={20}
          color={Colors.tint}
          strokeWidth={2}
        />
      </View>
      <View style={styles.connectBody}>
        <AppText variant="subheadline" weight="600">
          Connect {cta.tool_name}
        </AppText>
        <AppText variant="footnote" color="secondary">
          Complete authorization, then send done.
        </AppText>
      </View>
      <Button
        title="Connect"
        size="small"
        onPress={() => onConnect(cta.connect_url, cta.tool_name)}
      />
    </Card>
  );
}

function ScheduleProposalCard({
  msg,
  proposal,
  onConfirm,
  onEdit,
  onCancel,
}: {
  msg: ChatMessage;
  proposal: ScheduleProposal;
  onConfirm: () => void;
  onEdit: () => void;
  onCancel: () => void;
}) {
  const canAct = canActOnProposal(msg);
  const isConfirming = msg.scheduleAction === "confirming";
  return (
    <Card style={styles.card}>
      <AppText variant="headline">Schedule this task?</AppText>
      <View>
        <DetailRow label="Task" value={proposal.title} first />
        <DetailRow
          label="When"
          value={`${formatScheduleRule(proposal)} (${formatTimezone(
            proposal.timezone,
          )})`}
        />
        <DetailRow label="Does" value={proposal.task} numberOfLines={4} />
        <DetailRow
          label="Delivery"
          value={`${formatDeliveryLabel(proposal.delivery)}${
            proposal.delivery_target ? ` · ${proposal.delivery_target}` : ""
          }`}
        />
      </View>
      <AppText variant="footnote" color="secondary">
        {proposal.summary}
      </AppText>

      {msg.scheduleError ? (
        <AppText variant="footnote" color="destructive">
          {msg.scheduleError}
        </AppText>
      ) : null}

      {proposal.status === "confirmed" ? (
        <StatusLine label="Confirmed" done />
      ) : proposal.status === "dismissed" ? (
        <StatusLine label="Cancelled" />
      ) : (
        <View style={styles.cardActions}>
          <Button
            title={isConfirming ? "Saving..." : "Confirm"}
            size="small"
            loading={isConfirming}
            disabled={!canAct && !isConfirming}
            onPress={onConfirm}
          />
          <Button
            title="Edit"
            variant="tinted"
            size="small"
            disabled={!canAct}
            onPress={onEdit}
          />
          <Button
            title="Cancel"
            variant="tinted"
            size="small"
            disabled={!canAct}
            onPress={onCancel}
          />
        </View>
      )}
    </Card>
  );
}

function JobDraftCard({
  msg,
  draft,
  onSend,
}: {
  msg: ChatMessage;
  draft: JobDraft;
  onSend: () => void;
}) {
  const isSending = msg.jobDraftAction === "sending";
  const postUrl = draft.linkedin_post_url?.trim();
  const files = draft.attachments ?? [];
  return (
    <Card style={styles.card}>
      <AppText variant="headline">Job Application Draft</AppText>
      <View>
        <DetailRow
          label="To"
          value={draft.recipient_email}
          numberOfLines={1}
          first
        />
        <DetailRow label="Subject" value={draft.subject} numberOfLines={2} />
        {draft.company ? (
          <DetailRow label="Company" value={draft.company} numberOfLines={1} />
        ) : null}
        {draft.role_title ? (
          <DetailRow label="Role" value={draft.role_title} numberOfLines={1} />
        ) : null}
        <View style={styles.draftBody}>
          <AppText variant="subheadline" numberOfLines={6}>
            {draft.body}
          </AppText>
        </View>
      </View>

      {files.length > 0 ? (
        <View style={styles.draftFiles}>
          {files.map((file, index) => (
            <DraftFileRow key={`${file.document_id}-${index}`} file={file} />
          ))}
        </View>
      ) : null}

      {postUrl ? (
        <View style={styles.postRow}>
          <HugeiconsIcon
            icon={Link02Icon}
            size={14}
            color={Colors.secondaryLabel}
            strokeWidth={2}
          />
          <AppText
            variant="footnote"
            color="secondary"
            numberOfLines={1}
            style={styles.flexShrink}
          >
            From post: {postUrl}
          </AppText>
        </View>
      ) : null}

      {msg.jobDraftError ? (
        <AppText variant="footnote" color="destructive">
          {msg.jobDraftError}
        </AppText>
      ) : null}

      {draft.status === "sent" ? (
        <StatusLine label="Sent" done />
      ) : (
        <View style={styles.cardActions}>
          <Button
            title={
              isSending
                ? "Sending..."
                : draft.status === "failed"
                  ? "Send Again"
                  : "Send"
            }
            size="small"
            loading={isSending}
            disabled={!isSending && !canSendJobDraft(msg)}
            onPress={onSend}
          />
        </View>
      )}
    </Card>
  );
}

/** A file the draft sends with the email: its name and size, on a white row. */
function DraftFileRow({ file }: { file: DraftAttachment }) {
  const name = file.file_name || file.title;
  const size = file.size_bytes > 0 ? formatFileSize(file.size_bytes) : null;
  return (
    <View
      style={[styles.draftFile, continuous]}
      accessible
      accessibilityLabel={size ? `${name}, ${size}` : name}
    >
      <HugeiconsIcon
        icon={File01Icon}
        size={18}
        color={Colors.tint}
        strokeWidth={2}
      />
      <AppText variant="subheadline" numberOfLines={1} style={styles.flexFill}>
        {name}
      </AppText>
      {size ? (
        <AppText variant="footnote" color="secondary">
          {size}
        </AppText>
      ) : null}
    </View>
  );
}

/** A label and its value on one line of a card, below a hairline unless it is first. */
function DetailRow({
  label,
  value,
  numberOfLines,
  first = false,
}: {
  label: string;
  value: string;
  numberOfLines?: number;
  first?: boolean;
}) {
  return (
    <View style={[styles.detailRow, !first && styles.detailRowDivided]}>
      <AppText variant="subheadline" color="secondary" style={styles.detailLabel}>
        {label}
      </AppText>
      <AppText
        variant="subheadline"
        numberOfLines={numberOfLines}
        style={styles.flexFill}
      >
        {value}
      </AppText>
    </View>
  );
}

/** Where a card's request ended up, in place of its buttons. */
function StatusLine({ label, done = false }: { label: string; done?: boolean }) {
  return (
    <View style={styles.statusLine}>
      {done ? (
        <HugeiconsIcon
          icon={Tick02Icon}
          size={16}
          color={Colors.systemGreen}
          strokeWidth={2.2}
        />
      ) : null}
      <AppText
        variant="subheadline"
        weight="600"
        color={done ? "success" : "secondary"}
      >
        {label}
      </AppText>
    </View>
  );
}

/** The thread in the route (falling back to the main thread when it is gone), or main. */
async function resolveThread(
  routeThreadId: string | null,
  signal: AbortSignal,
): Promise<Thread> {
  if (routeThreadId) {
    try {
      return await getThread(routeThreadId, signal);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        throw error;
      }
      showToast("That chat no longer exists. Opening the main chat.");
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
function withNewerMessages(
  shown: ChatMessage[],
  latest: ChatMessage[],
): ChatMessage[] {
  const shownIds = new Set(shown.map((msg) => msg.id));
  const added = latest.filter((msg) => !shownIds.has(msg.id));
  // What was remembered from a message arrives once the chat has been quiet for a few
  // minutes, so a refresh brings it to messages already shown as well.
  const fresh = new Map(latest.map((msg) => [msg.id, msg]));
  let remembered = false;
  const refreshed = shown.map((msg) => {
    const update = fresh.get(msg.id);
    if (!update || savedKey(update) === savedKey(msg)) return msg;
    remembered = true;
    return { ...msg, savedMemories: update.savedMemories };
  });
  if (added.length === 0) return remembered ? refreshed : shown;
  return [...refreshed.filter(isStoredMessage), ...added];
}

function savedKey(msg: ChatMessage): string {
  return (msg.savedMemories ?? [])
    .map((memory) => `${memory.memory_id}:${memory.status}`)
    .join(",");
}

/**
 * The stored version of a message just sent, keeping the bytes of the PDFs it carried:
 * the server keeps only their names, and they can still be saved to My files.
 */
function withLocalFiles(stored: ChatMessage, local: ChatMessage): ChatMessage {
  if (!stored.attachments || !local.attachments) return stored;
  return {
    ...stored,
    attachments: stored.attachments.map((file, index) => {
      const sent = local.attachments?.[index];
      return sent?.data && sent.name === file.name ? { ...file, data: sent.data } : file;
    }),
  };
}

function formatDeliveryLabel(delivery?: string | null) {
  return (
    (delivery || "chat")
      .split(/[_-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ") || "Chat"
  );
}

/** The schedule card's buttons work only on a stored, pending proposal with no request in flight. */
function canActOnProposal(msg: ChatMessage) {
  return (
    msg.scheduleProposal?.status === "pending" &&
    !msg.scheduleAction &&
    !msg.pending
  );
}

function canSendJobDraft(msg?: ChatMessage) {
  if (!msg?.jobApplicationDraft) return false;
  return (
    (msg.jobApplicationDraft.status === "pending" ||
      msg.jobApplicationDraft.status === "failed") &&
    msg.jobDraftAction !== "sending" &&
    !msg.pending
  );
}

/** IANA timezone of the device, sent with each message for times and schedules. */
function getDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// Messages: iMessage's 18 pt bubbles, tight within a sender's run, apart between senders.
const BUBBLE_RADIUS = 18;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.systemBackground,
  },
  content: {
    flex: 1,
    justifyContent: "space-between",
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: ScreenMargin,
    paddingTop: 8,
    paddingBottom: 12,
    flexGrow: 1,
  },
  scrollInner: {
    flexGrow: 1,
  },
  loadEarlier: {
    alignSelf: "center",
    marginTop: 2,
  },
  dateLabel: {
    marginTop: 6,
    marginBottom: 12,
  },
  flexShrink: {
    flexShrink: 1,
  },
  flexFill: {
    flex: 1,
  },

  // --- Messages
  message: {
    width: "100%",
  },
  userMessage: {
    alignItems: "flex-end",
  },
  agentMessage: {
    alignItems: "flex-start",
  },
  messageSameSender: {
    marginTop: 4,
  },
  messageNewSender: {
    marginTop: 14,
  },
  bubbleTouch: {
    maxWidth: "80%",
  },
  bubble: {
    ...continuous,
    borderRadius: BUBBLE_RADIUS,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  userBubble: {
    backgroundColor: Colors.chatBubbleUser,
  },
  agentBubble: {
    backgroundColor: Colors.chatBubbleAi,
    // Markdown paragraphs bring 2 pt above and below.
    paddingVertical: 6,
  },
  bubbleFiles: {
    marginTop: 6,
    gap: 4,
  },
  bubbleFilesOnly: {
    marginTop: 0,
  },
  bubbleFile: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  typingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 12,
  },

  // What was remembered from a user's message, and saving its PDF, under the bubble.
  extrasRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: 6,
    marginTop: 6,
    paddingLeft: 48,
  },
  extraChipTouch: {
    maxWidth: "100%",
  },
  extraChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    maxWidth: "100%",
    minHeight: 28,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Radius.pill,
    backgroundColor: Colors.groupedBackground,
  },

  // --- Cards under the assistant's messages
  cards: {
    width: "88%",
    gap: 8,
  },
  cardsBelowBubble: {
    marginTop: 6,
  },
  card: {
    backgroundColor: Colors.groupedBackground,
    gap: 10,
  },
  cardActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 2,
  },
  detailRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    paddingVertical: 8,
  },
  detailRowDivided: {
    borderTopWidth: Hairline,
    borderTopColor: Colors.separator,
  },
  detailLabel: {
    width: 68,
  },
  draftBody: {
    paddingTop: 10,
    paddingBottom: 2,
    borderTopWidth: Hairline,
    borderTopColor: Colors.separator,
  },
  draftFiles: {
    gap: 6,
  },
  draftFile: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: Radius.md,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  postRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  statusLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 32,
  },
  connectCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
  },
  connectIcon: {
    width: 36,
    height: 36,
    borderRadius: Radius.sm,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.tintFill,
  },
  connectBody: {
    flex: 1,
    gap: 2,
  },

  // --- Composer
  composer: {
    paddingHorizontal: 12,
    paddingTop: 6,
    paddingBottom: Platform.OS === "ios" ? 10 : 8,
    backgroundColor: Colors.systemBackground,
  },
  composerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  composerButton: {
    alignItems: "center",
    justifyContent: "center",
  },
  field: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    minHeight: 36,
    paddingLeft: 14,
    paddingRight: 3,
    borderRadius: 18,
    borderWidth: Hairline,
    borderColor: Colors.separator,
    backgroundColor: Colors.systemBackground,
  },
  textInput: {
    flex: 1,
    marginRight: 6,
    paddingHorizontal: 0,
    paddingVertical: Platform.OS === "ios" ? 7 : 5,
    fontSize: Typography.body.fontSize,
    letterSpacing: Typography.body.letterSpacing,
    color: Colors.label,
  },
});
