/**
 * DRF builds cursor `next`/`previous` links as ABSOLUTE URLs from the Host
 * header it saw. In dev that host is the backend (`localhost:8000`, because
 * the vite proxy forwards with changeOrigin), not the origin the browser is
 * on — following the link verbatim turns page 2 into a cross-origin request
 * that dies in CORS preflight. Behind a TLS terminator it can come back as
 * `http://` and get blocked as mixed content.
 *
 * The fix: keep only the path + query and strip the axios base prefix, so
 * every page rides the same same-origin path (and dev proxy) as page 1.
 */
const API_BASE = "/api/v1";

export function relativizeCursor(next: string | null): string | null {
  if (!next) return null;
  try {
    const url = new URL(next, "http://relative.invalid");
    if (url.pathname.startsWith(`${API_BASE}/`)) {
      return url.pathname.slice(API_BASE.length) + url.search;
    }
    // Unexpected shape (different mount prefix): pass through untouched
    // rather than mangling it into a wrong relative path.
    return next;
  } catch {
    return next;
  }
}
