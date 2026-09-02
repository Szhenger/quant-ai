/**
 * A fake transport for the real axios client.
 *
 * Tests install a route table and the app's OWN `api` instance (interceptors,
 * baseURL, header injection, single-flight refresh — all of it) runs against
 * it. Nothing in src/ is mocked: only the wire is replaced, at the adapter
 * boundary axios provides for exactly this purpose. The bare `axios` default
 * used by the session store for login/refresh/logout shares the same table.
 */
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import api from "../../../frontend/src/api/client";

export interface FakeRequest {
  method: string;
  path: string;
  params: Record<string, unknown>;
  body: unknown;
  headers: Record<string, string>;
}

export type Handler = (req: FakeRequest) => { status?: number; data?: unknown } | Promise<{ status?: number; data?: unknown }>;

/** Keys look like "GET /api/v1/alerts/" — full path including the API base. */
export type Routes = Record<string, Handler>;

export interface FakeApi {
  calls: FakeRequest[];
  /** Requests whose key matches, in order. */
  of(key: string): FakeRequest[];
  /** Replace or add a handler mid-test. */
  route(key: string, handler: Handler): void;
}

function fullPath(config: InternalAxiosRequestConfig): string {
  const url = config.url ?? "";
  if (/^https?:\/\//.test(url)) return new URL(url).pathname;
  const base = config.baseURL ?? "";
  return (url.startsWith("/") && base && !url.startsWith(base) ? base + url : url).split("?")[0];
}

function plainHeaders(config: InternalAxiosRequestConfig): Record<string, string> {
  const out: Record<string, string> = {};
  const raw = config.headers as unknown as { toJSON?: () => Record<string, unknown> } & Record<string, unknown>;
  const entries = typeof raw?.toJSON === "function" ? raw.toJSON() : raw ?? {};
  for (const [k, v] of Object.entries(entries)) {
    if (v != null) out[k.toLowerCase()] = String(v);
  }
  return out;
}

export function installFakeApi(routes: Routes): FakeApi {
  const table: Routes = { ...routes };
  const calls: FakeRequest[] = [];

  const adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    const method = (config.method ?? "get").toUpperCase();
    const path = fullPath(config);
    const req: FakeRequest = {
      method,
      path,
      params: (config.params as Record<string, unknown>) ?? {},
      body: typeof config.data === "string" ? JSON.parse(config.data) : config.data,
      headers: plainHeaders(config),
    };
    calls.push(req);
    const handler = table[`${method} ${path}`];
    if (!handler) {
      throw new AxiosError(`no fake route for ${method} ${path}`, "ERR_BAD_REQUEST", config, null, {
        status: 404, statusText: "Not Found", data: { detail: `no fake route for ${method} ${path}` },
        headers: {}, config,
      } as AxiosResponse);
    }
    const { status = 200, data = null } = await handler(req);
    const response: AxiosResponse = {
      status, statusText: String(status), data, headers: {}, config,
    };
    if (status >= 400) {
      throw new AxiosError(
        `Request failed with status code ${status}`,
        status >= 500 ? "ERR_BAD_RESPONSE" : "ERR_BAD_REQUEST",
        config, null, response,
      );
    }
    return response;
  };

  api.defaults.adapter = adapter;
  axios.defaults.adapter = adapter;

  return {
    calls,
    of: (key) => calls.filter((c) => `${c.method} ${c.path}` === key),
    route: (key, handler) => {
      table[key] = handler;
    },
  };
}

/** A DRF LimitOffset page. */
export function paginated<T>(results: T[], count = results.length, next: string | null = null) {
  return { count, next, previous: null, results };
}

/** A DRF cursor page (alerts). */
export function cursorPage<T>(results: T[], next: string | null = null) {
  return { next, previous: null, results };
}
