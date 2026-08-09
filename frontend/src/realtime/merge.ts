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
