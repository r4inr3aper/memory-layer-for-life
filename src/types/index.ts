/**
 * Zoop - Core Type Definitions & Data Contracts
 *
 * Centralized TypeScript interfaces and types for application state,
 * navigation, companion chat, scheduler tasks, ideas, and settings.
 */

import type {
    ChatMessage as ApiChatMessage,
    BriefNote,
    BrowserPreview,
    ConnectLink,
    JobApplicationDraft,
    ReminderNote,
    SavedMemory,
    ScheduleProposal,
    ScheduledRunNote,
} from "@/lib/api/types";

/** Live cloud browser card shown under an agent message. */
export type ChatBrowserPreviewData = BrowserPreview;

/** "Connect {app}" card shown under an agent message. */
export type ChatConnectCta = ConnectLink;

/** Schedule proposal card shown under an agent message. */
export type ChatScheduleProposal = ScheduleProposal;
export type ChatJobApplicationDraft = JobApplicationDraft;

/** A file sent with a user message, listed in its bubble by name. */
export interface ChatAttachment {
  name: string;
  mediaType: string;
  /** Unknown for an optimistic bubble whose file was read on the device. */
  sizeBytes?: number;
  /**
   * Base64 of a file sent from this device in this session, so it can still be saved to
   * My files. Never stored: after a reload only the name is known.
   */
  data?: string;
  /** Saved to My files from this bubble (transient UI state). */
  savedToFiles?: boolean;
}

/**
 * Message object representing a chat utterance in the conversation history.
 */
export interface ChatMessage {
  /** Unique identifier for the message (a local id until the server has stored it) */
  id: string;
  /** Origin of the message: 'user' for current user, 'agent' for Cooper AI, or 'system' */
  sender: "user" | "agent" | "system";
  /** Plaintext or markdown formatted message content */
  text: string;
  /** Formatted timestamp display string (e.g. "3:35 PM") */
  timestamp: string;

  browserPreview?: ChatBrowserPreviewData;
  connectCta?: ChatConnectCta;
  scheduleProposal?: ChatScheduleProposal;
  jobApplicationDraft?: ChatJobApplicationDraft;
  /** Set on a message that delivered the result of a scheduled run */
  scheduledRun?: ScheduledRunNote;
  /** Set on a reminder the user set: the card offers Done and Snooze */
  reminder?: ReminderNote;
  /** Set on a daily brief: the card asks about yesterday's items */
  brief?: BriefNote;
  /** Files sent with a user message */
  attachments?: ChatAttachment[];
  /** On a user message: what was remembered from it, with Undo */
  savedMemories?: SavedMemory[];
  /** Schedule proposal request in flight (transient UI state, never stored) */
  scheduleAction?: "confirming" | "dismissing";
  /** Last schedule proposal request failure (transient UI state, never stored) */
  scheduleError?: string;
  /** Job-draft send request in flight (transient UI state, never stored) */
  jobDraftAction?: "sending";
  /** Last job-draft send failure (transient UI state, never stored) */
  jobDraftError?: string;

  /** Optimistic bubble the server has not stored yet */
  pending?: boolean;
  /** Agent reply that is still streaming in */
  streaming?: boolean;
}

/**
 * Maps a stored message from the API to the chat UI message.
 */
export function toUiMessage(message: ApiChatMessage): ChatMessage {
  const metadata = message.metadata ?? {};
  return {
    id: message.id,
    sender: message.role === "user" ? "user" : "agent",
    text: message.content,
    timestamp: formatMessageTime(message.created_at),
    browserPreview: metadata.browser_preview ?? undefined,
    connectCta: metadata.connect_link ?? undefined,
    jobApplicationDraft: metadata.job_application_draft ?? undefined,
    scheduleProposal: metadata.schedule_proposal ?? undefined,
    scheduledRun: metadata.scheduled_run ?? undefined,
    reminder: metadata.reminder ?? undefined,
    brief: metadata.brief ?? undefined,
    attachments: metadata.attachments?.length
      ? metadata.attachments.map((attachment) => ({
          name: attachment.name,
          mediaType: attachment.media_type,
          sizeBytes: attachment.size_bytes,
        }))
      : undefined,
    savedMemories: message.saved_memories?.length ? message.saved_memories : undefined,
  };
}

/**
 * Chat bubble timestamp, e.g. "03:35 PM".
 */
export function formatMessageTime(value: string | Date = new Date()): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Chat topic item listed under "Side chats" in the sliding sidebar drawer.
 */
export interface SideChatItem {
  /** Unique identifier for the side chat thread */
  id: string;
  /** Title or subject of the side chat */
  title: string;
  /** Indicates whether unread updates exist in this side thread */
  hasUnreadDot?: boolean;
}

/**
 * Inspiration card template for the Ideas tab.
 */
export interface IdeaItem {
  /** Unique idea identifier */
  id: string;
  /** 3D emoji or icon representing the domain */
  icon: string;
  /** Prominent bold action title */
  title: string;
  /** Descriptive preview of what Cooper will build or research */
  description: string;
  /** Full prompt automatically loaded into chat input upon selection */
  prompt: string;
}

/**
 * Status of scheduled goals or routines.
 */
export type TaskStatus = "active" | "paused" | "done";

/**
 * Scheduled goal or recurring autonomous workflow tracked in Tasks tab.
 */
export interface TaskGoalItem {
  /** Unique task identifier */
  id: string;
  /** Name of the goal or routine check */
  title: string;
  /** Frequency and time specification (e.g. "Every day @ 8:00 AM") */
  schedule: string;
  /** Current operating status */
  status: TaskStatus;
  /** Lifetime count of automated runs completed */
  runsCount: number;
}

/**
 * External workspace tool connector available in Settings.
 */
export interface ConnectorItem {
  /** Unique connector identifier */
  id: string;
  /** Tool brand name (e.g. "Google Workspace", "Notion") */
  name: string;
  /** Description of features enabled by connecting */
  description: string;
  /** Distinct brand background color for connector icon emblem */
  iconBg: string;
  /** Connection status */
  connected: boolean;
  /** Category grouping (e.g. "Productivity", "Developer", "Workspace") */
  category: string;
  /** Linked account identifier or email when active */
  accountEmail?: string;
}

/**
 * Agent Mascot Customization parameters (saved on the backend; see AgentProfileContext)
 */
export interface AgentProfile {
  name: string;
  subtitle: string;
  /** Avatar icon key from `AGENT_ICONS` (e.g. 'cooper', 'robot'), never an emoji */
  icon: string;
  /** `#RRGGBB` */
  color: string;
}

/**
 * Valid navigation tab identifiers
 */
export type TabKey = "chat" | "feed" | "ideas" | "tasks" | "settings";

/**
 * Tab dock destination item specification
 */
export interface TabItem {
  key: TabKey;
  label: string;
  route: string;
  icon: any;
}

export * from "./tools";

