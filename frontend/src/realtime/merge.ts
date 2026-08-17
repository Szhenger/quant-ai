/**
 * Pure cache-merge helpers for the alerts query cache. Kept free of React and
 * React Query imports so the concurrency-sensitive logic (dedupe on socket
 * prepend, optimistic read-state transitions) is unit-testable in isolation.
 */
import type { Alert, CursorPage } from "../api/types";

export interface AlertPages {
  pages: CursorPage<Alert>[];
  pageParams: unknown[];
}

/**
 * Prepend a socket-delivered alert to the first cached page.
 *
 * Dedupes by id across *all* cached pages: the same alert can arrive twice —
 * once over the socket and once in a background refetch that raced it — and
 * must render exactly once.
 */
export function prependAlert(data: AlertPages, alert: Alert): AlertPages {
  if (data.pages.some((p) => p.results.some((a) => a.id === alert.id))) {
    return data;
  }
  const [first, ...rest] = data.pages;
  if (!first) {
    return { ...data, pages: [{ next: null, previous: null, results: [alert] }] };
  }
  return { ...data, pages: [{ ...first, results: [alert, ...first.results] }, ...rest] };
}

export function markOneRead(data: AlertPages, id: string): AlertPages {
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      results: p.results.map((a) => (a.id === id ? { ...a, is_read: true } : a)),
    })),
  };
}

export function markAllRead(data: AlertPages): AlertPages {
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      results: p.results.map((a) => (a.is_read ? a : { ...a, is_read: true })),
    })),
  };
}

/** Ids of every currently-unread alert — the snapshot a rollback needs. */
export function unreadIds(data: AlertPages): string[] {
  return data.pages.flatMap((p) => p.results.filter((a) => !a.is_read).map((a) => a.id));
}

/**
 * Rollback for optimistic read-marking. Applied to the CURRENT cache rather
 * than restoring a pre-mutation snapshot: a snapshot restore would silently
 * delete any socket-delivered alert that arrived while the mutation was in
 * flight. Un-marking exactly the ids we optimistically marked loses nothing.
 */
export function markUnread(data: AlertPages, ids: readonly string[]): AlertPages {
  const wanted = new Set(ids);
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      results: p.results.map((a) => (wanted.has(a.id) ? { ...a, is_read: false } : a)),
    })),
  };
}

/**
 * Merge a fetched alerts page with the current in-memory list.
 *
 * The REST snapshot may be OLDER than socket-delivered alerts already on
 * screen (the fetch raced the socket): replacing would silently drop them.
 * Merge by id — fetched rows win for shared ids (they carry fresher server
 * state, e.g. read flags) — and keep newest-first ordering.
 */

export function mergeAlerts(fetched: Alert[], current: Alert[]): Alert[] {
  const byId = new Map<string, Alert>();
  for (const a of current) byId.set(a.id, a);
  for (const a of fetched) byId.set(a.id, a);
  return [...byId.values()].sort((x, y) => y.created_at.localeCompare(x.created_at));
}

/**
 * Flatten cached pages into one render list, deduping by id: after a socket
 * prepend or a first-page merge, an alert can transiently sit on two pages
 * (it slid across a cursor boundary between fetches). First occurrence wins —
 * pages run newest-first, so that is the freshest copy.
 */
export function flattenPages(data: AlertPages | undefined): Alert[] {
  if (!data) return [];
  const seen = new Set<string>();
  const out: Alert[] = [];
  for (const page of data.pages) {
    for (const alert of page.results) {
      if (!seen.has(alert.id)) {
        seen.add(alert.id);
        out.push(alert);
      }
    }
  }
  return out;
}
