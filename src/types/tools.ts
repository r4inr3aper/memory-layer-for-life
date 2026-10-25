/**
 * App Connection (Tool) Types
 *
 * The backend API owns the catalog and each user's connection status; these are its
 * wire types, re-exported for UI code.
 */

export type {
  ConnectToolResult,
  Tool,
  ToolAction,
  ToolConnectionStatus,
} from '@/lib/api/types';
