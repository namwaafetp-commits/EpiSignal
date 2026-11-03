import { fireEvent, render } from "@testing-library/react";
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
  delete window.umami;
  document.body.innerHTML = "";
});

afterEach(() => {
  delete window.umami;
  vi.unstubAllEnvs();
});

it("tracks a sanitized page path instead of the event public ID", () => {
  const script = document.createElement("script");
  script.id = "episignal-umami";
  script.dataset.websiteId = "website-id";
  document.body.append(script);
  window.umami = { track };
  render(<PageViewTracker />);

  expect(track).toHaveBeenCalledWith({
    website: "website-id",
    url: "/events/:public_id",
    title: "EpiSignal — Event",
  });
  expect(JSON.stringify(track.mock.calls)).not.toContain("EVT-2026-00001");
});

it("waits for tracker script load when tracker is not ready on mount", () => {
  const script = document.createElement("script");
  script.id = "episignal-umami";
  script.dataset.websiteId = "website-id";
  document.body.append(script);

  render(<PageViewTracker />);
  expect(track).not.toHaveBeenCalled();

  window.umami = { track };
  fireEvent.load(script);

  expect(track).toHaveBeenCalledOnce();
});

it("sends exactly one pageview when tracker load fires more than once", () => {
  const script = document.createElement("script");
  script.id = "episignal-umami";
  script.dataset.websiteId = "website-id";
  document.body.append(script);

  render(<PageViewTracker />);
  window.umami = { track };
  fireEvent.load(script);
  fireEvent.load(script);

  expect(track).toHaveBeenCalledOnce();
});

it("does not wait indefinitely when tracker script is unavailable", () => {
  expect(() => render(<PageViewTracker />)).not.toThrow();
  expect(track).not.toHaveBeenCalled();
});

it("is a no-op when the rendered tracker has no website id", () => {
  vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "");
  const script = document.createElement("script");
  script.id = "episignal-umami";
  script.dataset.websiteId = "";
  document.body.append(script);

  window.umami = { track };
  render(<PageViewTracker />);
  fireEvent.load(script);

  expect(track).not.toHaveBeenCalled();
});
