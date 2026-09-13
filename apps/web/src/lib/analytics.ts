const DISEASE_GROUPS = [
  "respiratory",
  "enteric_food_waterborne",
  "vector_borne",
  "vaccine_preventable",
  "viral_hemorrhagic_fever",
  "neurologic_invasive",
  "blood_borne_sti",
  "healthcare_associated_amr",
  "other_infectious",
  "unknown",
] as const;

const HOST_SECTORS = ["human", "animal", "both", "unknown"] as const;
const SOURCE_DOMAINS = [
  "who.int",
  "reuters.com",
  "africanews.com",
  "other",
] as const;
const VIEWS = ["map", "briefing"] as const;
const THEMES = ["light", "dark", "system"] as const;
const FILTERS = [
  "period",
  "disease_group",
  "host",
  "country",
  "status",
] as const;
const RESULT_BUCKETS = ["0", "1-5", "6-20", "20+"] as const;

export const analyticsEventNames = [
  "view_switch",
  "theme_change",
  "filter_change",
  "search_used",
  "map_event_open",
  "briefing_event_open",
  "reading_pane_open",
  "full_event_open",
  "source_click",
] as const;

export type DiseaseGroup = (typeof DISEASE_GROUPS)[number];
export type HostSector = (typeof HOST_SECTORS)[number];
export type SourceDomain = (typeof SOURCE_DOMAINS)[number];
export type SourceCountBucket = "0" | "1-5" | "6-20" | "20+";

export type AnalyticsEvent =
  | { name: "view_switch"; properties: { view: "map" | "briefing" } }
  | { name: "theme_change"; properties: { theme: "light" | "dark" | "system" } }
  | {
      name: "filter_change";
      properties: {
        filter: "period" | "disease_group" | "host" | "country" | "status";
      };
    }
  | { name: "search_used"; properties: { results_bucket: SourceCountBucket } }
  | {
      name: "map_event_open";
      properties: { disease_group: DiseaseGroup; host_sector: HostSector };
    }
  | {
      name: "briefing_event_open";
      properties: {
        disease_group: DiseaseGroup;
        host_sector: HostSector;
        source_count_bucket: SourceCountBucket;
      };
    }
  | { name: "reading_pane_open"; properties: Record<never, never> }
  | { name: "full_event_open"; properties: Record<never, never> }
  | { name: "source_click"; properties: { source_domain: SourceDomain } };

type UmamiTracker = {
  track: (payload: {
    website: string;
    url: string;
    title: string;
    name?: string;
    data?: Record<string, string>;
  }) => void;
};

declare global {
  interface Window {
    umami?: UmamiTracker;
  }
}

function isOneOf<T extends readonly string[]>(
  value: unknown,
  values: T,
): value is T[number] {
  return typeof value === "string" && values.includes(value as T[number]);
}

function pagePath(
  pathname: string,
): "/" | "/briefing" | "/events/:public_id" | null {
  if (pathname === "/") return "/";
  if (pathname === "/briefing") return "/briefing";
  if (pathname.startsWith("/events/")) return "/events/:public_id";
  return null;
}

function pageTitle(pathname: string) {
  if (pathname === "/") return "EpiSignal — Map";
  if (pathname === "/briefing") return "EpiSignal — Briefing";
  return "EpiSignal — Event";
}

function configuredWebsite() {
  const website = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
  const scriptUrl = process.env.NEXT_PUBLIC_UMAMI_SCRIPT_URL;
  return website && scriptUrl ? website : null;
}

export function diseaseGroupValue(
  value: string | null | undefined,
): DiseaseGroup {
  return isOneOf(value, DISEASE_GROUPS) ? value : "unknown";
}

export function hostSectorValue(value: string | null | undefined): HostSector {
  return isOneOf(value, HOST_SECTORS) ? value : "unknown";
}

export function countBucket(count: number): SourceCountBucket {
  if (count <= 0) return "0";
  if (count <= 5) return "1-5";
  if (count <= 20) return "6-20";
  return "20+";
}

export function sourceDomain(value: string): SourceDomain {
  try {
    const hostname = new URL(value).hostname
      .toLowerCase()
      .replace(/^www\./, "");
    return isOneOf(hostname, SOURCE_DOMAINS) && hostname !== "other"
      ? hostname
      : "other";
  } catch {
    return "other";
  }
}

function safeEvent(value: unknown): AnalyticsEvent | null {
  if (!value || typeof value !== "object") return null;
  const event = value as Record<string, unknown>;
  switch (event.name) {
    case "view_switch":
      return event.properties &&
        typeof event.properties === "object" &&
        isOneOf((event.properties as Record<string, unknown>).view, VIEWS)
        ? {
            name: event.name,
            properties: {
              view: (event.properties as { view: "map" | "briefing" }).view,
            },
          }
        : null;
    case "theme_change":
      return event.properties &&
        typeof event.properties === "object" &&
        isOneOf((event.properties as Record<string, unknown>).theme, THEMES)
        ? {
            name: event.name,
            properties: {
              theme: (
                event.properties as { theme: "light" | "dark" | "system" }
              ).theme,
            },
          }
        : null;
    case "filter_change":
      return event.properties &&
        typeof event.properties === "object" &&
        isOneOf((event.properties as Record<string, unknown>).filter, FILTERS)
        ? {
            name: event.name,
            properties: {
              filter: (event.properties as { filter: (typeof FILTERS)[number] })
                .filter,
            },
          }
        : null;
    case "search_used":
      return event.properties &&
        typeof event.properties === "object" &&
        isOneOf(
          (event.properties as Record<string, unknown>).results_bucket,
          RESULT_BUCKETS,
        )
        ? {
            name: event.name,
            properties: {
              results_bucket: (
                event.properties as { results_bucket: SourceCountBucket }
              ).results_bucket,
            },
          }
        : null;
    case "map_event_open":
      return event.properties && typeof event.properties === "object"
        ? {
            name: event.name,
            properties: {
              disease_group: diseaseGroupValue(
                (event.properties as Record<string, unknown>)
                  .disease_group as string,
              ),
              host_sector: hostSectorValue(
                (event.properties as Record<string, unknown>)
                  .host_sector as string,
              ),
            },
          }
        : null;
    case "briefing_event_open":
      return event.properties && typeof event.properties === "object"
        ? {
            name: event.name,
            properties: {
              disease_group: diseaseGroupValue(
                (event.properties as Record<string, unknown>)
                  .disease_group as string,
              ),
              host_sector: hostSectorValue(
                (event.properties as Record<string, unknown>)
                  .host_sector as string,
              ),
              source_count_bucket: isOneOf(
                (event.properties as Record<string, unknown>)
                  .source_count_bucket,
                RESULT_BUCKETS,
              )
                ? (
                    event.properties as {
                      source_count_bucket: SourceCountBucket;
                    }
                  ).source_count_bucket
                : "0",
            },
          }
        : null;
    case "reading_pane_open":
    case "full_event_open":
      return { name: event.name, properties: {} };
    case "source_click":
      return event.properties && typeof event.properties === "object"
        ? {
            name: event.name,
            properties: {
              source_domain: (() => {
                const value = String(
                  (event.properties as Record<string, unknown>).source_domain,
                );
                return isOneOf(value, SOURCE_DOMAINS)
                  ? value
                  : sourceDomain(value);
              })(),
            },
          }
        : null;
    default:
      return null;
  }
}

export function trackEvent(event: AnalyticsEvent): void {
  const website = configuredWebsite();
  if (
    typeof window === "undefined" ||
    !website ||
    typeof window.umami?.track !== "function"
  )
    return;
  const safe = safeEvent(event);
  if (!safe) return;
  const url = pagePath(window.location.pathname);
  if (!url) return;
  try {
    window.umami.track({
      website,
      url,
      title: pageTitle(window.location.pathname),
      name: safe.name,
      data: safe.properties as Record<string, string>,
    });
  } catch {
    // Analytics must never affect the application when a tracker is unavailable.
  }
}

export function trackPageView(pathname: string): void {
  const website = configuredWebsite();
  if (
    typeof window === "undefined" ||
    !website ||
    typeof window.umami?.track !== "function"
  )
    return;
  const url = pagePath(pathname);
  if (!url) return;
  try {
    window.umami.track({ website, url, title: pageTitle(pathname) });
  } catch {
    // Analytics must never affect the application when a tracker is unavailable.
  }
}

export function trackSearchUsed(resultCount: number): void {
  trackEvent({
    name: "search_used",
    properties: { results_bucket: countBucket(resultCount) },
  });
}
