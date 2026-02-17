import { describe, expect, it } from "vitest";

import { buildApiUrl, resolveApiBase } from "./apiBase";

describe("resolveApiBase", () => {
  it("normalizes /api with trailing slash", () => {
    expect(resolveApiBase("/api/", "https:")).toBe("/api");
  });

  it("accepts absolute https URLs and strips trailing slash", () => {
    expect(resolveApiBase("https://api.example.com/", "https:")).toBe("https://api.example.com");
  });

  it("rejects insecure http URL on https pages", () => {
    expect(() => resolveApiBase("http://api.example.com", "https:")).toThrow(
      "insecure http:// API base"
    );
  });

  it("uses deterministic default when unset", () => {
    expect(resolveApiBase(undefined, "https:")).toBe("/api");
    expect(resolveApiBase("", undefined)).toBe("/api");
  });
});

describe("buildApiUrl", () => {
  it("joins base path and endpoint path", () => {
    expect(buildApiUrl("/api", "/projects")).toBe("/api/projects");
  });

  it("joins absolute API base and endpoint path", () => {
    expect(buildApiUrl("https://api.example.com", "/projects")).toBe("https://api.example.com/projects");
  });
});
