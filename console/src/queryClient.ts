import { QueryClient } from "@tanstack/react-query";

/**
 * The client-side concurrency layer. React Query deduplicates concurrent
 * requests for the same key, aborts fetches whose consumers unmounted (the
 * AbortSignal is threaded through to axios), serves cached data instantly
 * while revalidating in the background, and retries transient failures.
 *
 * Query keys are prefixed with the workspace id (see api/hooks.ts), so
 * switching workspace switches to a separate cache namespace instead of
 * showing another tenant's data while refetching.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // fresh-enough window: instant tab switches, no refetch storm
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});
