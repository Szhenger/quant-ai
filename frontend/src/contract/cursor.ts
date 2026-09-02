/**
 * DRF builds cursor `next`/`previous` links as ABSOLUTE URLs from the Host
 * header it saw. In dev that host is the backend (`localhost:8000`, because
 * the vite proxy forwards with changeOrigin), not the origin the browser is
 * on — following the link verbatim turns page 2 into a cross-origin request
 * that dies in CORS preflight. Behind a TLS terminator it can come back as
 * `http://` and get blocked as mixed content.
 *
 * The fix: keep only the path + query and strip the API base's path prefix,
 * so every page rides the same axios base (and dev proxy) as page 1. The
 * prefix is derived from the caller's configured base (client.ts passes
 * API_BASE), never a duplicate hardcoded constant — a deployment that mounts
 * the API elsewhere (VITE_API_BASE) keeps its cursor walk working.
 */
export function relativizeCursor(
  next: string | null,
  apiBase: string = "/api/v1",
): string | null {
  if (!next) return null;
  try {
    // An absolute base's prefix is its pathname ("https://api.x/backend" →
    // "/backend"); a relative base is already a path.
    let prefix = new URL(apiBase, "http://relative.invalid").pathname;
    if (prefix.endsWith("/")) prefix = prefix.slice(0, -1);
    const url = new URL(next, "http://relative.invalid");
    if (url.pathname.startsWith(`${prefix}/`)) {
      return url.pathname.slice(prefix.length) + url.search;
    }
    // Unexpected shape (different mount prefix): pass through untouched
    // rather than mangling it into a wrong relative path.
    return next;
  } catch {
    return next;
  }
}
