"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getEventDetail, type EventDetailResponse } from "../lib/api-events";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import { EventMap } from "./event-map";

export type ApiShellStatus = "loading" | "ready" | "unavailable";
type HomeView = "map" | "calendar";

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking feed",
  ready: "Live feed",
  unavailable: "Feed unavailable",
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
  if (event.admin1) {
    return `${event.admin1}, ${event.country_code ?? "Unknown country"}`;
  }
  return event.country_code ?? "Location unresolved";
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

function relativeTimeLabel(value: string) {
  const minutes = Math.round((Date.now() - Date.parse(value)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

function isMapped(event: DashboardEvent) {
  return (
    (event.map_level === "admin1" || event.map_level === "country") &&
    typeof event.latitude === "number" &&
    typeof event.longitude === "number"
  );
}

function sortLatestFirst(events: readonly DashboardEvent[]) {
  return [...events].sort(
    (left, right) =>
      Date.parse(right.latest_report_at) - Date.parse(left.latest_report_at),
  );
}

function EventCard({
  event,
  onSelect,
}: {
  event: DashboardEvent;
  onSelect: (publicId: string) => void;
}) {
  return (
    <button
      type="button"
      className="event-card"
      data-event-card="true"
      onClick={() => onSelect(event.public_id)}
      aria-label={`View event: ${event.headline}`}
    >
      <div className="event-card__meta">
        <span className={`status-label status-label--${event.status}`}>
          {formatLabel(event.status)}
        </span>
        <span>{event.disease ?? "Disease not specified"}</span>
      </div>
      <h3>{event.headline}</h3>
      <p className="event-card__location">{eventLocation(event)}</p>
      <p className="event-card__summary">{event.summary}</p>
      <div className="event-card__footer">
        <span>{event.article_count} sources</span>
        <span>Updated {relativeTimeLabel(event.latest_report_at)}</span>
      </div>
    </button>
  );
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
        <span>{event.disease ?? "Disease not specified"}</span>
        <time dateTime={event.latest_report_at}>
          {relativeTimeLabel(event.latest_report_at)}
        </time>
      </div>
      <h3>{event.headline}</h3>
      <p className="event-card__location">{eventLocation(event)}</p>
      <p className="event-card__summary">{event.summary}</p>
      <div className="calendar-card__latest">
        <span>Latest development</span>
        <strong>Open event for full observation history</strong>
      </div>
      <div className="event-card__footer">
        <span>{event.article_count} sources</span>
        <span>Updated {dateTimeLabel(event.latest_report_at)}</span>
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
          <span>{event.disease ?? "Disease not specified"}</span>
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
        <p>
          {detailLoading
            ? "Loading latest development…"
            : (latestDevelopment ?? "No latest development recorded.")}
        </p>
      </div>
      <div className="event-detail-panel__footer">
        <span>{event.article_count} sources</span>
        <span>Updated {relativeTimeLabel(event.latest_report_at)}</span>
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
  disease,
  country,
  status,
  onSearch,
  onDisease,
  onCountry,
  onStatus,
}: {
  events: readonly DashboardEvent[];
  search: string;
  disease: string;
  country: string;
  status: string;
  onSearch: (value: string) => void;
  onDisease: (value: string) => void;
  onCountry: (value: string) => void;
  onStatus: (value: string) => void;
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
      <label className="search-field">
        <span>Search</span>
        <input
          type="search"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Search events or locations"
        />
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
    </section>
  );
}

function dateGroupKey(value: string) {
  return value.slice(0, 10);
}

function dateGroupLabel(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  const today = new Date();
  const todayKey = today.toISOString().slice(0, 10);
  if (value === todayKey) return "Today";
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
    const key = dateGroupKey(event.latest_report_at);
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
  const [disease, setDisease] = useState("");
  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
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
        const haystack = [event.headline, event.summary, eventLocation(event)]
          .join(" ")
          .toLowerCase();
        return (
          (!query || haystack.includes(query)) &&
          (!disease || event.disease === disease) &&
          (!country || event.country_code === country) &&
          (!status || event.status === status)
        );
      }),
    );
  }, [allEvents, country, disease, search, status]);

  const selectedEvent =
    events.find((event) => event.public_id === selectedId) ?? null;
  const mappedCount = allEvents.filter(isMapped).length;
  const activeCount = allEvents.filter((event) =>
    ACTIVE_STATUSES.has(event.status),
  ).length;
  const countryCount = new Set(
    allEvents.map((event) => event.country_code).filter(Boolean),
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
          disease={disease}
          country={country}
          status={status}
          onSearch={setSearch}
          onDisease={setDisease}
          onCountry={setCountry}
          onStatus={setStatus}
        />

        {view === "map" ? (
          <>
            <section className="map-view" aria-labelledby="map-heading">
              <div className="view-intro view-intro--map">
                <div>
                  <p className="eyebrow">Where things are happening</p>
                  <h1 id="map-heading">Global event map</h1>
                </div>
                <p>{events.length} visible events from summarized reporting.</p>
              </div>
              <div className="map-workspace">
                <div className="map-stage">
                  <EventMap
                    events={events}
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
                <aside
                  className="recent-events"
                  aria-labelledby="recent-heading"
                >
                  <div className="recent-events__heading">
                    <p className="eyebrow">Signal picture</p>
                    <h2 id="recent-heading">Recent events</h2>
                  </div>
                  <div className="recent-events__list" aria-live="polite">
                    {eventFeed.status === "loading" ? (
                      <p className="empty-state">Loading summarized events…</p>
                    ) : eventFeed.status === "unavailable" ? (
                      <p className="empty-state">
                        Events unavailable. The API could not load summaries.
                      </p>
                    ) : events.length === 0 ? (
                      <p className="empty-state">
                        No events match these filters.
                      </p>
                    ) : (
                      events.map((event) => (
                        <EventCard
                          key={event.public_id}
                          event={event}
                          onSelect={selectEvent}
                        />
                      ))
                    )}
                  </div>
                </aside>
              </div>
            </section>
            <section className="stats-strip" aria-label="Event overview">
              <div>
                <strong>{allEvents.length}</strong>
                <span>Total events</span>
              </div>
              <div>
                <strong>{activeCount}</strong>
                <span>Active events</span>
              </div>
              <div>
                <strong>{countryCount}</strong>
                <span>Countries</span>
              </div>
              <div>
                <strong>{mappedCount}</strong>
                <span>Mapped events</span>
              </div>
            </section>
          </>
        ) : (
          <CalendarView events={events} />
        )}
      </main>
    </div>
  );
}
