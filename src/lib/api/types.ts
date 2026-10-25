/**
 * Backend API Wire Types
 *
 * Request and response shapes of the backend API (`/api/v1`), exactly as they travel:
 * snake_case keys and ISO 8601 datetime strings.
 */

// --- Shared ----------------------------------------------------------------------------

/** One page of a collection. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Offset pagination accepted by collection endpoints (`limit` is 1..200, default 50). */
export interface PageParams {
  limit?: number;
  offset?: number;
}

/** Body of every non-2xx JSON response. */
export interface ApiErrorBody {
  error_code: string;
  message: string;
  detail: string | null;
}

// --- User ------------------------------------------------------------------------------

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  /** `null` means the default name, Cooper. */
  assistant_name: string | null;
  assistant_subtitle: string | null;
  /** An icon key chosen in the agent editor. */
  assistant_icon: string | null;
  /** `#RRGGBB`. */
  assistant_color: string | null;
  notifications_enabled: boolean;
  /** Whether the user's chat messages become memories. */
  memory_capture_enabled: boolean;
  /** IANA timezone the app last reported; briefs and due dates use it. */
  timezone: string | null;
  /** A daily brief in chat at `brief_time` (HH:MM, local). */
  brief_enabled: boolean;
  brief_time: string;
  /** Push for reminders the user set. */
  reminders_enabled: boolean;
  /** HH:MM; no brief push between them. The end may be earlier than the start. */
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  created_at: string;
}

/** Only the fields sent change. A text field sent as `null` or `""` returns to the default. */
export interface UpdateMeBody {
  assistant_name?: string | null;
  assistant_subtitle?: string | null;
  assistant_icon?: string | null;
  assistant_color?: string | null;
  notifications_enabled?: boolean;
  memory_capture_enabled?: boolean;
  timezone?: string;
  brief_enabled?: boolean;
  brief_time?: string;
  reminders_enabled?: boolean;
  /** Send both, or both as `null`. */
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
}

/**
 * Today's prompts. A prompt is a chat message sent or a scheduled run; the day is the UTC
 * calendar day, so it resets at `resets_at` (UTC midnight). Tokens and cost are today's.
 */
export interface Usage {
  /** The UTC day counted, YYYY-MM-DD. */
  day: string;
  resets_at: string;
  prompts_used: number;
  /** `null` when there is no limit. */
  prompt_limit: number | null;
  prompts_remaining: number | null;
  chat_messages: number;
  scheduled_runs: number;
  input_tokens: number;
  output_tokens: number;
  /** Decimal as a string, e.g. "0.012345"; `null` when the price is unknown. */
  estimated_cost_usd: string | null;
  /** ISO 4217 code of `estimated_cost`, e.g. "INR". */
  currency: string;
  /** `estimated_cost_usd` in `currency`, at the backend's fixed rate. */
  estimated_cost: string | null;
}

/**
 * `proposed`: saved from chat, not yet reviewed. `active`: accepted or written by the user.
 * `superseded`: replaced by a newer version or merged into another memory. `retracted`:
 * marked as wrong (kept as history, never used).
 */
export type MemoryStatus = 'proposed' | 'active' | 'superseded' | 'retracted';

/**
 * A memory from the user's chats or written by them. `memory_type` is e.g. "semantic_fact"
 * or "preference".
 */
export interface MemoryItem {
  id: string;
  memory_type: string;
  content: string;
  normalized_content: string | null;
  status: MemoryStatus;
  confidence: number | null;
  valid_from: string | null;
  valid_until: string | null;
  observed_at: string | null;
  supersedes_memory_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Who wrote the text: the memory pipeline, or the user (by hand or by correcting). */
  created_by: 'pipeline' | 'user';
  /** Health, feelings, or other private matters: shown here, never given to Cooper. */
  sensitive: boolean;
  /** Whether what it describes is open, planned, or done. */
  state: 'not_applicable' | 'open' | 'planned' | 'done' | null;
  /** YYYY-MM-DD: when a to-do is due. */
  due_on: string | null;
  /** When the user is reminded; cleared once sent. */
  remind_at: string | null;
  closed_at: string | null;
  close_reason: 'done' | 'dropped' | null;
}

/** What is open in the user's life now; each list soonest due first. */
export interface LifeOverview {
  /** The user's local date, YYYY-MM-DD. */
  today: string;
  timezone: string;
  overdue: MemoryItem[];
  due_today: MemoryItem[];
  /** Due in the next seven days. */
  upcoming: MemoryItem[];
  later: MemoryItem[];
  /** No due date. */
  someday: MemoryItem[];
  /** Goals and projects. */
  goals: MemoryItem[];
  /** Open items untouched for two weeks. */
  stale_ids: string[];
  reminders: MemoryItem[];
  recently_done: MemoryItem[];
}

export interface BriefPreview {
  /** Markdown, as posted to chat. */
  text: string;
  summary: string;
  follow_ups: { memory_id: string; content: string; due_on: string | null }[];
  nothing_to_say: boolean;
}

export type InsightKind =
  'money' | 'people.top' | 'people.quiet' | 'follow_through' | 'goal.quiet' | 'theme';

/** Something the user's memories show over time, with the memories it rests on. */
export interface Insight {
  /** Names the insight and its period; sent back with feedback. */
  key: string;
  kind: InsightKind;
  title: string;
  body: string;
  memory_ids: string[];
  /** What opening it shows: a person, a memory, the to-do list, or the memories. */
  target: 'person' | 'memory' | 'todo' | 'memories';
  target_id: string | null;
}

export interface ImportParticipant {
  name: string;
  messages: number;
  /** Conversations this person took part in. */
  conversations: number;
}

/** A chat export: `previewed` until started, then `queued` while the pipeline works. */
export interface ChatImport {
  id: string;
  file_name: string;
  status: 'previewed' | 'queued';
  /** Most messages first. */
  participants: ImportParticipant[];
  message_count: number;
  all_conversations: number;
  first_message_at: string | null;
  last_message_at: string | null;
  owner_name: string | null;
  since: string | null;
  /** Conversations queued, once started. */
  unit_count: number | null;
  /** Estimated cost of one extraction in `currency` (a decimal string), or null. */
  cost_per_conversation: string | null;
  currency: string;
  progress: { done: number; failed: number; waiting: number; memories: number } | null;
  created_at: string;
}

export interface StartImportBody {
  me: string;
  since?: string | null;
  only_my_conversations?: boolean;
  max_conversations?: number;
}

export interface FileMemoryResult {
  raw_message_id: string;
  processing_run_id: string;
  /** What was read from the file. */
  text: string;
  /** False when the same file was given before. */
  created: boolean;
}

/** An app that can be a memory source (Google Calendar for now). */
export interface SourceApp {
  app: string;
  connected: boolean;
  enabled: boolean;
  last_synced_at: string | null;
  /** Why the last sync failed, written for people. */
  error: string | null;
}

/** A chat message matching a search. Matches in `snippet` are wrapped in << and >>. */
export interface MessageHit {
  message_id: string;
  thread_id: string;
  thread_title: string;
  thread_kind: 'main' | 'side';
  role: 'user' | 'assistant';
  snippet: string;
  created_at: string;
}

export interface MemoryListParams extends PageParams {
  /** Default: `proposed` and `active`. */
  status?: MemoryStatus[];
  memory_type?: string;
  order?: 'newest' | 'oldest';
}

/** A memory the user writes, or saves from a held-back message. Saved as `active`. */
export interface CreateMemoryBody {
  memory_type?: string;
  content: string;
  sensitive?: boolean;
  /** For a to-do: YYYY-MM-DD. */
  due_on?: string | null;
  /** For a to-do: ISO time with an offset, in the future. */
  remind_at?: string | null;
}

/**
 * Only sent fields change. New `content` makes a new version with its own id. `due_on` and
 * `remind_at` sent as `null` clear them.
 */
export interface UpdateMemoryBody {
  content?: string;
  memory_type?: string;
  sensitive?: boolean;
  due_on?: string | null;
  remind_at?: string | null;
}

/** A message a memory rests on. */
export interface MemorySource {
  raw_message_id: string;
  source_role: 'supporting' | 'contradicting' | 'contextual';
  /** The words of the message the memory rests on. */
  evidence_text: string | null;
  source: string;
  sent_at: string | null;
  content: string;
  /** The chat it was said in, while that chat exists. */
  thread_id: string | null;
}

export interface MemoryEntity {
  entity_id: string;
  entity_type: string;
  canonical_name: string;
  relationship_type: string;
}

export type MemoryEventAction =
  | 'created'
  | 'accepted'
  | 'retracted'
  | 'restored'
  | 'edited'
  | 'corrected'
  | 'superseded'
  | 'merged'
  | 'replaced'
  | 'suggestion_dismissed';

export interface MemoryEvent {
  id: string;
  action: MemoryEventAction;
  details: Record<string, unknown>;
  created_at: string;
}

export interface MemoryVersion {
  id: string;
  content: string;
  created_at: string;
}

export interface MemoryDetail extends MemoryItem {
  sources: MemorySource[];
  entities: MemoryEntity[];
  /** Oldest first. */
  history: MemoryEvent[];
  /** Older versions and memories merged into or replaced by this one, newest first. */
  replaced: MemoryVersion[];
  /** When superseded: the memory that replaced this one. */
  replaced_by_id: string | null;
}

export type SuggestionKind = 'duplicate' | 'conflict';

/** Two memories that look like duplicates or like they conflict. `first` is the older. */
export interface MemorySuggestion {
  kind: SuggestionKind;
  first: MemoryItem;
  second: MemoryItem;
  /** 0 to 1. */
  similarity: number;
  shared_entities: number;
}

export interface HeldBackMessage {
  raw_message_id: string;
  content: string;
  sent_at: string | null;
  thread_id: string | null;
}

/** A message the pipeline would not turn into memories on its own. */
export interface HeldBack {
  run_id: string;
  held_at: string | null;
  /** `unclear`: nothing reliable was found. `unreadable`: the extraction was unusable. */
  reason: 'unclear' | 'unreadable';
  messages: HeldBackMessage[];
}

export interface ReviewInbox {
  proposed_count: number;
  suggestions: MemorySuggestion[];
  held_back: HeldBack[];
  held_back_count: number;
}

export interface MemorySearchHit {
  memory: MemoryItem;
  rank: number;
}

export interface MemorySearchResult {
  query: string;
  items: MemorySearchHit[];
  degraded: boolean;
}

/** A person, place, or thing the user's memories mention. */
export interface Person {
  id: string;
  entity_type: string;
  name: string;
  memory_count: number;
  last_seen_at: string | null;
}

export interface PersonDetail extends Person {
  aliases: string[];
  /** Newest first. */
  memories: MemoryItem[];
}

export type UsageGranularity = 'day' | 'week' | 'month';

/** One day, week, or month of usage. Periods are UTC; weeks start on Monday. */
export interface UsagePeriod {
  /** The period's first day, YYYY-MM-DD. */
  start: string;
  prompts: number;
  /** Decimal as a string, e.g. "0.0312". */
  cost_usd: string;
  /** `cost_usd` in the history's `currency`. */
  cost: string;
  input_tokens: number;
  output_tokens: number;
}

/** The last 14 days, 12 weeks, or 12 months, oldest first; the last is the current one. */
export interface UsageHistory {
  granularity: UsageGranularity;
  /** ISO 4217 code of every `cost`, e.g. "INR". */
  currency: string;
  periods: UsagePeriod[];
  total_cost_usd: string;
  total_cost: string;
  total_prompts: number;
}

export interface AccountDeletion {
  apps_disconnected: number;
  /** Apps Composio could not revoke; the user should revoke them in each app. */
  apps_not_disconnected: number;
  /** Whether the Supabase sign-in was deleted too. */
  identity_deleted: boolean;
}

export type DevicePlatform = 'ios' | 'android' | 'web';

export interface RegisterPushTokenBody {
  /** An Expo push token, e.g. `ExponentPushToken[...]`. */
  token: string;
  platform: DevicePlatform;
}

export interface FeedbackBody {
  /** 1 to 4000 characters. */
  message: string;
  platform?: DevicePlatform;
  app_version?: string;
}

export interface FeedbackResult {
  id: string;
  created_at: string;
}

// --- Threads and messages --------------------------------------------------------------

export type ThreadKind = 'main' | 'side';

export interface Thread {
  id: string;
  kind: ThreadKind;
  title: string;
  created_at: string;
  /** Moves forward with every new message. */
  updated_at: string;
}

export type ChatRole = 'user' | 'assistant';

export type BrowserPreviewStatus = 'running' | 'completed' | 'failed' | 'login_required';

/** A cloud browser the assistant used. `live_view_url` shows it while it runs. */
export interface BrowserPreview {
  run_id: string;
  session_id: string | null;
  live_view_url: string | null;
  task: string;
  status: BrowserPreviewStatus;
}

/** An app the user has to connect before the assistant can use it. */
export interface ConnectLink {
  toolkit: string;
  tool_name: string;
  connect_url: string;
}

/**
 * once: on `start_date`. weekly: on `weekdays`. monthly: on `day_of_month` (a shorter
 * month runs on its last day). interval: every `interval_hours` from `start_date` at
 * `local_time`.
 */
export type ScheduleFrequency = 'once' | 'daily' | 'weekly' | 'monthly' | 'interval';

export type Weekday =
  'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday';

export type ScheduleDelivery =
  'chat' | 'slack' | 'email' | 'calendar' | 'notion' | 'teams' | 'discord';

export type ProposalStatus = 'pending' | 'confirmed' | 'dismissed';

/** A schedule the assistant proposed. It exists only once the user confirms it. */
export interface ScheduleProposal {
  title: string;
  original_prompt: string;
  task: string;
  frequency: ScheduleFrequency;
  /** HH:MM, 24-hour, in the proposal's timezone. */
  local_time: string;
  weekdays?: Weekday[] | null;
  /** Proposals made before weekdays became a list name one day. */
  weekday?: Weekday | null;
  day_of_month?: number | null;
  /** YYYY-MM-DD. */
  start_date?: string | null;
  interval_hours?: number | null;
  timezone: string;
  delivery: ScheduleDelivery;
  delivery_target: string | null;
  summary: string;
  status: ProposalStatus;
  scheduled_task_id: string | null;
}

/** `skipped`: the slot was not run (missed by too much, or an earlier run was going). */
export type ScheduleRunStatus = 'running' | 'succeeded' | 'failed' | 'skipped';

/** Marks a message that delivered the result of a scheduled run. */
export interface ScheduledRunNote {
  scheduled_task_id: string;
  run_id: string;
  status: ScheduleRunStatus;
}

/** What the app shows beside a message. */
/** A file sent with a user message. The file itself is not kept on the server. */
export interface AttachmentNote {
  name: string;
  media_type: string;
  size_bytes: number;
}

/** Marks a reminder the user set; a sensitive one's text is not in the message. */
export interface ReminderNote {
  memory_id: string;
  sensitive: boolean;
}

/** Marks a daily brief; `follow_ups` were due yesterday and are still open. */
export interface BriefNote {
  day: string;
  follow_ups: { memory_id: string; content: string }[];
}

export interface MessageMetadata {
  browser_preview?: BrowserPreview | null;
  connect_link?: ConnectLink | null;
  schedule_proposal?: ScheduleProposal | null;
  scheduled_run?: ScheduledRunNote | null;
  attachments?: AttachmentNote[] | null;
  reminder?: ReminderNote | null;
  brief?: BriefNote | null;
}

export interface ChatMessage {
  id: string;
  thread_id: string;
  role: ChatRole;
  content: string;
  metadata: MessageMetadata;
  created_at: string;
  updated_at: string;
}

export interface CreateThreadBody {
  title?: string;
}

/** Images (jpeg, png, gif, webp) and PDFs; at most 3 files of 5 MB each by default. */
export type AttachmentMediaType =
  'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp' | 'application/pdf';

export interface AttachmentInput {
  name: string;
  media_type: AttachmentMediaType;
  /** Base64 of the file's bytes, without a `data:` prefix. */
  data: string;
}

export interface SendMessageBody {
  /** May be empty when files are attached. */
  content: string;
  /** IANA timezone of the user, used for the time and for schedules. */
  timezone: string;
  attachments?: AttachmentInput[];
}

// --- Reply stream (`POST /threads/{id}/messages`, NDJSON) -------------------------------

/** The server stored the user's message. */
export interface TurnStartedEvent {
  type: 'turn_started';
  user_message: ChatMessage;
}

export interface TextDeltaEvent {
  type: 'text_delta';
  text: string;
}

export interface ToolStartedEvent {
  type: 'tool_started';
  tool: string;
  /** Human-readable activity, e.g. "Browsing the web". */
  label: string;
}

export interface BrowserEvent {
  type: 'browser';
  browser_preview: BrowserPreview;
}

export interface ConnectLinkEvent {
  type: 'connect_link';
  connect_link: ConnectLink;
}

/** The stored assistant reply. */
export interface FinalEvent {
  type: 'final';
  message: ChatMessage;
}

export interface StreamErrorEvent {
  type: 'error';
  error_code: string;
  message: string;
}

export type ChatStreamEvent =
  | TurnStartedEvent
  | TextDeltaEvent
  | ToolStartedEvent
  | BrowserEvent
  | ConnectLinkEvent
  | FinalEvent
  | StreamErrorEvent;

// --- Schedules -------------------------------------------------------------------------

/** `completed`: a one-time schedule whose moment has come. */
export type ScheduleStatus = 'active' | 'paused' | 'cancelled' | 'completed';

export type ScheduleRunTrigger = 'schedule' | 'manual';

export interface Schedule {
  id: string;
  title: string;
  original_prompt: string;
  task: string;
  frequency: ScheduleFrequency;
  /** HH:MM, 24-hour, in the schedule's timezone. */
  local_time: string;
  /** Weekly: the days it runs on, in order. Empty otherwise. */
  weekdays: Weekday[];
  day_of_month: number | null;
  /** YYYY-MM-DD: the day a one-time schedule runs, or an interval's first day. */
  start_date: string | null;
  interval_hours: number | null;
  timezone: string;
  delivery: ScheduleDelivery;
  delivery_target: string | null;
  status: ScheduleStatus;
  next_run_at: string | null;
  /** The next run as YYYY-MM-DDTHH:MM in the schedule's timezone. */
  next_run_local: string | null;
  last_run_at: string | null;
  last_run_status: ScheduleRunStatus | null;
  last_run_summary: string | null;
  last_run_error: string | null;
  run_count: number;
  source_thread_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleRun {
  id: string;
  scheduled_task_id: string;
  trigger: ScheduleRunTrigger;
  status: ScheduleRunStatus;
  scheduled_for: string | null;
  started_at: string;
  finished_at: string | null;
  summary: string | null;
  error_code: string | null;
  error_message: string | null;
  chat_message_id: string | null;
}

/** The fields of a schedule's rule. Only those its frequency uses are sent. */
export interface ScheduleRuleBody {
  frequency: ScheduleFrequency;
  /** HH:MM, 24-hour, in `timezone`. */
  local_time: string;
  /** IANA timezone. */
  timezone: string;
  weekdays?: Weekday[] | null;
  day_of_month?: number | null;
  /** YYYY-MM-DD. */
  start_date?: string | null;
  interval_hours?: number | null;
}

export interface CreateScheduleBody extends ScheduleRuleBody {
  title: string;
  /** What to do on each run, written as an instruction. */
  task: string;
  delivery?: ScheduleDelivery;
  delivery_target?: string | null;
}

/** A finished scheduled run, as the Feed shows it. */
export interface ActivityItem {
  run_id: string;
  scheduled_task_id: string;
  title: string;
  trigger: ScheduleRunTrigger;
  status: ScheduleRunStatus;
  summary: string | null;
  error_message: string | null;
  delivery: ScheduleDelivery;
  finished_at: string | null;
  /** The thread the result was posted to, when it went to chat. */
  thread_id: string | null;
  chat_message_id: string | null;
}

/** Only the fields sent change. A rule change needs only the fields that differ. */
export interface UpdateScheduleBody extends Partial<ScheduleRuleBody> {
  title?: string;
  task?: string;
  delivery?: ScheduleDelivery;
  delivery_target?: string | null;
  status?: ScheduleStatus;
}

export interface ConfirmProposalResult {
  message: ChatMessage;
  schedule: Schedule;
}

// --- App connections -------------------------------------------------------------------

export type ToolConnectionStatus = 'not_connected' | 'pending' | 'connected' | 'failed' | 'revoked';

export interface ToolAction {
  name: string;
  description: string;
}

/** A connectable app with the signed-in user's connection status. */
export interface Tool {
  slug: string;
  name: string;
  description: string;
  category: string;
  logo_url: string;
  actions: ToolAction[];
  status: ToolConnectionStatus;
  connected_label: string | null;
  connected_email: string | null;
  connected_at: string | null;
  last_checked_at: string | null;
}

export interface ConnectToolBody {
  callback_url?: string;
}

export interface ConnectToolResult {
  tool: Tool;
  /** Open this to authorize the app. `null` when the app was already connected. */
  connect_url: string | null;
}
