import type { Role } from './types';
export async function api<T>(
  path: string,
  role: Role,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { 'X-RelayOps-Role': role, Accept: 'application/json' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['X-RelayOps-Request'] = '1';
  }
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const data = await response
    .json()
    .catch(() => ({ detail: `Unreadable server response (${response.status})` }));
  if (!response.ok)
    throw new Error(
      typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`,
    );
  return data as T;
}
export async function downloadReport(id: string, role: Role) {
  const response = await fetch(`/api/cases/${encodeURIComponent(id)}/report`, {
    headers: { 'X-RelayOps-Role': role },
  });
  if (!response.ok) throw new Error(`Report download failed (${response.status})`);
  const blob = await response.blob(),
    url = URL.createObjectURL(blob),
    anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `relayops-${id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function downloadPatch(id: string, role: Role) {
  const response = await fetch(`/api/cases/${encodeURIComponent(id)}/patch`, {
    headers: { 'X-RelayOps-Role': role },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: 'Patch download unavailable' }));
    throw new Error(data.detail || 'Patch download unavailable');
  }
  const url = URL.createObjectURL(await response.blob()),
    anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `relayops-${id}.patch`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
