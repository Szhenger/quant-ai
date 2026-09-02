import type { Indicator, IndicatorReading } from "./types";

/**
 * Word a field value exactly as the server does (markets.indicators.read_indicator):
 * walk the field's reading bands in order, first band that holds wins, a band
 * with no operator is the catch-all. Kept in lockstep with the backend so the
 * analysis table and the stock page never disagree about what "oversold" means.
 */
export const NO_HISTORY_READING = "not enough history yet";

function holds(band: IndicatorReading, value: number): boolean {
  if (band.op == null || band.at == null) return true;
  switch (band.op) {
    case "<":
      return value < band.at;
    case ">":
      return value > band.at;
    case "<=":
      return value <= band.at;
    case ">=":
      return value >= band.at;
    default:
      return false; // an operator this build doesn't know: never claim the band
  }
}

export function readIndicator(spec: Indicator | undefined, value: number | null): string {
  if (!spec || spec.readings.length === 0) return "";
  if (value == null || Number.isNaN(value)) return NO_HISTORY_READING;
  for (const band of spec.readings) {
    if (holds(band, value)) return band.text;
  }
  return "";
}
