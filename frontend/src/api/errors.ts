import { AxiosError } from "axios";

/** Turn any thrown value (usually an AxiosError) into a readable message. */
export function extractError(err: unknown): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data;
    if (typeof data === "string") return data;
    if (data && typeof data === "object") {
      const parts: string[] = [];
      for (const [key, val] of Object.entries(data as Record<string, unknown>)) {
        if (Array.isArray(val)) parts.push(`${key}: ${val.join(", ")}`);
        else if (val != null) parts.push(`${key}: ${String(val)}`);
      }
      if (parts.length) return parts.join(" · ");
    }
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
