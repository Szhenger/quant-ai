/**
 * The transport (api/client.ts) against a fake wire: the real interceptors
 * are exercised — header injection from the session bridge, the single-flight
 * 401 refresh, the rejected-vs-transient refresh split, boot-time restore,
 * and the concurrent page fan-out.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import api, { bootstrapAccess, fetchAllPages } from "../../../frontend/src/api/client";
import { useAuthStore } from "../../../frontend/src/session/auth";
import { installFakeApi, paginated, type FakeApi } from "../helpers/fakeApi";
import { signIn, signOut, WORKSPACE_ID } from "../helpers/render";

const REFRESH = "POST /api/v1/auth/token/refresh/";

describe("api/client", () => {
  let wire: FakeApi;

  beforeEach(() => {
    signOut();
    localStorage.clear();
  });

  it("attaches the bearer token and the workspace header from the session", async () => {
    signIn();
    wire = installFakeApi({ "GET /api/v1/limits/": () => ({ data: { ok: true } }) });
    await api.get("/limits/");
    const [req] = wire.of("GET /api/v1/limits/");
    expect(req.headers.authorization).toBe("Bearer access-token");
    expect(req.headers["x-workspace-id"]).toBe(WORKSPACE_ID);
  });

  it("refreshes ONCE for parallel 401s, retries both, and persists the rotated pair", async () => {
    signIn({ access: "stale" });
    let refreshed = false;
    wire = installFakeApi({
      "GET /api/v1/strategies/": (req) =>
        req.headers.authorization === "Bearer fresh"
          ? { data: paginated([]) }
          : { status: 401, data: { detail: "expired" } },
      "GET /api/v1/limits/": (req) =>
        req.headers.authorization === "Bearer fresh"
          ? { data: { ok: true } }
          : { status: 401, data: { detail: "expired" } },
      [REFRESH]: async () => {
        refreshed = true;
        // Hold the refresh open long enough for both 401s to queue behind it.
        await new Promise((r) => setTimeout(r, 10));
        return { data: { access: "fresh", refresh: "rotated" } };
      },
    });

    const [a, b] = await Promise.all([api.get("/strategies/"), api.get("/limits/")]);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    expect(refreshed).toBe(true);
    expect(wire.of(REFRESH)).toHaveLength(1); // single flight
    expect(wire.of(REFRESH)[0].body).toEqual({ refresh: "refresh-token" });
    // Rotation: the NEW refresh token is what the store holds now.
    expect(useAuthStore.getState().access).toBe("fresh");
    expect(useAuthStore.getState().refresh).toBe("rotated");
    // Each original request was retried exactly once with the new bearer.
    expect(wire.of("GET /api/v1/strategies/").map((r) => r.headers.authorization)).toEqual([
      "Bearer stale", "Bearer fresh",
    ]);
  });

  it("ends the session when the refresh token itself is rejected", async () => {
    signIn({ access: "stale" });
    wire = installFakeApi({
      "GET /api/v1/strategies/": () => ({ status: 401, data: {} }),
      [REFRESH]: () => ({ status: 401, data: { detail: "blacklisted" } }),
      "POST /api/v1/auth/logout/": () => ({ status: 205 }),
    });
    await expect(api.get("/strategies/")).rejects.toMatchObject({ response: { status: 401 } });
    expect(useAuthStore.getState().access).toBeNull();
    expect(useAuthStore.getState().refresh).toBeNull();
    expect(useAuthStore.getState().workspaceId).toBeNull();
  });

  it("keeps the session on a transient refresh failure and fails only that request", async () => {
    signIn({ access: "stale" });
    wire = installFakeApi({
      "GET /api/v1/strategies/": () => ({ status: 401, data: {} }),
      [REFRESH]: () => ({ status: 502, data: "bad gateway" }),
    });
    await expect(api.get("/strategies/")).rejects.toBeTruthy();
    expect(useAuthStore.getState().refresh).toBe("refresh-token");
    expect(useAuthStore.getState().access).toBe("stale");
  });

  it("bootstrapAccess trades the persisted refresh token for an access token, once", async () => {
    signIn({ access: null });
    wire = installFakeApi({
      [REFRESH]: async () => {
        await new Promise((r) => setTimeout(r, 5));
        return { data: { access: "booted", refresh: "rotated" } };
      },
    });
    const [x, y] = await Promise.all([bootstrapAccess(), bootstrapAccess()]);
    expect(x).toBe(true);
    expect(y).toBe(true);
    expect(wire.of(REFRESH)).toHaveLength(1);
    expect(useAuthStore.getState().access).toBe("booted");
  });

  it("bootstrapAccess reports false without a refresh token and never calls the wire", async () => {
    wire = installFakeApi({});
    expect(await bootstrapAccess()).toBe(false);
    expect(wire.calls).toHaveLength(0);
  });

  it("fetchAllPages fans the remaining offsets out concurrently and concatenates in order", async () => {
    signIn();
    const page = (offset: number) => Array.from({ length: 50 }, (_, i) => ({ id: offset + i }));
    wire = installFakeApi({
      "GET /api/v1/watchlist/": (req) => {
        const offset = Number(req.params.offset ?? 0);
        return { data: paginated(page(offset), 120, offset + 50 < 120 ? "next" : null) };
      },
    });
    const rows = await fetchAllPages<{ id: number }>("/watchlist/");
    expect(rows).toHaveLength(150); // 3 pages x 50 (the fake returns full pages)
    expect(wire.of("GET /api/v1/watchlist/").map((r) => r.params.offset ?? 0)).toEqual([0, 50, 100]);
    expect(rows.map((r) => r.id).slice(48, 52)).toEqual([48, 49, 50, 51]);
  });
});
