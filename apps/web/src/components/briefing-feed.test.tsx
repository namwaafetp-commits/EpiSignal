import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardEvent } from "../lib/api-dashboard";
import { BriefingFeed, SHELF_THRESHOLD } from "./briefing-feed";

const NOW = Date.parse("2026-09-13T12:00:00Z");

function buildEvent(index: number, overrides: Partial<DashboardEvent> = {}) {
  return {
    public_id: `EVT-${String(index).padStart(5, "0")}`,
    headline: `Reported event ${index}`,
    summary: "A summary.",
    disease: "Dengue",
    disease_group: "vector_borne",
    disease_group_label: "Vector-borne infections",
    host_sector: "human",
    event_type: "outbreak",
    status: "monitoring",
    country_code: "TH",
    admin1: null,
    first_reported_at: "2026-09-01T00:00:00Z",
    latest_report_at: "2026-09-13T10:00:00Z",
    article_count: 2,
    last_summarized_at: "2026-09-13T11:00:00Z",
    latitude: null,
    longitude: null,
    map_level: null,
    ...overrides,
  } as DashboardEvent;
}

function renderFeed(events: DashboardEvent[]) {
  return render(
    <BriefingFeed
      events={events}
      selectedId={null}
      onSelect={vi.fn()}
      query=""
      now={NOW}
    />,
  );
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BriefingFeed", () => {
  it("keeps the dated timeline for a small feed", () => {
    const { container } = renderFeed([buildEvent(1), buildEvent(2)]);
    expect(screen.getByText(/13 September 2026/)).toBeVisible();
    expect(container.querySelector(".shelf-track")).toBeNull();
  });

  it("groups a large feed into horizontal disease-group tracks", () => {
    const events = [
      ...Array.from({ length: SHELF_THRESHOLD }, (_, i) => buildEvent(i + 1)),
      buildEvent(99, {
        disease_group: "respiratory",
        disease_group_label: "Respiratory",
        headline: "Respiratory cluster under investigation",
      }),
    ];
    const { container } = renderFeed(events);

    const tracks = container.querySelectorAll(".shelf-track");
    expect(tracks).toHaveLength(2);

    // Busiest disease group leads, and every event stays reachable.
    const shelves = screen.getAllByRole("region");
    expect(shelves[0]).toHaveAccessibleName(
      `Vector-borne infections — ${SHELF_THRESHOLD} events`,
    );
    expect(shelves[1]).toHaveAccessibleName("Respiratory — 1 events");
    expect(
      within(shelves[1]).getByRole("link", {
        name: /Respiratory cluster under investigation/,
      }),
    ).toBeVisible();
    expect(screen.getAllByRole("link")).toHaveLength(events.length);
  });

  it("labels host sector for assistive technology when only the icon shows", () => {
    renderFeed([buildEvent(1, { host_sector: "both" })]);
    expect(screen.getByTitle("Human / Animal")).toBeInTheDocument();
    expect(screen.getByText("Human / Animal")).toHaveClass("sr-only");
  });

  describe("keyboard traversal", () => {
    const headlines = () =>
      screen.getAllByRole("link").map((a) => a.textContent?.trim());

    it("walks the feed with j and k from anywhere on the page", () => {
      renderFeed([buildEvent(1), buildEvent(2), buildEvent(3)]);

      fireEvent.keyDown(document, { key: "j" });
      expect(document.activeElement).toHaveTextContent("Reported event 1");

      fireEvent.keyDown(document, { key: "j" });
      expect(document.activeElement).toHaveTextContent("Reported event 2");

      fireEvent.keyDown(document, { key: "k" });
      expect(document.activeElement).toHaveTextContent("Reported event 1");

      // Stops at the ends rather than wrapping.
      fireEvent.keyDown(document, { key: "k" });
      expect(document.activeElement).toHaveTextContent("Reported event 1");
      expect(headlines()).toHaveLength(3);
    });

    it("leaves typing alone", () => {
      const { container } = renderFeed([buildEvent(1)]);
      const input = document.createElement("input");
      container.append(input);
      input.focus();

      fireEvent.keyDown(input, { key: "j" });
      expect(document.activeElement).toBe(input);
    });

    it("ignores shortcuts held with a modifier", () => {
      renderFeed([buildEvent(1), buildEvent(2)]);
      fireEvent.keyDown(document, { key: "j", metaKey: true });
      expect(document.activeElement).toBe(document.body);
    });

    it("takes the arrow keys only once focus is already in the feed", () => {
      renderFeed([buildEvent(1), buildEvent(2)]);

      // Outside the feed the page keeps its normal scrolling.
      const outside = fireEvent.keyDown(document, { key: "ArrowDown" });
      expect(outside).toBe(true);
      expect(document.activeElement).toBe(document.body);

      fireEvent.keyDown(document, { key: "j" });
      expect(document.activeElement).toHaveTextContent("Reported event 1");

      fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
      expect(document.activeElement).toHaveTextContent("Reported event 2");
    });

    it("opens the reading pane on Enter without letting the link fire twice", () => {
      const onSelect = vi.fn();
      render(
        <BriefingFeed
          events={[buildEvent(1), buildEvent(2)]}
          selectedId={null}
          onSelect={onSelect}
          query=""
          now={NOW}
        />,
      );

      fireEvent.keyDown(document, { key: "j" });
      const focused = document.activeElement as HTMLAnchorElement;
      const notDefaultPrevented = fireEvent.keyDown(focused, { key: "Enter" });

      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledWith("EVT-00001");
      // preventDefault suppresses the browser click, so the pane opens once.
      expect(notDefaultPrevented).toBe(false);
    });

    it("lets a modified Enter follow the link instead", () => {
      const onSelect = vi.fn();
      render(
        <BriefingFeed
          events={[buildEvent(1)]}
          selectedId={null}
          onSelect={onSelect}
          query=""
          now={NOW}
        />,
      );

      fireEvent.keyDown(document, { key: "j" });
      fireEvent.keyDown(document.activeElement!, {
        key: "Enter",
        metaKey: true,
      });
      expect(onSelect).not.toHaveBeenCalled();
    });

    it("tells the reader the shortcuts exist", () => {
      renderFeed([buildEvent(1)]);
      expect(screen.getByText(/to move through events/)).toBeInTheDocument();
    });
  });
});
