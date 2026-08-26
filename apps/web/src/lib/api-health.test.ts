import { afterEach, expect, test, vi } from "vitest";
import { getApiStatus } from "./api-health";

afterEach(() => vi.unstubAllGlobals());

test("returns ready for a ready API", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ready",
        components: { database: "up", postgis: "up" },
      }),
    }),
  );
  await expect(getApiStatus()).resolves.toBe("ready");
});

test("returns unavailable instead of throwing", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(getApiStatus()).resolves.toBe("unavailable");
});
