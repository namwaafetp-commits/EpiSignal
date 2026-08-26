import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { HomeShell } from "./home-shell";

test("renders an honest evidence-free foundation shell", () => {
  render(<HomeShell apiStatus="ready" />);
  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toBeDisabled();
  expect(
    screen.getByText(
      "Event records will appear after source ingestion is connected.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/cases|deaths/i)).not.toBeInTheDocument();
});

test("shows API unavailability without hiding the product shell", () => {
  render(<HomeShell apiStatus="unavailable" />);
  expect(screen.getByText("API unavailable")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /what is happening/i }),
  ).toBeInTheDocument();
});

test("shows loading state in the same stable shell", () => {
  render(<HomeShell apiStatus="loading" />);
  expect(screen.getByText("Checking API")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
});

test("marks the mobile readiness panel as a bottom sheet", () => {
  render(<HomeShell apiStatus="ready" />);
  expect(screen.getByLabelText("Foundation status")).toHaveAttribute(
    "data-mobile-role",
    "bottom-sheet",
  );
});
