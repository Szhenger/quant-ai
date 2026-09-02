/**
 * LoginPage: the two modes, a successful login through the store, and a
 * server error rendered as a human message.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "../../../frontend/src/session/LoginPage";
import { useAuthStore } from "../../../frontend/src/session/auth";
import { installFakeApi, paginated } from "../helpers/fakeApi";
import { renderWithQuery, signOut } from "../helpers/render";

// The mode tab and the submit button can share a label ("Log in"): the tabs
// sit above the form, the submit button inside it.
const form = () => screen.getByLabelText("Password").closest("form")!;
const submitButton = () => within(form()).getByRole("button");
const modeTab = (name: string) =>
  screen.getAllByRole("button", { name }).find((b) => !form().contains(b))!;

describe("<LoginPage>", () => {
  beforeEach(() => {
    signOut();
    localStorage.clear();
  });

  it("logs in through the store and shows the email field only when registering", async () => {
    const user = userEvent.setup();
    const wire = installFakeApi({
      "POST /api/v1/auth/token/": () => ({ data: { access: "a", refresh: "r" } }),
      "GET /api/v1/workspaces/": () => ({ data: paginated([]) }),
    });
    renderWithQuery(<LoginPage />);

    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    await user.click(modeTab("Register"));
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(submitButton()).toHaveTextContent("Create account");
    await user.click(modeTab("Log in"));

    await user.type(screen.getByLabelText("Username"), "  trader ");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(submitButton());

    await waitFor(() => expect(useAuthStore.getState().access).toBe("a"));
    expect(wire.of("POST /api/v1/auth/token/")[0].body).toEqual({ username: "trader", password: "pw" });
  });

  it("renders the server's rejection as readable text", async () => {
    const user = userEvent.setup();
    installFakeApi({
      "POST /api/v1/auth/token/": () => ({
        status: 401, data: { detail: "No active account found with the given credentials" },
      }),
    });
    renderWithQuery(<LoginPage />);
    await user.type(screen.getByLabelText("Username"), "trader");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(submitButton());
    expect(await screen.findByText(/detail: No active account/)).toBeInTheDocument();
    expect(useAuthStore.getState().access).toBeNull();
  });
});
