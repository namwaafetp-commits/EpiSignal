"use client";

import Link from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { X } from "lucide-react";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import {
  getEventDetail,
  relativeTimeLabel,
  type EventDetailResponse,
} from "../lib/api-events";
import {
  defaultPeriod,
  filterEvents,
  invalidRange,
  readFilters,
  type EventFilters,
} from "../lib/event-filters";
import { countryName } from "../lib/country";
import { diseaseGroupLabel, hostSectorLabel } from "../lib/surveillance-labels";
import { EventBrief, SourceList } from "./event-content";
import { EventMap } from "./event-map";
import { FilterBar } from "./event-filters";
import { BriefingFeed } from "./briefing-feed";
import {
  diseaseGroupValue,
  hostSectorValue,
  countBucket,
  trackEvent,
  trackSearchUsed,
} from "../lib/analytics";

export type ApiShellStatus = "loading" | "ready" | "unavailable";
type View = "map" | "briefing";
const APP_BOOT_TIME = Date.now();

function initialFilters(initialQuery: string, view: View) {
  if (initialQuery) return readFilters(initialQuery, view);
  return readFilters(
    typeof window === "undefined" ? "" : window.location.search,
    view,
  );
}

function serializeFilters(filters: EventFilters, view: View) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (!value || (key === "period" && value === defaultPeriod(view))) continue;
    if (filters.period !== "custom" && (key === "from" || key === "to"))
      continue;
    params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function HomeShell({
  apiStatus,
  eventFeed,
  view = "map",
  initialQuery = "",
  now = APP_BOOT_TIME,
}: {
  apiStatus: ApiShellStatus;
  eventFeed: DashboardFeedState;
  view?: View;
  initialQuery?: string;
  now?: number;
}) {
  const [filters, setFilters] = useState(() =>
    initialFilters(initialQuery, view),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<{
    id: string;
    data: EventDetailResponse | null;
  } | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const openerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const allEvents = useMemo(
    () => (eventFeed.status === "ready" ? eventFeed.data.items : []),
    [eventFeed],
  );
  const events = useMemo(
    () => filterEvents(allEvents, filters, now),
    [allEvents, filters, now],
  );
  const selectedEvent =
    allEvents.find((event) => event.public_id === selectedId) ?? null;
  const detail =
    selectedId && detailState?.id === selectedId ? detailState.data : null;
  const detailLoading = Boolean(selectedId && detailState?.id !== selectedId);
  const query = serializeFilters(filters, view);

  useEffect(() => {
    const onPopState = () => {
      setFilters(readFilters(window.location.search, view));
      setSelectedId(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [view]);

  useEffect(() => {
    const root = document.documentElement;
    const update = () =>
      setTheme(root.dataset.theme === "dark" ? "dark" : "light");
    update();
    const observer = new MutationObserver(update);
    observer.observe(root, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    getEventDetail(selectedId).then((data) => {
      if (active) setDetailState({ id: selectedId, data });
    });
    closeRef.current?.focus();
    return () => {
      active = false;
    };
  }, [selectedId]);

  function updateFilter(key: keyof EventFilters, value: string) {
    setFilters((current) => {
      let next = { ...current, [key]: value };
      if (
        key === "period" &&
        value === "custom" &&
        (!current.from || !current.to)
      ) {
        const to = new Date().toISOString().slice(0, 10);
        const fromDate = new Date(`${to}T00:00:00Z`);
        fromDate.setUTCDate(fromDate.getUTCDate() - 7);
        next = { ...next, from: fromDate.toISOString().slice(0, 10), to };
      }
      const url = `${view === "briefing" ? "/briefing" : "/"}${serializeFilters(next, view)}`;
      if (key === "q" || key === "from" || key === "to")
        window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
      return next;
    });
    if (
      key === "period" ||
      key === "disease_group" ||
      key === "host" ||
      key === "country"
    ) {
      trackEvent({ name: "filter_change", properties: { filter: key } });
    }
    if (key === "q") {
      trackSearchUsed(
        filterEvents(allEvents, { ...filters, q: value }, now).length,
      );
    }
    setSelectedId(null);
  }

  function resetFilters() {
    setFilters(readFilters("", view));
    setSelectedId(null);
    window.history.pushState(null, "", view === "briefing" ? "/briefing" : "/");
  }

  function selectEvent(id: string) {
    openerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setDetailState(null);
    setSelectedId(id);
    const event = allEvents.find((item) => item.public_id === id);
    trackEvent({ name: "reading_pane_open", properties: {} });
    if (event && view === "map") {
      trackEvent({
        name: "map_event_open",
        properties: {
          disease_group: diseaseGroupValue(event.disease_group),
          host_sector: hostSectorValue(event.host_sector),
        },
      });
    }
    if (event && view === "briefing") {
      trackEvent({
        name: "briefing_event_open",
        properties: {
          disease_group: diseaseGroupValue(event.disease_group),
          host_sector: hostSectorValue(event.host_sector),
          source_count_bucket: countBucket(event.article_count),
        },
      });
    }
  }

  function closePane() {
    setSelectedId(null);
    openerRef.current?.focus();
  }

  const statusText =
    apiStatus === "ready"
      ? "Live reporting"
      : apiStatus === "loading"
        ? "Checking feed"
        : "Feed unavailable";
  return (
    <main id="main-content" className={`v2-page v2-page--${view}`}>
      <header className="v2-page-header">
        <div>
          <p className="eyebrow">Global infectious-disease intelligence</p>
          <h1>
            {view === "briefing" ? "The Briefing" : "Outbreaks, in context."}
          </h1>
          <p>
            {view === "briefing"
              ? "A live editorial record of events requiring attention."
              : "Reported infectious-disease events, mapped with their source trail intact."}
          </p>
        </div>
        <div className={`feed-indicator feed-indicator--${apiStatus}`}>
          <span aria-hidden="true" />
          {statusText}
        </div>
      </header>
      <FilterBar
        events={allEvents}
        filters={filters}
        onChange={updateFilter}
        onReset={resetFilters}
        view={view}
      />
      {eventFeed.status === "loading" ? (
        <FeedMessage>Loading summarized events…</FeedMessage>
      ) : eventFeed.status === "unavailable" ? (
        <FeedMessage>
          Events unavailable. The API could not load summaries.
        </FeedMessage>
      ) : invalidRange(filters) ? null : events.length === 0 ? (
        <FeedMessage>
          No events match these filters.
          <button
            type="button"
            className="feed-message__reset"
            onClick={resetFilters}
          >
            Reset filters
          </button>
        </FeedMessage>
      ) : view === "map" ? (
        <section className="map-workspace" aria-labelledby="map-view-heading">
          <div className="map-caption">
            <h2 id="map-view-heading">Global event map</h2>
            <p>
              {events.length} event{events.length === 1 ? "" : "s"} ·{" "}
              {new Set(events.map((e) => e.country_code).filter(Boolean)).size}{" "}
              countries
            </p>
          </div>
          <div className="map-stage">
            <EventMap
              events={events}
              region=""
              selectedId={selectedId}
              onSelect={selectEvent}
              onReset={() => setSelectedId(null)}
              theme={theme}
            />
            {selectedEvent && (
              <ReadingPane
                event={selectedEvent}
                detail={detail}
                loading={detailLoading}
                query={query}
                onClose={closePane}
                closeRef={closeRef}
              />
            )}
          </div>
          <div className="map-alternative">
            <h2>Events in view</h2>
            {events.slice(0, 8).map((event) => (
              <Link
                key={event.public_id}
                href={`/events/${encodeURIComponent(event.public_id)}${query}`}
                onClick={() =>
                  trackEvent({ name: "full_event_open", properties: {} })
                }
              >
                {event.headline}
                <span>{eventLocation(event)}</span>
              </Link>
            ))}
          </div>
        </section>
      ) : (
        <div
          className={`briefing-layout ${selectedEvent ? "has-reading-pane" : ""}`}
        >
          <BriefingFeed
            events={events}
            selectedId={selectedId}
            onSelect={selectEvent}
            query={query}
            now={now}
          />
          {selectedEvent && (
            <ReadingPane
              event={selectedEvent}
              detail={detail}
              loading={detailLoading}
              query={query}
              onClose={closePane}
              closeRef={closeRef}
            />
          )}
        </div>
      )}
    </main>
  );
}

function FeedMessage({ children }: { children: ReactNode }) {
  return (
    <div className="feed-message" role="status">
      {children}
    </div>
  );
}

function ReadingPane({
  event,
  detail,
  loading,
  query,
  onClose,
  closeRef,
}: {
  event: DashboardEvent;
  detail: EventDetailResponse | null;
  loading: boolean;
  query: string;
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <aside
      className="reading-pane"
      role="dialog"
      aria-label="Event details"
      aria-modal="false"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <button
        ref={closeRef}
        type="button"
        className="reading-pane__close"
        onClick={onClose}
        aria-label="Close event details"
      >
        <X size={20} aria-hidden="true" />
      </button>
      <p className="reading-pane__kicker">
        {diseaseGroupLabel(event.disease_group)} ·{" "}
        {hostSectorLabel(event.host_sector)}
      </p>
      <p className="reading-pane__location">{eventLocation(event)}</p>
      <h2>{event.headline}</h2>
      <p className="reading-pane__facts">
        Updated {relativeTimeLabel(event.latest_report_at)} ·{" "}
        {event.article_count} source{event.article_count === 1 ? "" : "s"}
      </p>
      <EventBrief event={detail ?? event} />
      {loading ? (
        <p className="reading-pane__loading" aria-live="polite">
          Loading source links…
        </p>
      ) : detail ? (
        <SourceList sources={detail.sources.slice(0, 5)} />
      ) : (
        <p className="reading-pane__loading">
          Source details are temporarily unavailable.
        </p>
      )}
      <Link
        className="primary-action"
        href={`/events/${encodeURIComponent(event.public_id)}${query}`}
        onClick={() => trackEvent({ name: "full_event_open", properties: {} })}
      >
        View full event
      </Link>
    </aside>
  );
}

function eventLocation(event: Pick<DashboardEvent, "admin1" | "country_code">) {
  const country = countryName(event.country_code);
  return event.admin1 ? `${event.admin1}, ${country}` : country;
}
