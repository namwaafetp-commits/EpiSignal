import { describe, expect, it } from "vitest";
import { briefingHref } from "./page";
import { diseaseGroupLabel, hostSectorLabel } from "@/lib/surveillance-labels";

describe("legacy /events redirect", () => {
  it("sends a bare request to the briefing", () => {
    expect(briefingHref({})).toBe("/briefing");
  });

  it("carries the filters the briefing still supports", () => {
    const href = briefingHref({
      disease: "Dengue",
      country: "TH",
      host_sector: "animal",
      disease_group: "vector_borne",
    });
    const query = new URLSearchParams(href.split("?")[1]);

    expect(query.get("disease_group")).toBe("vector_borne");
    expect(query.get("country")).toBe("TH");
    expect(query.get("host")).toBe("animal");
    // A named disease becomes a free-text search on the briefing.
    expect(query.get("q")).toBe("Dengue");
  });

  it("drops retired and all-value filters", () => {
    const href = briefingHref({
      status: "ongoing",
      country: "all",
      disease_group: "respiratory",
    });
    const query = new URLSearchParams(href.split("?")[1]);

    expect(query.has("status")).toBe(false);
    expect(query.has("country")).toBe(false);
    expect(query.get("disease_group")).toBe("respiratory");
  });

  it("uses human-facing surveillance labels", () => {
    expect(diseaseGroupLabel("enteric_food_waterborne")).toBe(
      "Enteric / food- & water-borne infections",
    );
    expect(hostSectorLabel("human")).toBe("Human");
    expect(hostSectorLabel("animal")).toBe("Animal");
    expect(hostSectorLabel("both")).toBe("Human / Animal");
    expect(hostSectorLabel("unknown")).toBe("Unknown");
  });
});
