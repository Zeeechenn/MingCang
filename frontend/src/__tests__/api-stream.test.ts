import { afterEach, expect, it, vi } from 'vitest';
import { chatWithAIStream } from '../services/api';

afterEach(() => vi.unstubAllGlobals());

it('does not replay a chat POST when streaming is unavailable', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: undefined });
  vi.stubGlobal('fetch', fetchMock);

  await expect(chatWithAIStream({ message: 'single submit' })).rejects.toThrow(/check the request status before retrying/i);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
