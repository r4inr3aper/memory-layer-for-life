/**
 * App Connections (Tools) API
 */

import { apiRequest } from '@/lib/api/client';
import type { ConnectToolBody, ConnectToolResult, Tool } from '@/lib/api/types';

/** The whole app catalog, each with the user's last known connection status. */
export function listTools(signal?: AbortSignal): Promise<Tool[]> {
  return apiRequest<Tool[]>('/tools', { signal });
}

/**
 * Starts connecting an app. `connect_url` is where the user authorizes it, or `null`
 * when the app is already connected.
 */
export function connectTool(slug: string, callbackUrl?: string): Promise<ConnectToolResult> {
  const body: ConnectToolBody = callbackUrl ? { callback_url: callbackUrl } : {};
  return apiRequest<ConnectToolResult>(`${toolPath(slug)}/connect`, { method: 'POST', body });
}

/** Refreshes an app's connection status from Composio. */
export function getToolConnection(slug: string): Promise<Tool> {
  return apiRequest<Tool>(`${toolPath(slug)}/connection`);
}

/** Removes every connected account of the app. */
export function disconnectTool(slug: string): Promise<Tool> {
  return apiRequest<Tool>(`${toolPath(slug)}/connection`, { method: 'DELETE' });
}

function toolPath(slug: string): string {
  return `/tools/${encodeURIComponent(slug)}`;
}
