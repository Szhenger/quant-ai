/**
 * The session store (session/auth.ts): login/register/logout against the
 * fake wire, what is (and is not) persisted, and the cross-tab sync that
 * keeps every tab on the current refresh token after a rotation.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../../../frontend/src/session/auth";
import { queryClient } from "../../../frontend/src/app/queryClient";
import { installFakeApi, paginated, type FakeApi } from "../helpers/fakeApi";
import { signIn, signOut, WORKSPACE_ID } from "../helpers/render";

const STORAGE_KEY = "quantai-auth";

describe("session/auth", () => {
  let wire: FakeApi;

  beforeEach(() => {
    signOut();
    localStorage.clear();
    queryClient.clear();
  });

  it("login stores the token pair and loads the caller's workspaces", async () => {
    wire = installFakeApi({
      "POST /api/v1/auth/token/": (req) => {
        expect(req.body).toEqual({ username: "trader", password: "pw" });
        return { data: { access: "a1", refresh: "r1" } };
      },
      "GET /api/v1/workspaces/": (req) => {
        // The workspace list is fetched through the authenticated client.
        expect(req.headers.authorization).toBe("Bearer a1");
        return { data: paginated([{ id: WORKSPACE_ID, name: "Desk", created_at: "2026-01-01T00:00:00Z" }]) };
      },
    });
    await useAuthStore.getState().login("trader", "pw");
    const s = useAuthStore.getState();
    expect(s.access).toBe("a1");
    expect(s.refresh).toBe("r1");
    expect(s.username).toBe("trader");
    expect(s.workspaceId).toBe(WORKSPACE_ID);
    expect(s.workspaces).toHaveLength(1);
  });

  it("register creates the account and then logs in", async () => {
    wire = installFakeApi({
      "POST /api/v1/auth/register/": () => ({ status: 201, data: { id: 1 } }),
      "POST /api/v1/auth/token/": () => ({ data: { access: "a", refresh: "r" } }),
      "GET /api/v1/workspaces/": () => ({ data: paginated([]) }),
    });
    await useAuthStore.getState().register("newbie", "n@example.com", "pw");
    expect(wire.calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /api/v1/auth/register/", "POST /api/v1/auth/token/", "GET /api/v1/workspaces/",
    ]);
    expect(useAuthStore.getState().workspaceId).toBeNull(); // no workspace came back
  });

  it("loadWorkspaces keeps the active workspace only if it is still listed", async () => {
    signIn({ workspaceId: "gone" });
    wire = installFakeApi({
      "GET /api/v1/workspaces/": () => ({
        data: paginated([{ id: WORKSPACE_ID, name: "Desk", created_at: "2026-01-01T00:00:00Z" }]),
      }),
    });
    await useAuthStore.getState().loadWorkspaces();
    expect(useAuthStore.getState().workspaceId).toBe(WORKSPACE_ID);
  });

  it("persists the refresh token and workspace but never the access token", () => {
    signIn({ access: "secret-bearer", refresh: "r-persisted" });
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as { state?: Record<string, unknown> };
    expect(stored.state?.refresh).toBe("r-persisted");
    expect(stored.state?.workspaceId).toBe(WORKSPACE_ID);
    expect(stored.state).not.toHaveProperty("access");
    expect(JSON.stringify(stored)).not.toContain("secret-bearer");
  });

  it("logout revokes the refresh token server-side, clears the store and the query cache", async () => {
    signIn();
    queryClient.setQueryData([WORKSPACE_ID, "strategies"], [{ id: "cached" }]);
    wire = installFakeApi({
      "POST /api/v1/auth/logout/": (req) => {
        expect(req.body).toEqual({ refresh: "refresh-token" });
        return { status: 205 };
      },
    });
    useAuthStore.getState().logout();
    await Promise.resolve(); // the fire-and-forget POST is dispatched synchronously
    expect(wire.of("POST /api/v1/auth/logout/")).toHaveLength(1);
    const s = useAuthStore.getState();
    expect([s.access, s.refresh, s.workspaceId, s.username]).toEqual([null, null, null, null]);
    expect(queryClient.getQueryData([WORKSPACE_ID, "strategies"])).toBeUndefined();
  });

  it("rehydrates from another tab's rotation via the storage event", async () => {
    signIn({ refresh: "old-pair" });
    // Another tab rotated the pair and wrote the new one to localStorage.
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as { state: Record<string, unknown>; version: number };
    stored.state.refresh = "rotated-elsewhere";
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
    await new Promise((r) => setTimeout(r, 0));
    expect(useAuthStore.getState().refresh).toBe("rotated-elsewhere");
  });
});
