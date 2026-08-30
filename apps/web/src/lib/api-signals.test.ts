import { afterEach, expect, test, vi } from "vitest";
import { getEvidenceFeed } from "./api-signals";

afterEach(() => vi.unstubAllGlobals());

test("returns exact evidence from the signals endpoint", async () => {
  const payload = {
    items: [
      {
        id: "178cc906-edee-4b01-9efb-b230c00a397a",
        source_name: "WHO Disease Outbreak News",
        title: "Ebola disease - Democratic Republic of the Congo",
        raw_text: "4665 confirmed cases.",
        url: "https://www.who.int/report",
        published_at: "2026-08-14T15:38:29Z",
        retrieved_at: "2026-08-26T10:00:00Z",
      },
    ],
    total: 12,
    source_count: 1,
    limit: 20,
    offset: 0,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => payload }),
  );

  await expect(getEvidenceFeed()).resolves.toEqual({
    status: "ready",
    data: payload,
  });
});

test("returns unavailable instead of inventing evidence", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

  await expect(getEvidenceFeed()).resolves.toEqual({
    status: "unavailable",
    data: null,
  });
});

test("rejects malformed successful responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: "not evidence", total: 12 }),
    }),
  );

  await expect(getEvidenceFeed()).resolves.toEqual({
    status: "unavailable",
    data: null,
  });
});
