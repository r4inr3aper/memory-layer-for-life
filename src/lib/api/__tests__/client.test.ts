import { apiRequest, ApiError, buildApiUrl, readApiError } from '@/lib/api/client';
import { supabase } from '@/lib/supabase';

jest.mock('@/lib/env', () => ({
  env: { apiUrl: 'https://api.test', supabaseUrl: '', supabasePublishableKey: '' },
  isApiConfigured: true,
  isSupabaseConfigured: false,
}));

jest.mock('@/lib/supabase', () => ({
  getAccessToken: jest.fn(async () => 'token-123'),
  supabase: {
    auth: {
      getSession: jest.fn(async () => ({ data: { session: { access_token: 'token-123' } } })),
      signOut: jest.fn(async () => ({ error: null })),
    },
  },
}));

const mockSignOut = supabase.auth.signOut as jest.Mock;

function errorResponse(status: number, body: string | (() => Promise<string>)) {
  return {
    status,
    text: typeof body === 'function' ? body : async () => body,
  };
}

describe('readApiError', () => {
  it('uses the error code, message, and detail from the JSON body', async () => {
    const error = await readApiError(
      errorResponse(
        422,
        JSON.stringify({
          error_code: 'VALIDATION_ERROR',
          message: 'Title is required.',
          detail: 'title',
        })
      )
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Title is required.',
      detail: 'title',
    });
  });

  it('falls back to a readable message when the body is not JSON', async () => {
    const error = await readApiError(errorResponse(502, '<html>Bad Gateway</html>'));

    expect(error).toMatchObject({
      status: 502,
      code: 'http_error',
      message: 'The server is unavailable right now. Please try again.',
      detail: null,
    });
  });

  it('explains an expired session for an empty 401', async () => {
    const error = await readApiError(errorResponse(401, ''));

    expect(error.message).toBe('Your session has expired. Please sign in again.');
    expect(error.code).toBe('http_error');
  });

  it('keeps the code when the message is missing, and survives an unreadable body', async () => {
    const withoutMessage = await readApiError(
      errorResponse(404, JSON.stringify({ error_code: 'NOT_FOUND' }))
    );
    expect(withoutMessage).toMatchObject({
      status: 404,
      code: 'NOT_FOUND',
      message: 'Request failed (404).',
    });

    const unreadable = await readApiError(
      errorResponse(500, () => Promise.reject(new Error('stream closed')))
    );
    expect(unreadable).toMatchObject({ status: 500, code: 'http_error' });
  });
});

describe('buildApiUrl', () => {
  it('joins the API origin, version prefix, and path', () => {
    expect(buildApiUrl('/threads/main')).toBe('https://api.test/api/v1/threads/main');
  });

  it('encodes the query and skips null and undefined values', () => {
    expect(
      buildApiUrl('/activity', {
        limit: 50,
        offset: 0,
        kind: undefined,
        cursor: null,
        search: 'a b&c',
        archived: false,
      })
    ).toBe('https://api.test/api/v1/activity?limit=50&offset=0&search=a%20b%26c&archived=false');
  });

  it('repeats the key of an array value', () => {
    expect(buildApiUrl('/me/memories', { status: ['proposed', 'active'], limit: 5 })).toBe(
      'https://api.test/api/v1/me/memories?status=proposed&status=active&limit=5'
    );
    expect(buildApiUrl('/me/memories', { status: [] })).toBe('https://api.test/api/v1/me/memories');
  });

  it('throws a clear error when no API URL is configured', () => {
    const mockEnv = jest.requireMock<{ isApiConfigured: boolean }>('@/lib/env');
    mockEnv.isApiConfigured = false;
    try {
      expect(() => buildApiUrl('/me')).toThrow(
        expect.objectContaining({ status: 0, code: 'api_not_configured' })
      );
    } finally {
      mockEnv.isApiConfigured = true;
    }
  });
});

describe('apiRequest', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockSignOut.mockClear();
  });

  it('signs out when the server answers 401, and still throws the ApiError', async () => {
    globalThis.fetch = jest.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ error_code: 'UNAUTHORIZED', message: 'Token expired.' }),
    })) as unknown as typeof fetch;

    await expect(apiRequest('/me')).rejects.toMatchObject({
      status: 401,
      code: 'UNAUTHORIZED',
      message: 'Token expired.',
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('returns undefined for 204 and parses JSON otherwise', async () => {
    globalThis.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 204, text: async () => '' })
      .mockResolvedValueOnce({ ok: true, status: 200, text: async () => '{"id":"u1"}' });

    await expect(apiRequest('/threads/t1', { method: 'DELETE' })).resolves.toBeUndefined();
    await expect(apiRequest('/me')).resolves.toEqual({ id: 'u1' });
    expect(mockSignOut).not.toHaveBeenCalled();
  });
});
