import { useQuery } from "@tanstack/react-query";
import api from "./client";
import { keys } from "./keys";
import type { IndicatorCatalog } from "../contract/types";

/**
 * The field registry (`GET /indicators/`): every indicator's label, unit,
 * parameter defaults, default threshold, summary flag and reading bands.
 * Shared by the markets screens (wording a value) and the strategy builders
 * (building the form), which is why it lives here rather than in either.
 */
export function useIndicatorCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: ({ signal }) =>
      api.get<IndicatorCatalog>("/indicators/", { signal }).then((r) => r.data),
    staleTime: Infinity, // static metadata; fetch once per session
  });
}
