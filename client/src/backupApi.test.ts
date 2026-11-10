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
