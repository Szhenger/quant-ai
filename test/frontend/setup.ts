/**
 * Shared vitest setup: jest-dom matchers (`toBeInTheDocument`, ...) and an
 * unmount after every test so one render can never leak into the next.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
