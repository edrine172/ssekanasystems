import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdministratorSessionExpiredError, api, subscribeToAdministratorSessionExpired } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('database backup API', () => {
  it('downloads the backup with the administrator session and response filename', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('backup', {
      status: 200,
      headers: {
        'Content-Disposition': 'attachment; filename="stockpulse-database-backup-test.json.gz"',
      },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.downloadSystemBackup();

    expect(result.filename).toBe('stockpulse-database-backup-test.json.gz');
    expect(await result.blob.text()).toBe('backup');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/system\/backup\/$/),
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );
  });

  it('identifies an expired administrator session from the backup API response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Authentication credentials were not provided.' }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.downloadSystemBackup()).rejects.toBeInstanceOf(AdministratorSessionExpiredError);
  });
});

describe('API GET response cache', () => {
  it('reuses recent reads and invalidates them after a mutation', async () => {
    let productName = 'Initial';
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/access/csrf/')) {
        return new Response(JSON.stringify({ csrf_token: 'csrf-token' }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/products/') && (init?.method ?? 'GET') === 'GET') {
        return new Response(JSON.stringify([{ id: 1, name: productName }]), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/products/1/') && init?.method === 'PATCH') {
        productName = 'Updated';
        return new Response(JSON.stringify({ id: 1, name: productName }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const firstRead = await api.products();
    const cachedRead = await api.products();
    expect(firstRead[0].name).toBe('Initial');
    expect(cachedRead[0].name).toBe('Initial');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await api.updateProduct(1, { name: 'Updated' });
    const refreshedRead = await api.products();
    expect(refreshedRead[0].name).toBe('Updated');
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

describe('API bearer access tokens', () => {
  it('refreshes expiring access tokens before sending API requests', async () => {
    const makeToken = (expiresInSeconds: number) => {
      const encodedClaims = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expiresInSeconds }))
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
      return `e30.${encodedClaims}.signature`;
    };
    const accessToken = makeToken(10);
    const refreshedAccessToken = makeToken(600);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/access/csrf/')) {
        return new Response(JSON.stringify({ csrf_token: 'csrf-token' }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/access/login/')) {
        return new Response(JSON.stringify({
          user: { id: 1, username: 'admin' },
          csrf_token: 'csrf-token',
          access_token: accessToken,
        }), { headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/access/token/refresh/')) {
        return new Response(JSON.stringify({ access_token: refreshedAccessToken }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/products/')) {
        return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/access/logout/') && init?.method === 'POST') {
        return new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.accessLogin('admin', 'password');
    await api.products();
    const productsRequest = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/products/'));
    expect(new Headers(productsRequest?.[1]?.headers).get('Authorization')).toBe(`Bearer ${refreshedAccessToken}`);
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/access/token/refresh/'))).toBe(true);
    await api.accessLogout();
  });
});

describe('administrator session handling', () => {
  it('notifies the app when an API request reports an expired session', async () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAdministratorSessionExpired(listener);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Authentication credentials were not provided.' }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.expenseSummary()).rejects.toBeInstanceOf(AdministratorSessionExpiredError);
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
  });
});
