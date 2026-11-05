import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdministratorSessionExpiredError, api } from './api';

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
