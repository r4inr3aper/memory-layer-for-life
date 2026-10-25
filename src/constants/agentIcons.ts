/**
 * Agent Avatar Icons
 *
 * The backend stores the chosen avatar as a short key (`^[A-Za-z0-9_-]{1,40}$`), never
 * the emoji itself. `cooper` is the original mascot image.
 */

export const DEFAULT_AGENT_ICON = 'cooper';

export const AGENT_ICONS = [
  { key: 'cooper', emoji: null, label: 'Cooper' },
  { key: 'robot', emoji: '🤖', label: 'Robot' },
  { key: 'sparkles', emoji: '✨', label: 'Sparkles' },
  { key: 'brain', emoji: '🧠', label: 'Brain' },
  { key: 'rocket', emoji: '🚀', label: 'Rocket' },
  { key: 'bulb', emoji: '💡', label: 'Light bulb' },
  { key: 'target', emoji: '🎯', label: 'Target' },
  { key: 'seedling', emoji: '🌱', label: 'Seedling' },
  { key: 'zap', emoji: '⚡', label: 'Lightning' },
] as const;

export type AgentIconKey = (typeof AGENT_ICONS)[number]['key'];

export function isAgentIconKey(value: unknown): value is AgentIconKey {
  return AGENT_ICONS.some((icon) => icon.key === value);
}

/** The emoji for an icon key, or `null` for the mascot image (and for unknown keys). */
export function agentIconEmoji(key: string | null | undefined): string | null {
  return AGENT_ICONS.find((icon) => icon.key === key)?.emoji ?? null;
}
