import { describe, expect, it } from "vitest";

import {
  cacheHitRate,
  formatDuration,
  formatPercent,
  formatRelative,
  formatTokens,
  formatUsd,
  modelLabel,
  passRate,
  truncate,
} from "./format";

describe("money", () => {
  it("shows cents for ordinary amounts and more digits for tiny ones", () => {
    expect(formatUsd(1.2)).toBe("$1.20");
    expect(formatUsd(0.000446)).toBe("$0.000446");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(null)).toBe("n/a");
  });
});

describe("counts and durations", () => {
  it("rounds large token counts", () => {
    expect(formatTokens(726)).toBe("726");
    expect(formatTokens(858168)).toBe("858.2K");
  });

  it("picks the unit by size", () => {
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(7900)).toBe("7.9 s");
    expect(formatDuration(125_000)).toBe("2 min 5 s");
    expect(formatDuration(undefined)).toBe("n/a");
  });

  it("formats percentages and rates", () => {
    expect(formatPercent(0.9838, 1)).toBe("98.4%");
    expect(passRate(122, 2)).toBeCloseTo(122 / 124);
    expect(passRate(0, 0)).toBeNull();
    expect(cacheHitRate(900, 100, 0)).toBe(0.9);
    expect(cacheHitRate(0, 0, 0)).toBeNull();
  });
});

describe("time", () => {
  it("describes recent moments relative to now", () => {
    const now = new Date("2026-10-12T10:00:00Z");
    expect(formatRelative("2026-10-12T09:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-12T09:40:00Z", now)).toBe("20 min ago");
    expect(formatRelative("2026-10-12T07:00:00Z", now)).toBe("3 h ago");
    expect(formatRelative("2026-10-11T07:00:00Z", now)).toBe("yesterday");
  });
});

describe("names", () => {
  it("shortens model ids", () => {
    expect(modelLabel("claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(modelLabel("claude-haiku-5-5")).toBe("Haiku 5.5");
    expect(modelLabel("claude-opus-5")).toBe("Opus 5");
    expect(modelLabel("test-model")).toBe("test-model");
    expect(modelLabel(null)).toBe("unknown");
  });

  it("truncates with an ellipsis", () => {
    expect(truncate("buy milk", 20)).toBe("buy milk");
    expect(truncate("a much longer note", 8)).toBe("a much …");
  });
});
