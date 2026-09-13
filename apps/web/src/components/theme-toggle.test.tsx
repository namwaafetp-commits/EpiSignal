import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeToggle } from "./theme-toggle";

let systemDark = false;
let change: (() => void) | undefined;
const track = vi.fn();
beforeEach(() => {
  localStorage.clear();
  vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
  vi.stubEnv("NEXT_PUBLIC_UMAMI_SCRIPT_URL", "https://stats.example/script.js");
  track.mockReset();
  window.umami = { track };
  systemDark = false;
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return systemDark;
    },
    addEventListener: (_: string, fn: () => void) => {
      change = fn;
    },
    removeEventListener: vi.fn(),
  }));
});
afterEach(() => {
  cleanup();
  delete window.umami;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const option = (label: string) =>
  screen.getByRole("button", { name: `${label} theme` });

it("switches true light/black themes and restores the saved preference", () => {
  const view = render(<ThemeToggle />);
  fireEvent.click(option("Dark"));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("episignal-theme")).toBe("dark");

  view.unmount();
  render(<ThemeToggle />);
  expect(option("Dark")).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(option("Light"));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(option("Light")).toHaveAttribute("aria-pressed", "true");
  expect(option("Dark")).toHaveAttribute("aria-pressed", "false");
});

it("follows system changes only when System is selected", () => {
  render(<ThemeToggle />);
  expect(option("System")).toHaveAttribute("aria-pressed", "true");

  systemDark = true;
  change?.();
  expect(document.documentElement.dataset.theme).toBe("dark");

  fireEvent.click(option("Light"));
  change?.();
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("labels every icon-only option for assistive technology", () => {
  render(<ThemeToggle />);
  const group = screen.getByRole("group", { name: "Theme" });
  expect(group).toBeInTheDocument();
  for (const label of ["Light", "Dark", "System"]) {
    expect(option(label)).toHaveAttribute("title", `${label} theme`);
  }
});

it("tracks an approved theme change without preference details", () => {
  render(<ThemeToggle />);

  fireEvent.click(option("Dark"));

  expect(track).toHaveBeenCalledWith(
    expect.objectContaining({
      name: "theme_change",
      data: { theme: "dark" },
    }),
  );
});
