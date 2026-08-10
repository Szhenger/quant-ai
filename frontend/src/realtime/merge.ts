/**
 * Merge a fetched alerts page with the current in-memory list.
 *
 * The REST snapshot may be OLDER than socket-delivered alerts already on
 * screen (the fetch raced the socket): replacing would silently drop them.
 * Merge by id — fetched rows win for shared ids (they carry fresher server
 * state, e.g. read flags) — and keep newest-first ordering.
 */
import type { Alert } from "../api/types";

export function mergeAlerts(fetched: Alert[], current: Alert[]): Alert[] {
  const byId = new Map<string, Alert>();
  for (const a of current) byId.set(a.id, a);
  for (const a of fetched) byId.set(a.id, a);
  return [...byId.values()].sort((x, y) => y.created_at.localeCompare(x.created_at));
}
