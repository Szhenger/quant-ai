import { describe, expect, it } from "vitest";
import { relativizeCursor } from "../../../frontend/src/api/cursor";

describe("relativizeCursor", () => {
  it("strips scheme, host, and the API base prefix", () => {
    expect(
      relativizeCursor("http://localhost:8000/api/v1/alerts/?cursor=cD0yMDI2"),
    ).toBe("/alerts/?cursor=cD0yMDI2");
  });

  it("keeps every query parameter", () => {
    expect(
      relativizeCursor("https://api.example.com/api/v1/alerts/?cursor=abc&page_size=100"),
    ).toBe("/alerts/?cursor=abc&page_size=100");
  });

  it("handles an already-relative link", () => {
    expect(relativizeCursor("/api/v1/alerts/?cursor=x")).toBe("/alerts/?cursor=x");
  });

  it("passes through links outside the API base rather than mangling them", () => {
    expect(relativizeCursor("http://host/other/alerts/?cursor=x")).toBe(
      "http://host/other/alerts/?cursor=x",
    );
  });

  it("maps null (last page) to null", () => {
    expect(relativizeCursor(null)).toBeNull();
  });
});
