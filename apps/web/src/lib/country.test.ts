import { describe, expect, it } from "vitest";
import { countryFlag, countryName, formatCountryLocation } from "./country";

describe("country presentation", () => {
  it.each([
    ["AR", "Argentina", "🇦🇷", "🇦🇷 Argentina"],
    ["TH", "Thailand", "🇹🇭", "🇹🇭 Thailand"],
    ["US", "United States", "🇺🇸", "🇺🇸 United States"],
  ])("formats %s as %s", (code, name, flag, label) => {
    expect(countryName(code)).toBe(name);
    expect(countryFlag(code)).toBe(flag);
    expect(formatCountryLocation(null, code)).toBe(label);
  });

  it("places an administrative area before readable country", () => {
    expect(formatCountryLocation("Chiang Mai", "TH")).toBe(
      "Chiang Mai, 🇹🇭 Thailand",
    );
  });

  it("falls back to country code when no country name is available", () => {
    expect(formatCountryLocation(null, "ZZ")).toBe("ZZ");
  });
});
