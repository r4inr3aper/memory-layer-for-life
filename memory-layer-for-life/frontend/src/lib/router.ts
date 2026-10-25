/**
 * A small hash router: `#/evaluations/abc?x=1` is the path `/evaluations/abc` with a query.
 *
 * Hash routes need nothing from the server, so the console works from the API's static
 * file mount and from a plain file server alike.
 */
import { useMemo, useSyncExternalStore } from "react";

export interface RouteLocation {
  path: string;
  query: URLSearchParams;
}

function currentHash(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

export function parseLocation(hash: string): RouteLocation {
  const [rawPath, search = ""] = hash.split("?", 2);
  const trimmed = rawPath.replace(/\/+$/, "");
  return { path: trimmed === "" ? "/" : trimmed, query: new URLSearchParams(search) };
}

export function useRouteLocation(): RouteLocation {
  const hash = useSyncExternalStore(subscribe, currentHash, () => "/");
  return useMemo(() => parseLocation(hash), [hash]);
}

/** Match `/evaluations/:runId` against a path. Returns the parameters, or null. */
export function matchPath(pattern: string, path: string): Record<string, string> | null {
  const expected = pattern.split("/").filter(Boolean);
  const actual = path.split("/").filter(Boolean);
  if (expected.length !== actual.length) return null;
  const params: Record<string, string> = {};
  for (let index = 0; index < expected.length; index += 1) {
    if (expected[index].startsWith(":")) {
      params[expected[index].slice(1)] = decodeURIComponent(actual[index]);
    } else if (expected[index] !== actual[index]) {
      return null;
    }
  }
  return params;
}

/** Whether a navigation entry for `to` should look selected on `path`. */
export function isActivePath(path: string, to: string, end: boolean): boolean {
  if (end || to === "/") return path === to;
  return path === to || path.startsWith(`${to}/`);
}

export function hrefTo(to: string): string {
  return `#${to}`;
}

export function navigate(to: string): void {
  window.location.hash = to;
}
