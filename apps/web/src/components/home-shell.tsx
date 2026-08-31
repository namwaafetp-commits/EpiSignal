"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  getEventDetail,
  relativeTimeLabel,
  type EventDetailResponse,
} from "../lib/api-events";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import { formatCountryLocation } from "../lib/country";
import { EventMap, type EventMapRegion } from "./event-map";

export type ApiShellStatus = "loading" | "ready" | "unavailable";
type HomeView = "map" | "calendar";
type TimeRange = "24h" | "7d" | "30d" | "custom";
type Region = EventMapRegion;

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking feed",
  ready: "Live feed",
  unavailable: "Feed unavailable",
};

const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: "24h", label: "24H" },
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "custom", label: "Custom" },
];

const REGIONS: { value: Region; label: string }[] = [
  { value: "", label: "All regions" },
  { value: "Africa", label: "Africa" },
  { value: "Asia", label: "Asia" },
  { value: "Europe", label: "Europe" },
  { value: "North America", label: "North America" },
  { value: "South America", label: "South America" },
  { value: "Oceania", label: "Oceania" },
  { value: "ASEAN", label: "ASEAN" },
];

const ASEAN_COUNTRIES = new Set([
  "BN",
  "KH",
  "ID",
  "LA",
  "MY",
  "MM",
  "PH",
  "SG",
  "TH",
  "TL",
  "VN",
]);

const REGION_COUNTRIES: Record<Exclude<Region, "" | "ASEAN">, Set<string>> = {
  Africa: new Set(
    "AO BF BI BJ BW CD CF CG CI CM CV DJ DZ EG ER ET GA GH GM GN GQ GW KE KM LR LS LY MA MG ML MR MU MW MZ NA NE NG RW SC SD SH SL SN SO SS ST SZ TD TG TN TZ UG YT ZA ZM ZW".split(
      " ",
    ),
  ),
  Asia: new Set(
    "AF AM AZ BD BH BN BT CN CY GE ID IL IN IQ IR JO JP KG KH KP KR KW KZ LA LB LK MM MN MY MV NP OM PH PK PS QA RU SA SG SY TH TJ TL TM TR TW UZ VN YE".split(
      " ",
    ),
  ),
  Europe: new Set(
    "AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FR GB GR HR HU IE IS IT LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SK SM UA VA XK".split(
      " ",
    ),
  ),
  "North America": new Set(
    "AG BB BS BZ CA CR CU DM DO GD GT HN HT JM KN LC MX NI PA PM PR SV TT US VC".split(
      " ",
    ),
  ),
  "South America": new Set(
    "AR BO BR CL CO EC FK GF GY PE PY SR UY VE".split(" "),
  ),
  Oceania: new Set(
    "AS AU CK FJ FM GU KI MH MP NC NF NR NU NZ PF PG PW SB TK TO TV VU WF WS".split(
      " ",
    ),
  ),
};

const ACTIVE_STATUSES = new Set([
  "monitoring",
  "ongoing",
  "expanding",
  "stable",
  "declining",
]);

function formatLabel(value: string) {
  return value.replaceAll("_", " ");
}

function eventLocation(event: DashboardEvent) {
  return formatCountryLocation(event.admin1, event.country_code);
}

function dateTimeLabel(value: string | null) {
  if (!value) return "Not reported";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

function isMapped(event: DashboardEvent) {
  return (
    (event.map_level === "admin1" || event.map_level === "country") &&
    typeof event.latitude === "number" &&
    typeof event.longitude === "number"
  );
}

function eventDate(event: DashboardEvent) {
  return event.latest_report_at || event.last_summarized_at;
}

function isInRegion(countryCode: string | null, region: Region) {
  if (!region) return true;
  if (!countryCode) return false;
  if (region === "ASEAN") return ASEAN_COUNTRIES.has(countryCode);
  return REGION_COUNTRIES[region].has(countryCode);
}

function isInTimeRange(
  event: DashboardEvent,
  timeRange: TimeRange,
  customRange: DateRange,
) {
  const timestamp = Date.parse(eventDate(event));
  if (Number.isNaN(timestamp)) return false;
  const now = Date.now();
  if (timeRange === "24h")
    return timestamp >= now - 24 * 60 * 60 * 1000 && timestamp <= now;
  if (timeRange === "7d")
    return timestamp >= now - 7 * 24 * 60 * 60 * 1000 && timestamp <= now;
  if (timeRange === "30d")
    return timestamp >= now - 30 * 24 * 60 * 60 * 1000 && timestamp <= now;
  if (!customRange.from || !customRange.to) return true;
  const from = Date.parse(`${customRange.from}T00:00:00Z`);
  const to = Date.parse(`${customRange.to}T23:59:59.999Z`);
  return timestamp >= from && timestamp <= to;
}

function sortLatestFirst(events: readonly DashboardEvent[]) {
  return [...events].sort(
    (left, right) => Date.parse(eventDate(right)) - Date.parse(eventDate(left)),
  );
}

interface DateRange {
  from: string;
  to: string;
}

function initialDateRange(): DateRange {
  const today = new Date();
  const from = new Date(today);
  from.setUTCDate(from.getUTCDate() - 7);
  return {
    from: from.toISOString().slice(0, 10),
    to: today.toISOString().slice(0, 10),
  };
}

function CalendarCard({ event }: { event: DashboardEvent }) {
  return (
    <Link
      href={`/events/${encodeURIComponent(event.public_id)}`}
      className="calendar-card"
      aria-label={`Open event: ${event.headline}`}
    >
      <div className="event-card__meta">
        <span className={`status-label status-label--${event.status}`}>
          {formatLabel(event.status)}
        </span>
        <span>{event.disease ?? "Unknown disease"}</span>
        <time dateTime={eventDate(event)}>
          {relativeTimeLabel(eventDate(event))}
        </time>
      </div>
      <h3>{event.headline}</h3>
      <p className="event-card__location">{eventLocation(event)}</p>
      <p className="event-card__summary">{event.summary}</p>
      <div className="calendar-card__latest">
        <span>Latest development</span>
        <strong>Available on the full event page</strong>
      </div>
      <div className="event-card__footer">
        <span>{event.article_count} sources</span>
        <span>Updated {dateTimeLabel(eventDate(event))}</span>
      </div>
    </Link>
  );
}

function EventDetailPanel({
  event,
  detail,
  detailLoading,
  onClose,
}: {
  event: DashboardEvent;
  detail: EventDetailResponse | null;
  detailLoading: boolean;
  onClose: () => void;
}) {
  const latestDevelopment = detail?.summaries[0]?.latest_development;

  return (
    <aside
      className="event-detail-panel"
      role="dialog"
      aria-label="Event details"
    >
      <div className="event-detail-panel__header">
        <div className="event-card__meta">
          <span className={`status-label status-label--${event.status}`}>
            {formatLabel(event.status)}
          </span>
          <span aria-hidden="true">·</span>
          <span>{event.disease ?? "Unknown disease"}</span>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="Close event details"
        >
          Close
        </button>
      </div>
      <h2>{event.headline}</h2>
      <p className="event-detail-panel__location">{eventLocation(event)}</p>
      <p className="event-detail-panel__summary">{event.summary}</p>
      <div className="event-detail-panel__development">
        <span>Latest development</span>
        <p className="line-clamp-2">
          {detailLoading
            ? "Loading latest development…"
            : (latestDevelopment ?? "No latest development recorded.")}
        </p>
      </div>
      <div className="event-detail-panel__sources">
        <span>Sources</span>
        {detailLoading ? (
          <p>Loading source links…</p>
        ) : detail?.sources.length ? (
          <>
            <div className="event-detail-panel__source-links">
              {detail.sources.slice(0, 3).map((source) => (
                <a
                  key={source.signal_id}
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {source.source_name} ↗
                </a>
              ))}
            </div>
            {detail.sources.length > 3 && (
              <p>+{detail.sources.length - 3} more sources</p>
            )}
          </>
        ) : (
          <p>No source links available.</p>
        )}
      </div>
      <div className="event-detail-panel__footer">
        <span>{detail?.sources.length ?? event.article_count} sources</span>
        <span>Updated {relativeTimeLabel(eventDate(event))}</span>
      </div>
      <Link
        href={`/events/${encodeURIComponent(event.public_id)}`}
        className="primary-action"
      >
        View full event
      </Link>
    </aside>
  );
}

function FilterBar({
  events,
  search,
  region,
  disease,
  country,
  status,
  timeRange,
  customDraft,
  onSearch,
  onRegion,
  onDisease,
  onCountry,
  onStatus,
  onTimeRange,
  onCustomDraft,
  onApplyCustom,
}: {
  events: readonly DashboardEvent[];
  search: string;
  region: Region;
  disease: string;
  country: string;
  status: string;
  timeRange: TimeRange;
  customDraft: DateRange;
  onSearch: (value: string) => void;
  onRegion: (value: Region) => void;
  onDisease: (value: string) => void;
  onCountry: (value: string) => void;
  onStatus: (value: string) => void;
  onTimeRange: (value: TimeRange) => void;
  onCustomDraft: (value: DateRange) => void;
  onApplyCustom: () => void;
}) {
  const diseases = [
    ...new Set(
      events
        .map((event) => event.disease)
        .filter((value): value is string => Boolean(value)),
    ),
  ].sort();
  const countries = [
    ...new Set(
      events
        .map((event) => event.country_code)
        .filter((value): value is string => Boolean(value)),
    ),
  ].sort();
  const statuses = [...new Set(events.map((event) => event.status))].sort();

  return (
    <section className="filter-bar" aria-label="Event filters">
      <div className="filter-bar__selects">
        <label className="search-field">
          <span>Search</span>
          <input
            type="search"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Search headline, disease, country, or region"
          />
        </label>
        <label>
          <span>Region</span>
          <select
            value={region}
            onChange={(event) => onRegion(event.target.value as Region)}
          >
            {REGIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Disease</span>
          <select
            value={disease}
            onChange={(event) => onDisease(event.target.value)}
          >
            <option value="">All diseases</option>
            {diseases.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Country</span>
          <select
            value={country}
            onChange={(event) => onCountry(event.target.value)}
          >
            <option value="">All countries</option>
            {countries.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select
            value={status}
            onChange={(event) => onStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            {statuses.map((value) => (
              <option key={value} value={value}>
                {formatLabel(value)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="time-filter">
        <legend>Time range</legend>
        <div className="time-filter__buttons">
          {TIME_RANGES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={timeRange === option.value}
              className={timeRange === option.value ? "is-active" : ""}
              onClick={() => onTimeRange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        {timeRange === "custom" && (
          <div className="custom-range">
            <label>
              <span>From</span>
              <input
                type="date"
                value={customDraft.from}
                onChange={(event) =>
                  onCustomDraft({ ...customDraft, from: event.target.value })
                }
              />
            </label>
            <label>
              <span>To</span>
              <input
                type="date"
                value={customDraft.to}
                onChange={(event) =>
                  onCustomDraft({ ...customDraft, to: event.target.value })
                }
              />
            </label>
            <button
              type="button"
              className="apply-filter"
              onClick={onApplyCustom}
            >
              Apply
            </button>
          </div>
        )}
      </fieldset>
    </section>
  );
}

function dateGroupKey(value: string) {
  return value.slice(0, 10);
}

function dateGroupLabel(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  const todayKey = new Date().toISOString().slice(0, 10);
  if (value === todayKey) return "TODAY";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  })
    .format(date)
    .toUpperCase();
}

function CalendarView({ events }: { events: readonly DashboardEvent[] }) {
  const groups = new Map<string, DashboardEvent[]>();
  for (const event of events) {
    const key = dateGroupKey(eventDate(event));
    const group = groups.get(key) ?? [];
    group.push(event);
    groups.set(key, group);
  }

  return (
    <section className="calendar-view" aria-labelledby="calendar-heading">
      <div className="view-intro">
        <div>
          <p className="eyebrow">Chronological surveillance feed</p>
          <h1 id="calendar-heading">Surveillance calendar</h1>
        </div>
        <p>Newest reports first. Each event keeps its reporting history.</p>
      </div>
      {events.length === 0 ? (
        <p className="empty-state">No events match these filters.</p>
      ) : (
        <div className="calendar-groups">
          {[...groups.entries()].map(([date, group]) => (
            <section
              key={date}
              className="calendar-group"
              aria-labelledby={`date-${date}`}
            >
              <h2 id={`date-${date}`}>{dateGroupLabel(date)}</h2>
              <div className="calendar-group__events">
                {group.map((event) => (
                  <CalendarCard key={event.public_id} event={event} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export function HomeShell({
  apiStatus,
  eventFeed,
}: {
  apiStatus: ApiShellStatus;
  eventFeed: DashboardFeedState;
}) {
  const [view, setView] = useState<HomeView>("map");
  const [search, setSearch] = useState("");
  const [region, setRegion] = useState<Region>("");
  const [disease, setDisease] = useState("");
  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
  const [timeRange, setTimeRange] = useState<TimeRange>("7d");
  const [customRange, setCustomRange] = useState<DateRange>(initialDateRange);
  const [customDraft, setCustomDraft] = useState<DateRange>(initialDateRange);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<{
    id: string;
    data: EventDetailResponse | null;
  } | null>(null);

  const allEvents = useMemo(
    () => (eventFeed.status === "ready" ? eventFeed.data.items : []),
    [eventFeed],
  );
  const events = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sortLatestFirst(
      allEvents.filter((event) => {
        const haystack = [
          event.headline,
          event.summary,
          event.disease,
          event.country_code,
          event.admin1,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return (
          (!query || haystack.includes(query)) &&
          isInRegion(event.country_code, region) &&
          (!disease || event.disease === disease) &&
          (!country || event.country_code === country) &&
          (!status || event.status === status) &&
          isInTimeRange(event, timeRange, customRange)
        );
      }),
    );
  }, [
    allEvents,
    country,
    customRange,
    disease,
    region,
    search,
    status,
    timeRange,
  ]);

  const selectedEvent =
    events.find((event) => event.public_id === selectedId) ?? null;
  const mappedCount = events.filter(isMapped).length;
  const activeCount = events.filter((event) =>
    ACTIVE_STATUSES.has(event.status),
  ).length;
  const countryCount = new Set(
    events.map((event) => event.country_code).filter(Boolean),
  ).size;

  useEffect(() => {
    if (!selectedId) return;

    let current = true;
    getEventDetail(selectedId).then((detail) => {
      if (!current) return;
      setDetailState({ id: selectedId, data: detail });
    });
    return () => {
      current = false;
    };
  }, [selectedId]);

  const selectedDetail =
    selectedId && detailState?.id === selectedId ? detailState.data : null;
  const detailLoading = Boolean(selectedId && detailState?.id !== selectedId);

  function selectEvent(publicId: string) {
    setSelectedId(publicId);
  }

  function selectTimeRange(value: TimeRange) {
    setTimeRange(value);
    if (value === "custom") setCustomDraft(customRange);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" href="/">
          <span className="brand-mark" aria-hidden="true" />
          EpiSignal
        </Link>
        <nav className="view-tabs" aria-label="Homepage views">
          <button
            type="button"
            className={view === "map" ? "is-active" : ""}
            aria-pressed={view === "map"}
            onClick={() => setView("map")}
          >
            Map
          </button>
          <button
            type="button"
            className={view === "calendar" ? "is-active" : ""}
            aria-pressed={view === "calendar"}
            onClick={() => setView("calendar")}
          >
            Calendar
          </button>
        </nav>
        <div className={`feed-status feed-status--${apiStatus}`}>
          <span className="feed-status__dot" aria-hidden="true" />
          {STATUS_LABELS[apiStatus]}
        </div>
      </header>

      <main className="home-main">
        <FilterBar
          events={allEvents}
          search={search}
          region={region}
          disease={disease}
          country={country}
          status={status}
          timeRange={timeRange}
          customDraft={customDraft}
          onSearch={setSearch}
          onRegion={setRegion}
          onDisease={setDisease}
          onCountry={setCountry}
          onStatus={setStatus}
          onTimeRange={selectTimeRange}
          onCustomDraft={setCustomDraft}
          onApplyCustom={() => setCustomRange(customDraft)}
        />

        {view === "map" ? (
          <>
            <section className="map-view" aria-labelledby="map-heading">
              <div className="view-intro view-intro--map">
                <div>
                  <p className="eyebrow">Where things are happening</p>
                  <h1 id="map-heading">Global event map</h1>
                </div>
                <p>{events.length} events in current view.</p>
              </div>
              <div className="map-stage">
                <EventMap
                  events={events}
                  region={region}
                  selectedId={selectedId}
                  onSelect={selectEvent}
                />
                {selectedEvent && (
                  <EventDetailPanel
                    event={selectedEvent}
                    detail={selectedDetail}
                    detailLoading={detailLoading}
                    onClose={() => setSelectedId(null)}
                  />
                )}
              </div>
              {eventFeed.status === "loading" ? (
                <p className="map-feed-message">Loading summarized events…</p>
              ) : eventFeed.status === "unavailable" ? (
                <p className="map-feed-message">
                  Events unavailable. The API could not load summaries.
                </p>
              ) : events.length === 0 ? (
                <p className="map-feed-message">
                  No events match these filters.
                </p>
              ) : null}
              <p className="map-stats" aria-label="Filtered event statistics">
                {events.length} EVENTS · {mappedCount} MAPPED · {countryCount}{" "}
                COUNTRIES · {activeCount} ACTIVE
              </p>
            </section>
          </>
        ) : (
          <CalendarView events={events} />
        )}
      </main>
    </div>
  );
}
