import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TopNavigation } from "./app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/briefing",
  useSearchParams: () => new URLSearchParams("period=3d&country=TH"),
}));

const track = vi.fn();

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
  vi.stubEnv("NEXT_PUBLIC_UMAMI_SCRIPT_URL", "https://stats.example/script.js");
  track.mockReset();
  window.umami = { track };
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});
afterEach(() => {
  cleanup();
  delete window.umami;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("keeps shareable filters across Map and Briefing navigation", () => {
  render(<TopNavigation />);
  expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute(
    "href",
    "/?period=3d&country=TH",
  );
  expect(screen.getByRole("link", { name: "Briefing" })).toHaveAttribute(
    "href",
    "/briefing?period=3d&country=TH",
  );
  expect(screen.getByRole("link", { name: "Briefing" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("link", { name: "Search events" })).toHaveAttribute(
    "href",
    "/briefing?period=3d&country=TH#event-search",
  );
});

it("carries the brand mark on the home link without duplicating its label", () => {
  const { container } = render(<TopNavigation />);
  const home = screen.getByRole("link", { name: "EpiSignal home" });
  expect(home).toHaveAttribute("href", "/?period=3d&country=TH");

  // Both variants ship so the pre-paint theme script can swap them in CSS alone.
  const marks = container.querySelectorAll(".wordmark-mark");
  expect(marks).toHaveLength(2);
  for (const mark of marks) {
    expect(mark).toHaveAttribute("alt", "");
  }
});

it("tracks Map and Briefing view switches", () => {
  render(<TopNavigation />);

  fireEvent.click(screen.getByRole("link", { name: "Map" }));
  fireEvent.click(screen.getByRole("link", { name: "Briefing" }));

  expect(track).toHaveBeenNthCalledWith(1, {
    website: "website-id",
    url: "/",
    title: "EpiSignal — Map",
    name: "view_switch",
    data: { view: "map" },
  });
  expect(track).toHaveBeenNthCalledWith(2, {
    website: "website-id",
    url: "/",
    title: "EpiSignal — Map",
    name: "view_switch",
    data: { view: "briefing" },
  });
});
