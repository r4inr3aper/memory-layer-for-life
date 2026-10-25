import { describe, expect, it } from "vitest";

import { isActivePath, matchPath, parseLocation } from "./router";

describe("parseLocation", () => {
  it("splits the path from the query and drops a trailing slash", () => {
    const location = parseLocation("/calls/?status=failed&model=claude-haiku-5-5");
    expect(location.path).toBe("/calls");
    expect(location.query.get("status")).toBe("failed");
    expect(location.query.get("model")).toBe("claude-haiku-5-5");
  });

  it("treats an empty hash as the root", () => {
    expect(parseLocation("").path).toBe("/");
    expect(parseLocation("/").path).toBe("/");
  });
});

describe("matchPath", () => {
  it("matches fixed paths exactly", () => {
    expect(matchPath("/", "/")).toEqual({});
    expect(matchPath("/calls", "/calls")).toEqual({});
    expect(matchPath("/calls", "/pipeline")).toBeNull();
    expect(matchPath("/calls", "/calls/extra")).toBeNull();
  });

  it("reads parameters and decodes them", () => {
    expect(matchPath("/evaluations/:runId", "/evaluations/abc-123")).toEqual({ runId: "abc-123" });
    expect(matchPath("/x/:name", "/x/a%20b")).toEqual({ name: "a b" });
    expect(matchPath("/evaluations/:runId", "/evaluations")).toBeNull();
  });
});

describe("isActivePath", () => {
  it("selects a section for its sub-pages but the root only for itself", () => {
    expect(isActivePath("/evaluations/abc", "/evaluations", false)).toBe(true);
    expect(isActivePath("/evaluations", "/evaluations", false)).toBe(true);
    expect(isActivePath("/evaluations-old", "/evaluations", false)).toBe(false);
    expect(isActivePath("/calls", "/", false)).toBe(false);
    expect(isActivePath("/", "/", true)).toBe(true);
  });
});
