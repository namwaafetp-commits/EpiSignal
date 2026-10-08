import { afterEach, expect, test, vi } from "vitest";

import { GET } from "./route";

afterEach(() => vi.unstubAllGlobals());

test("web liveness stays available when backend requests fail", async () => {
  vi.stubGlobal("fetch", () => {
    throw new Error("Backend unavailable");
  });

  const response = GET();

  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "live" });
});
