import { describe, expect, it } from "vitest";
import { hrefWithParam } from "./page";
import { diseaseGroupLabel, hostSectorLabel } from "@/lib/surveillance-labels";

const activeFilters = {
  disease: "Dengue",
  country: "TH",
  status: "ongoing",
  host_sector: "animal",
  disease_group: "vector_borne",
};

function queryOf(href: string) {
  return new URLSearchParams(href.split("?")[1]);
}

describe("event filter links", () => {
  it.each([
    ["host_sector", "animal"],
    ["disease_group", "vector_borne"],
    ["country", "TH"],
    ["status", "ongoing"],
  ])("preserves all active filters when selecting %s", (param, value) => {
    const query = queryOf(
      hrefWithParam(param, value, undefined, activeFilters),
    );

    for (const [key, expected] of Object.entries(activeFilters)) {
      expect(query.get(key)).toBe(expected);
    }
  });

  it("preserves combined disease, country, host, and group filters", () => {
    const query = queryOf(
      hrefWithParam("disease_group", "respiratory", undefined, activeFilters),
    );

    expect(query.get("disease")).toBe("Dengue");
    expect(query.get("country")).toBe("TH");
    expect(query.get("host_sector")).toBe("animal");
    expect(query.get("disease_group")).toBe("respiratory");
  });

  it("clears only the active filter", () => {
    const query = queryOf(
      hrefWithParam("host_sector", "animal", "animal", activeFilters),
    );

    expect(query.has("host_sector")).toBe(false);
    expect(query.get("disease")).toBe("Dengue");
    expect(query.get("country")).toBe("TH");
    expect(query.get("status")).toBe("ongoing");
    expect(query.get("disease_group")).toBe("vector_borne");
  });

  it("uses human-facing surveillance labels", () => {
    expect(diseaseGroupLabel("enteric_food_waterborne")).toBe(
      "Enteric / food- & water-borne infections",
    );
    expect(hostSectorLabel("human")).toBe("Human");
    expect(hostSectorLabel("animal")).toBe("Animal");
    expect(hostSectorLabel("both")).toBe("Human + Animal");
    expect(hostSectorLabel("unknown")).toBe("Unknown");
  });
});
