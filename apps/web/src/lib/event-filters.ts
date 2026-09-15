import type { DashboardEvent } from "./api-dashboard";
import { countryName } from "./country";
import { diseaseGroupLabel, hostSectorLabel } from "./surveillance-labels";

/**
 * The map is a "what is happening now" surface, so it offers tight windows and
 * opens on Today. The briefing is a reading surface and keeps the wider ranges.
 */
export const BRIEFING_PERIODS = [
  "today",
  "24h",
  "3d",
  "7d",
  "30d",
  "custom",
] as const;
export const MAP_PERIODS = ["today", "24h", "48h", "72h", "custom"] as const;
export const PERIODS = [
  ...new Set([...BRIEFING_PERIODS, ...MAP_PERIODS]),
] as const;

export const PERIOD_LABELS: Record<string, string> = {
  today: "Today",
  "24h": "24h",
  "48h": "48h",
  "72h": "72h",
  "3d": "3d",
  "7d": "7d",
  "30d": "30d",
  custom: "Custom",
};

const ROLLING_HOURS: Record<string, number> = {
  "24h": 24,
  "48h": 48,
  "72h": 72,
  "3d": 72,
  "7d": 168,
  "30d": 720,
};

export type FilterView = "map" | "briefing";

export function defaultPeriod(view: FilterView) {
  return view === "map" ? "today" : "7d";
}

export function periodOptions(view: FilterView) {
  return view === "map" ? MAP_PERIODS : BRIEFING_PERIODS;
}
export type EventFilters = {
  period: string;
  disease_group: string;
  host: string;
  country: string;
  q: string;
  from: string;
  to: string;
};
export function currentTimestamp() {
  return Date.now();
}
export function readFilters(
  query: string,
  view: FilterView = "briefing",
): EventFilters {
  const params = new URLSearchParams(query);
  const fallback = defaultPeriod(view);
  const period = params.get("period") ?? fallback;
  return {
    period: periodOptions(view).some((p) => p === period) ? period : fallback,
    disease_group: params.get("disease_group") ?? "",
    host: params.get("host") ?? "",
    country: (params.get("country") ?? "").toUpperCase(),
    q: params.get("q") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
  };
}
function validDate(value: string) {
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}
export function invalidRange(filters: EventFilters) {
  return (
    filters.period === "custom" &&
    (!validDate(filters.from) ||
      !validDate(filters.to) ||
      filters.from > filters.to)
  );
}
export function filterEvents(
  events: readonly DashboardEvent[],
  filters: EventFilters,
  now: number,
) {
  if (invalidRange(filters)) return [];
  const hour = 3_600_000;
  const start =
    filters.period === "custom"
      ? Date.parse(`${filters.from}T00:00:00Z`)
      : filters.period === "today"
        ? Date.parse(`${new Date(now).toISOString().slice(0, 10)}T00:00:00Z`)
        : now - (ROLLING_HOURS[filters.period] ?? 168) * hour;
  const end =
    filters.period === "custom"
      ? Date.parse(`${filters.to}T23:59:59.999Z`)
      : now;
  const query = filters.q.trim().toLowerCase();
  return events
    .filter((event) => {
      const timestamp = Date.parse(event.latest_report_at);
      const text = [
        event.headline,
        event.summary,
        event.disease,
        diseaseGroupLabel(event.disease_group),
        hostSectorLabel(event.host_sector),
        countryName(event.country_code),
        event.country_code,
        event.admin1,
      ]
        .join(" ")
        .toLowerCase();
      return (
        timestamp >= start &&
        timestamp <= end &&
        (!query || text.includes(query)) &&
        (!filters.disease_group ||
          event.disease_group === filters.disease_group) &&
        (!filters.host ||
          event.host_sector === filters.host ||
          (["human", "animal"].includes(filters.host) &&
            event.host_sector === "both")) &&
        (!filters.country || event.country_code === filters.country)
      );
    })
    .sort(
      (a, b) => Date.parse(b.latest_report_at) - Date.parse(a.latest_report_at),
    );
}
