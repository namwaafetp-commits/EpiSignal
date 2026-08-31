const ISO_2_PATTERN = /^[A-Z]{2}$/;

let regionNames: Intl.DisplayNames | null | undefined;

function normalizedCode(countryCode: string | null) {
  const code = countryCode?.trim().toUpperCase() ?? "";
  return ISO_2_PATTERN.test(code) ? code : "";
}

function getRegionNames() {
  if (regionNames !== undefined) return regionNames;
  if (typeof Intl.DisplayNames !== "function") {
    regionNames = null;
    return regionNames;
  }
  try {
    regionNames = new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    regionNames = null;
  }
  return regionNames;
}

export function countryName(countryCode: string | null) {
  const code = normalizedCode(countryCode);
  if (!code) return countryCode?.trim() || "Location unresolved";

  const name = getRegionNames()?.of(code);
  return name && name !== "Unknown Region" ? name : code;
}

export function countryFlag(countryCode: string | null) {
  const code = normalizedCode(countryCode);
  if (!code) return "";
  return String.fromCodePoint(
    ...[...code].map((letter) => 127397 + letter.charCodeAt(0)),
  );
}

export function formatCountryLocation(
  admin1: string | null,
  countryCode: string | null,
) {
  const code = countryCode?.trim() ?? "";
  const country = countryName(countryCode);
  const flag = country === code ? "" : countryFlag(countryCode);
  const countryLabel = flag ? `${flag} ${country}` : country;
  if (admin1) return `${admin1}, ${countryLabel}`;
  return code ? countryLabel : "Location unresolved";
}
