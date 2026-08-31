"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import { EventMap } from "./event-map";

export type ApiShellStatus = "loading" | "ready" | "unavailable";

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking API",
  ready: "API connected",
  unavailable: "API unavailable",
};

function formatLabel(value: string) {
  return value.replaceAll("_", " ");
}

function dateLabel(value: string | null) {
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

function eventLocation(event: DashboardEvent) {
  return event.town ?? event.country_code ?? "Location unresolved";
}

function EventCard({ event }: { event: DashboardEvent }) {
  return (
    <Link
      href={`/events/${encodeURIComponent(event.public_id)}`}
      className="evidence-card block transition-all duration-200 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
      data-event-card="true"
      aria-label={`View event: ${event.headline}`}
    >
      <div className="flex flex-wrap gap-2 mb-2">
        {event.disease && (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-200">
            {event.disease}
          </span>
        )}
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
          {formatLabel(event.status)}
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
          {formatLabel(event.event_type)}
        </span>
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
          📍 {eventLocation(event)}
          {event.map_level ? ` (${event.map_level})` : ""}
        </span>
      </div>

      <h2 className="text-lg font-bold text-slate-900 mb-2">
        {event.headline}
      </h2>
      <p className="text-sm text-slate-700 mb-3 line-clamp-3">
        {event.summary}
      </p>

      <div className="flex flex-wrap gap-4 text-xs text-slate-500 mt-2">
        <time dateTime={event.first_reported_at ?? undefined}>
          First report {dateLabel(event.first_reported_at)}
        </time>
        <time dateTime={event.latest_report_at}>
          Latest report {dateLabel(event.latest_report_at)}
        </time>
        <span>{event.article_count} articles</span>
      </div>
      <div className="text-xs text-slate-500 mt-2">
        Summarized {dateLabel(event.last_summarized_at)}
      </div>
    </Link>
  );
}

export function HomeShell({
  apiStatus,
  eventFeed,
}: {
  apiStatus: ApiShellStatus;
  eventFeed: DashboardFeedState;
}) {
  const router = useRouter();
  const events = eventFeed.status === "ready" ? eventFeed.data.items : [];
  const mappedCount = events.filter(
    (event) =>
      (event.map_level === "town" || event.map_level === "country") &&
      event.latitude !== null &&
      event.longitude !== null,
  ).length;

  return (
    <>
      <header className="masthead">
        <Link className="brand" href="/">
          EpiSignal
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/events">Events</Link>
          <a href="#event-map">Map</a>
          <a href="#events-list">Events</a>
          <Link href="/admin/pipeline">Pipeline Monitor</Link>
          <Link href="/admin/reviews">Review Queue</Link>
          <a href="#about">About</a>
        </nav>
        <span className={`system-pill system-pill--${apiStatus}`}>
          {STATUS_LABELS[apiStatus]}
        </span>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <p className="eyebrow">Epidemiological Intelligence</p>
          <h1 id="hero-title">Summarized Events</h1>
          <p className="hero-intro">
            Traceable outbreak events assembled from public health reports and
            global media sources.
          </p>
        </section>

        <section id="event-map" className="map-section mb-8">
          <EventMap
            events={events}
            onSelect={(publicId) =>
              router.push(`/events/${encodeURIComponent(publicId)}`)
            }
          />
        </section>

        <section
          id="events-list"
          className="evidence-section"
          aria-labelledby="events-heading"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stored summaries</p>
              <h2 id="events-heading">All summarized events</h2>
            </div>
            {eventFeed.status === "ready" && (
              <p className="text-sm text-slate-500">
                {events.length} events · {mappedCount} mapped
              </p>
            )}
          </div>

          <div className="evidence-layout">
            <div className="evidence-list" aria-live="polite">
              {eventFeed.status === "loading" ? (
                <p className="empty-state">Loading summarized events…</p>
              ) : eventFeed.status === "unavailable" ? (
                <p className="empty-state">
                  Events unavailable. The API could not load summaries.
                </p>
              ) : events.length === 0 ? (
                <p className="empty-state">No summarized events stored.</p>
              ) : (
                events.map((event) => (
                  <EventCard key={event.public_id} event={event} />
                ))
              )}
            </div>
          </div>
        </section>

        <section
          id="about"
          className="about-strip mt-12 py-8 border-t border-slate-200"
          aria-label="About EpiSignal"
        >
          <p className="eyebrow">Evidence before claims</p>
          <p className="text-sm text-slate-600 max-w-2xl">
            EpiSignal shows only stored event summaries with traceable source
            provenance, report timing, and preserved observation history.
          </p>
        </section>
      </main>
    </>
  );
}
