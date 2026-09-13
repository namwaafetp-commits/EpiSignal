import { render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PageViewTracker } from "./page-view-tracker";

const track = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/events/EVT-2026-00001",
}));

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
  vi.stubEnv("NEXT_PUBLIC_UMAMI_SCRIPT_URL", "https://stats.example/script.js");
  track.mockReset();
  window.umami = { track };
});

afterEach(() => {
  delete window.umami;
  vi.unstubAllEnvs();
});

it("tracks a sanitized page path instead of the event public ID", () => {
  render(<PageViewTracker />);

  expect(track).toHaveBeenCalledWith({
    website: "website-id",
    url: "/events/:public_id",
    title: "EpiSignal — Event",
  });
  expect(JSON.stringify(track.mock.calls)).not.toContain("EVT-2026-00001");
});
