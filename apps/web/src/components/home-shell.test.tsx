import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { HomeShell } from "./home-shell";

const evidenceFeed = {
  status: "ready" as const,
  data: {
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
  },
};

test("renders traceable evidence and warns that coverage is limited", () => {
  render(<HomeShell apiStatus="ready" evidenceFeed={evidenceFeed} />);

  expect(
    screen.getByRole("heading", {
      name: "Ebola disease - Democratic Republic of the Congo",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("4665 confirmed cases.")).toBeInTheDocument();
  expect(screen.getByText("Collected 26 Aug 2026")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /view original/i })).toHaveAttribute(
    "href",
    "https://www.who.int/report",
  );
  expect(screen.getByText("Limited coverage")).toBeInTheDocument();
  expect(screen.getByText(/12 reports from 1 source/i)).toBeInTheDocument();
  expect(
    screen.getByText(/not comprehensive global surveillance/i),
  ).toBeInTheDocument();
});

const emptyFeed = {
  status: "ready" as const,
  data: { items: [], total: 0, source_count: 0, limit: 20, offset: 0 },
};

const unavailableFeed = { status: "unavailable" as const, data: null };

test("renders an honest evidence-free shell", () => {
  render(<HomeShell apiStatus="ready" evidenceFeed={emptyFeed} />);
  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toBeDisabled();
  expect(
    screen.getByText("No source evidence has been ingested yet."),
  ).toBeInTheDocument();
  expect(screen.queryByText(/cases|deaths/i)).not.toBeInTheDocument();
});

test("shows API unavailability without hiding the product shell", () => {
  render(<HomeShell apiStatus="unavailable" evidenceFeed={unavailableFeed} />);
  expect(screen.getByText("API unavailable")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /what are official health sources/i }),
  ).toBeInTheDocument();
  expect(screen.getByText("Evidence feed unavailable.")).toBeInTheDocument();
});

test("shows loading state in the same stable shell", () => {
  render(
    <HomeShell
      apiStatus="loading"
      evidenceFeed={{ status: "loading", data: null }}
    />,
  );
  expect(screen.getByText("Checking API")).toBeInTheDocument();
  expect(screen.getByText("Checking stored reports.")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
});

test("marks the mobile coverage panel as a bottom sheet", () => {
  render(<HomeShell apiStatus="ready" evidenceFeed={evidenceFeed} />);
  expect(screen.getByLabelText("Coverage notice")).toHaveAttribute(
    "data-mobile-role",
    "bottom-sheet",
  );
});
