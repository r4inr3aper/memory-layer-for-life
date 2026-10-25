/**
 * Backend API Client
 *
 * `apiRequest` sends one JSON request to `${API_URL}/api/v1` with the signed-in user's
 * Supabase access token, and turns every failure into an `ApiError`.
 */

import { env, isApiConfigured } from '@/lib/env';
import { getAccessToken, supabase } from '@/lib/supabase';
import type { ApiErrorBody } from '@/lib/api/types';

const API_PREFIX = '/api/v1';

type QueryScalar = string | number | boolean;
type QueryValue = QueryScalar | readonly QueryScalar[] | null | undefined;

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  /** Serialized as JSON when present. */
  body?: unknown;
  /**
   * Appended as a query string; `null`/`undefined` values are skipped and an array repeats
   * its key (`status=a&status=b`).
   */
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

/**
 * A failed API call. `status` is the HTTP status, or 0 when the server was not reached.
 * `message` is safe to show to the user.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | null;

  constructor(status: number, code: string, message: string, detail: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal } = options;
  const url = buildApiUrl(path, query);
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(await authHeaders()),
  };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    throw toNetworkError(error, signal);
  }

  if (!response.ok) {
    throw await failedResponseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Full URL of an API path such as `/threads/main`. */
export function buildApiUrl(path: string, query?: Record<string, QueryValue>): string {
  if (!isApiConfigured) {
    throw new ApiError(
      0,
      'api_not_configured',
      'The app is not connected to a server. Set EXPO_PUBLIC_API_URL and restart.'
    );
  }

  const search = Object.entries(query ?? {})
    .flatMap(([key, value]) =>
      value === undefined || value === null
        ? []
        : (Array.isArray(value) ? value : [value]).map(
            (item) => `${encodeURIComponent(key)}=${encodeURIComponent(String(item))}`
          )
    )
    .join('&');

  return `${env.apiUrl}${API_PREFIX}${path}${search ? `?${search}` : ''}`;
}

/** `Authorization` header for the signed-in user. Throws a 401 `ApiError` when signed out. */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, 'not_signed_in', 'Please sign in again.');
  }
  return { Authorization: `Bearer ${token}` };
}

/** Builds an `ApiError` from a non-2xx response with the backend's JSON error body. */
export async function readApiError(response: {
  status: number;
  text(): Promise<string>;
}): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    const text = await response.text();
    body = text ? (JSON.parse(text) as Partial<ApiErrorBody>) : null;
  } catch {
    body = null;
  }

  const message =
    typeof body?.message === 'string' && body.message
      ? body.message
      : fallbackMessage(response.status);
  const code = typeof body?.error_code === 'string' ? body.error_code : 'http_error';
  const detail = typeof body?.detail === 'string' ? body.detail : null;

  return new ApiError(response.status, code, message, detail);
}

/**
 * The `ApiError` for a non-2xx response. A 401 means the server no longer accepts the
 * session, so it also signs the user out; the route guard then shows the sign-in screen.
 */
export async function failedResponseError(response: {
  status: number;
  text(): Promise<string>;
}): Promise<ApiError> {
  const error = await readApiError(response);
  if (error.status === 401) {
    void signOutExpiredSession();
  }
  return error;
}

let expiredSessionSignOut: Promise<void> | null = null;

/**
 * Signs out after the server rejected the session. Requests that fail together share one
 * sign-out, and nothing happens when the user is already signed out.
 */
export function signOutExpiredSession(): Promise<void> {
  expiredSessionSignOut ??= (async () => {
    try {
      const { data } = await supabase.auth.getSession();
      if (data.session) {
        await supabase.auth.signOut();
      }
    } catch (error) {
      console.warn('[api] Could not sign out after a 401:', error);
    } finally {
      expiredSessionSignOut = null;
    }
  })();
  return expiredSessionSignOut;
}

/** Wraps a fetch rejection: aborts pass through unchanged, anything else is a network error. */
export function toNetworkError(error: unknown, signal?: AbortSignal): unknown {
  if (isAbortError(error, signal)) {
    return error;
  }
  return new ApiError(
    0,
    'network_error',
    'Could not reach the server. Check your connection and try again.'
  );
}

/**
 * True for the rejection of a request or stream cancelled with an `AbortController`.
 * Pass the request's signal when available: some fetch implementations reject an
 * aborted request with an error that is not named `AbortError`.
 */
export function isAbortError(error: unknown, signal?: AbortSignal | null): boolean {
  if (signal?.aborted) {
    return true;
  }
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: unknown }).name === 'AbortError'
  );
}

/** A user-facing message for any thrown value. */
export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function fallbackMessage(status: number): string {
  if (status === 401) {
    return 'Your session has expired. Please sign in again.';
  }
  if (status >= 500) {
    return 'The server is unavailable right now. Please try again.';
  }
  return `Request failed (${status}).`;
}
