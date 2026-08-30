"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type {
  BriefPoint,
  RadarEventContext,
  RadarEventGroup,
  RadarFeedState,
  RadarItem,
} from "../lib/api-radar";
import { SignalMap } from "./signal-map";

export type ApiShellStatus = "loading" | "ready" | "unavailable";

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking API",
  ready: "API connected",
  unavailable: "API unavailable",
};

const SLOT_TITLES: Record<string, string> = {
  what_where: "What & Where",
  counts: "Case Counts",
  timing: "Timeline",
  spread: "Geographic Spread",
  reporting: "Reporting Source",
};

function formatSourceBadge(isOfficial: boolean) {
  return isOfficial ? "Official Source" : "Media Source";
}

function formatVerificationStatus(status: string) {
  switch (status) {
    case "officially_confirmed":
      return "Officially Confirmed";
    case "high_credibility":
      return "High Credibility Event";
    case "signal":
      return "Early Signal Event";
    case "unverified":
      return "Unverified Event";
    case "rumor_monitoring":
      return "Rumor Monitoring";
    default:
      return status;
  }
}

function dateLabel(value: string | null) {
  if (!value) return "Publication date unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

function BriefSlots({ brief }: { brief: readonly BriefPoint[] }) {
  return (
    <>
      {brief.map((slot) => (
        <div key={slot.slot} className="slot-point">
          <span className="font-semibold text-slate-700 mr-2">
            [{SLOT_TITLES[slot.slot] || slot.slot}]:
          </span>
          <span
            className={
              slot.reported ? "text-slate-900" : "text-slate-500 italic"
            }
          >
            {slot.text}
          </span>
        </div>
      ))}
    </>
  );
}

function AttachedEventContext({ event }: { event: RadarEventContext }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-bold text-amber-950">
          Outbreak Event: {event.public_id}
        </span>
        <span className="px-1.5 py-0.5 rounded bg-amber-100 font-medium text-amber-900">
          {formatVerificationStatus(event.verification_status)}
        </span>
      </div>
      <div className="flex gap-4 text-amber-900 pt-1">
        {event.early_signal_score !== null && (
          <span>
            Surveillance Interest:{" "}
            <strong>{Math.round(event.early_signal_score * 100)}%</strong>
          </span>
        )}
        {event.evidence_score !== null && (
          <span>
            Evidence Support:{" "}
            <strong>{Math.round(event.evidence_score * 100)}%</strong>
          </span>
        )}
      </div>
    </div>
  );
}

export function HomeShell({
  apiStatus,
  radarFeed,
}: {
  apiStatus: ApiShellStatus;
  radarFeed: RadarFeedState;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());

  const statusLabel = STATUS_LABELS[apiStatus];
  const items: RadarItem[] =
    radarFeed.status === "ready" ? radarFeed.data.items : [];
  const eventGroups: RadarEventGroup[] =
    radarFeed.status === "ready" ? radarFeed.data.event_groups : [];
  const groupedSignalCount = eventGroups.reduce(
    (sum, group) => sum + group.signal_count,
    0,
  );
  const totalSignalCount = items.length + groupedSignalCount;

  useEffect(() => {
    if (selectedId) {
      const card = cardRefs.current.get(selectedId);
      if (card && typeof card.scrollIntoView === "function") {
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }
  }, [selectedId]);

  return (
    <>
      <header className="masthead">
        <Link className="brand" href="/">
          EpiSignal
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/events">Events</Link>
          <a href="#radar-map">Map</a>
          <a href="#signals-list">Signals</a>
          <Link href="/admin/pipeline">Pipeline Monitor</Link>
          <Link href="/admin/reviews">Review Queue</Link>
          <a href="#about">About</a>
        </nav>
        <span className={`system-pill system-pill--${apiStatus}`}>
          {statusLabel}
        </span>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <p className="eyebrow">Real-Time Epidemiological Intelligence</p>
          <h1 id="hero-title">Early Signal Radar</h1>
          <p className="hero-intro">
            Continuous surveillance and 5-slot brief extraction of infectious
            disease signals from official public health agencies and global
            media sources.
          </p>
        </section>

        <section id="radar-map" className="map-section mb-8">
          <SignalMap
            items={items}
            groups={eventGroups}
            selectedId={selectedId}
            onSelect={(id) => setSelectedId(id)}
          />
        </section>

        <section
          id="signals-list"
          className="evidence-section"
          aria-labelledby="signals-heading"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Recent Signals</p>
              <h2 id="signals-heading">Extracted Outbreak Briefs</h2>
            </div>
            {radarFeed.status === "ready" && (
              <p className="text-sm text-slate-500">
                {totalSignalCount} signals in 48h surveillance window
              </p>
            )}
          </div>

          <div className="evidence-layout">
            <div className="evidence-list" aria-live="polite">
              {radarFeed.status === "loading" ? (
                <p className="empty-state">Loading recent signals…</p>
              ) : radarFeed.status === "unavailable" ? (
                <p className="empty-state">
                  Signals unavailable. The API could not load recent signals.
                </p>
              ) : totalSignalCount === 0 ? (
                <p className="empty-state">
                  No signals found in the selected window.
                </p>
              ) : (
                <>
                  {eventGroups.map((group) => {
                    const isSelected = group.event_public_id === selectedId;
                    return (
                      <article
                        key={group.event_public_id}
                        ref={(el) => {
                          if (el)
                            cardRefs.current.set(group.event_public_id, el);
                          else cardRefs.current.delete(group.event_public_id);
                        }}
                        tabIndex={0}
                        role="button"
                        aria-pressed={isSelected}
                        aria-label={`Select signal: ${group.representative_title}`}
                        data-event-group="true"
                        className={`evidence-card cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                          isSelected
                            ? "ring-2 ring-blue-600 bg-blue-50/20"
                            : "hover:border-slate-300"
                        }`}
                        data-selected={isSelected ? "true" : "false"}
                        onClick={() => setSelectedId(group.event_public_id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelectedId(group.event_public_id);
                          }
                        }}
                      >
                        <div className="evidence-meta">
                          <span className="font-semibold text-slate-900">
                            {group.all_source_names.join(" · ")}
                          </span>
                          <div className="evidence-dates">
                            <time
                              dateTime={
                                group.earliest_published_at ?? undefined
                              }
                            >
                              First published{" "}
                              {dateLabel(group.earliest_published_at)}
                            </time>
                            <time
                              dateTime={group.latest_published_at ?? undefined}
                            >
                              Latest published{" "}
                              {dateLabel(group.latest_published_at)}
                            </time>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2 my-2">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-200">
                            {group.signal_count} reports
                          </span>
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                            Tier: {group.representative_source.credibility_tier}
                          </span>
                          {group.representative_location ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
                              📍 {group.representative_location.label} (
                              {group.representative_location.precision})
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
                              📍 Location unresolved
                            </span>
                          )}
                        </div>

                        <h3 className="text-lg font-bold text-slate-900 mb-3">
                          {group.representative_title}
                        </h3>

                        <div className="brief-grid grid grid-cols-1 gap-2 my-3 p-3 bg-slate-50 rounded-md border border-slate-200 text-sm">
                          <BriefSlots brief={group.representative_brief} />
                        </div>

                        <div className="event-context my-3 p-2.5 rounded bg-amber-50/60 border border-amber-200 text-xs">
                          <AttachedEventContext event={group.event} />
                        </div>

                        <div className="mt-3 pt-2 border-t border-slate-100 flex justify-between items-center">
                          <a
                            className="source-link text-sm font-medium text-blue-600 hover:text-blue-800"
                            href={group.representative_source.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View original source{" "}
                            <span aria-hidden="true">↗</span>
                          </a>
                        </div>
                      </article>
                    );
                  })}
                  {items.map((item) => {
                    const isSelected = item.id === selectedId;
                    return (
                      <article
                        key={item.id}
                        ref={(el) => {
                          if (el) cardRefs.current.set(item.id, el);
                          else cardRefs.current.delete(item.id);
                        }}
                        tabIndex={0}
                        role="button"
                        aria-pressed={isSelected}
                        aria-label={`Select signal: ${item.title_english}`}
                        className={`evidence-card cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                          isSelected
                            ? "ring-2 ring-blue-600 bg-blue-50/20"
                            : "hover:border-slate-300"
                        }`}
                        data-selected={isSelected ? "true" : "false"}
                        onClick={() => setSelectedId(item.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelectedId(item.id);
                          }
                        }}
                      >
                        <div className="evidence-meta">
                          <span className="font-semibold text-slate-900">
                            {item.source.name}
                          </span>
                          <div className="evidence-dates">
                            <time dateTime={item.published_at ?? undefined}>
                              Published {dateLabel(item.published_at)}
                            </time>
                            <time dateTime={item.first_seen_at}>
                              Seen {dateLabel(item.first_seen_at)}
                            </time>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2 my-2">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-800">
                            {formatSourceBadge(item.source.is_official)}
                          </span>
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                            Tier: {item.source.credibility_tier}
                          </span>
                          {item.location ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
                              📍 {item.location.label} (
                              {item.location.precision})
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
                              📍 Location unresolved
                            </span>
                          )}
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-800 border border-indigo-200">
                            {Math.round(item.extraction_confidence * 100)}%
                            extraction confidence
                          </span>
                        </div>

                        <h3 className="text-lg font-bold text-slate-900 mb-3">
                          {item.title_english}
                        </h3>

                        <div className="brief-grid grid grid-cols-1 gap-2 my-3 p-3 bg-slate-50 rounded-md border border-slate-200 text-sm">
                          <BriefSlots brief={item.brief} />
                        </div>

                        <div className="event-context my-3 p-2.5 rounded bg-amber-50/60 border border-amber-200 text-xs">
                          {item.event_context_status === "attached" &&
                          item.event ? (
                            <AttachedEventContext event={item.event} />
                          ) : item.event_context_status === "ambiguous" ? (
                            <span className="text-amber-800">
                              Ambiguous signal (matches multiple candidate
                              events)
                            </span>
                          ) : (
                            <span className="text-slate-600">
                              Unattached signal (not linked to an outbreak
                              event)
                            </span>
                          )}
                        </div>

                        <div className="mt-3 pt-2 border-t border-slate-100 flex justify-between items-center">
                          <a
                            className="source-link text-sm font-medium text-blue-600 hover:text-blue-800"
                            href={item.source.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View original source{" "}
                            <span aria-hidden="true">↗</span>
                          </a>
                        </div>
                      </article>
                    );
                  })}
                </>
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
            EpiSignal never shows a claim or metric without traceable source
            provenance. 5-slot briefs and representative locations preserve the
            exact chain of evidence from official agency bulletins and media
            reports.
          </p>
        </section>
      </main>
    </>
  );
}
