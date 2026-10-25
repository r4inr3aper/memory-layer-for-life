/** Formatting that the whole console shares, so the same number reads the same everywhere. */

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usdPrecise = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 6,
});
const integer = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** Money. Small amounts keep enough digits to show a single cheap call. */
export function formatUsd(value: number | null | undefined, options?: { precise?: boolean }) {
  if (value === null || value === undefined) return "n/a";
  if (value !== 0 && (options?.precise || value < 0.01)) return usdPrecise.format(value);
  return usd.format(value);
}

export function formatInteger(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return integer.format(value);
}

/** Token counts read better rounded once they pass a few thousand. */
export function formatTokens(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return value >= 10_000 ? compact.format(value) : integer.format(value);
}

export function formatDuration(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "n/a";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} min ${seconds} s`;
}

export function formatPercent(ratio: number | null | undefined, digits = 0) {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return "n/a";
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "n/a";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "n/a";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "3 min ago", "2 h ago", "yesterday". Falls back to the date beyond a week. */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()) {
  if (!iso) return "n/a";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 172_800) return "yesterday";
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)} days ago`;
  return formatDate(iso);
}

/** Passed over evaluated, or null before anything was evaluated. */
export function passRate(passed: number, failed: number) {
  const evaluated = passed + failed;
  return evaluated === 0 ? null : passed / evaluated;
}

/** The share of prompt tokens that came from the cache. */
export function cacheHitRate(cacheRead: number, cacheWrite: number, fresh: number) {
  const prompt = cacheRead + cacheWrite + fresh;
  return prompt === 0 ? null : cacheRead / prompt;
}

/** A short, readable name for a model id. */
export function modelLabel(model: string | null | undefined) {
  if (!model) return "unknown";
  const match = model.match(/^claude-([a-z]+)-(\d+)(?:-(\d+))?/);
  if (!match) return model;
  const [, family, major, minor] = match;
  const name = family.charAt(0).toUpperCase() + family.slice(1);
  return minor ? `${name} ${major}.${minor}` : `${name} ${major}`;
}

export function truncate(text: string, length: number) {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}
