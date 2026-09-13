"use client";

import Link from "next/link";
import {
  useEffect,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent,
  type RefObject,
} from "react";
import { ArrowUpRight } from "lucide-react";
import type { DashboardEvent } from "../lib/api-dashboard";
import { countryFlag, countryName } from "../lib/country";
import { relativeTimeLabel } from "../lib/api-events";
import { diseaseGroupLabel, hostSectorLabel } from "../lib/surveillance-labels";
import {
  DiseaseGroupIcon,
  HostSectorIcon,
  RecencyIcon,
} from "../lib/surveillance-icons";

/**
 * Below this the day-by-day timeline still reads well. Above it the feed is
 * easier to scan as one horizontal track per disease group.
 */
export const SHELF_THRESHOLD = 10;

function isTypingTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName ?? "")
  );
}

/**
 * Moves focus between headlines so the feed can be worked through without a
 * mouse. Enter needs no handling: focusing a headline and pressing it fires the
 * same click path as a left click, which opens the reading pane.
 *
 * j and k work anywhere on the page because neither scrolls. The arrow keys
 * only take over once focus is already in the feed, so ordinary page scrolling
 * is never hijacked.
 */
function useFeedTraversal(feedRef: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      const links = [
        ...(feedRef.current?.querySelectorAll<HTMLAnchorElement>(
          "[data-event-link]",
        ) ?? []),
      ];
      if (!links.length) return;

      const current = links.indexOf(
        document.activeElement as HTMLAnchorElement,
      );
      const inFeed = current !== -1;
      const forward =
        event.key === "j" || (inFeed && event.key === "ArrowDown");
      const back = event.key === "k" || (inFeed && event.key === "ArrowUp");
      if (!forward && !back) return;

      const next = !inFeed
        ? forward
          ? 0
          : links.length - 1
        : Math.min(links.length - 1, Math.max(0, current + (forward ? 1 : -1)));

      event.preventDefault();
      links[next].focus();
      links[next].scrollIntoView({ block: "nearest" });
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [feedRef]);
}

type RowProps = {
  event: DashboardEvent;
  selectedId: string | null;
  onSelect: (id: string) => void;
  query: string;
  now: number;
};

/**
 * The reading pane only takes over a plain desktop activation. Modified clicks,
 * middle clicks and mobile all fall through to the link so opening in a new tab
 * and navigating still work.
 */
function opensReadingPane(e: {
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}) {
  return (
    !e.metaKey &&
    !e.ctrlKey &&
    !e.shiftKey &&
    !e.altKey &&
    !window.matchMedia("(max-width: 700px)").matches
  );
}

function useRowSelect(onSelect: (id: string) => void) {
  return {
    onClick(e: MouseEvent<HTMLAnchorElement>, id: string) {
      if (e.button !== 0 || !opensReadingPane(e)) return;
      e.preventDefault();
      onSelect(id);
    },
    // Handled explicitly rather than leaning on the anchor default, so Enter
    // behaves the same everywhere. preventDefault suppresses the native click,
    // so the pane cannot open twice.
    onKeyDown(e: ReactKeyboardEvent<HTMLAnchorElement>, id: string) {
      if (e.key !== "Enter" || !opensReadingPane(e)) return;
      e.preventDefault();
      onSelect(id);
    },
  };
}

function groupByDay(events: DashboardEvent[]) {
  const groups = new Map<string, DashboardEvent[]>();
  for (const event of events) {
    const day = new Date(event.latest_report_at).toISOString().slice(0, 10);
    groups.set(day, [...(groups.get(day) ?? []), event]);
  }
  return [...groups];
}

function groupByDisease(events: DashboardEvent[]) {
  const groups = new Map<string, DashboardEvent[]>();
  for (const event of events) {
    const key = event.disease_group ?? "unknown";
    groups.set(key, [...(groups.get(key) ?? []), event]);
  }
  // Busiest groups first so the densest reporting leads the page.
  return [...groups].sort((a, b) => b[1].length - a[1].length);
}

function EventMeta({ event }: { event: DashboardEvent }) {
  return (
    <p className="briefing-row__meta">
      <span className="briefing-row__tag briefing-row__tag--disease">
        <DiseaseGroupIcon group={event.disease_group} />
        {diseaseGroupLabel(event.disease_group)}
      </span>
      <span aria-hidden="true">·</span>
      <span
        className="briefing-row__tag"
        title={hostSectorLabel(event.host_sector)}
      >
        <HostSectorIcon host={event.host_sector} size={14} />
        <span className="sr-only">{hostSectorLabel(event.host_sector)}</span>
      </span>
      <span aria-hidden="true">·</span>
      <span className="briefing-row__tag">
        {event.article_count} {event.article_count === 1 ? "source" : "sources"}
      </span>
    </p>
  );
}

function EventOverline({ event, now }: { event: DashboardEvent; now: number }) {
  const flag = countryFlag(event.country_code);
  return (
    <div className="briefing-row__overline">
      <span>
        {flag ? (
          <span className="briefing-row__flag" aria-hidden="true">
            {flag}
          </span>
        ) : null}
        {event.admin1 ? `${event.admin1}, ` : ""}
        {countryName(event.country_code)}
      </span>
      <time className="briefing-row__time" dateTime={event.latest_report_at}>
        <RecencyIcon reportedAt={event.latest_report_at} now={now} />
        {relativeTimeLabel(event.latest_report_at)}
      </time>
    </div>
  );
}

function EventHeadline({
  event,
  selectedId,
  onSelect,
  query,
}: Omit<RowProps, "now">) {
  const row = useRowSelect(onSelect);
  return (
    <h3>
      <Link
        href={`/events/${encodeURIComponent(event.public_id)}${query}`}
        onClick={(e) => row.onClick(e, event.public_id)}
        onKeyDown={(e) => row.onKeyDown(e, event.public_id)}
        aria-current={selectedId === event.public_id ? "true" : undefined}
        aria-keyshortcuts="j k"
        data-event-link=""
      >
        {event.headline}
        <ArrowUpRight size={17} aria-hidden="true" />
      </Link>
    </h3>
  );
}

function BriefingRow(props: RowProps) {
  const { event, selectedId, now } = props;
  return (
    <article
      className={`briefing-row ${selectedId === event.public_id ? "is-selected" : ""}`}
      data-disease={event.disease_group ?? "unknown"}
    >
      <EventOverline event={event} now={now} />
      <EventHeadline {...props} />
      <EventMeta event={event} />
    </article>
  );
}

function FeedShortcutHint() {
  return (
    <p className="feed-shortcuts">
      Press <kbd>J</kbd> and <kbd>K</kbd> to move through events,{" "}
      <kbd>Enter</kbd> to open.
    </p>
  );
}

export function BriefingFeed({
  events,
  selectedId,
  onSelect,
  query,
  now,
}: {
  events: DashboardEvent[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  query: string;
  now: number;
}) {
  const asShelves = events.length > SHELF_THRESHOLD;
  const feedRef = useRef<HTMLDivElement | null>(null);
  useFeedTraversal(feedRef);

  if (asShelves) {
    return (
      <div className="briefing-feed briefing-feed--shelves" ref={feedRef}>
        <FeedShortcutHint />
        {groupByDisease(events).map(([group, rows]) => (
          <section
            className="briefing-shelf"
            key={group}
            aria-label={`${diseaseGroupLabel(group)} — ${rows.length} events`}
          >
            <h2 className="date-heading">
              <span className="briefing-row__tag">
                <DiseaseGroupIcon group={group} size={14} />
                {diseaseGroupLabel(group)}
              </span>
              <span>
                {rows.length} {rows.length === 1 ? "event" : "events"}
              </span>
            </h2>
            <ul className="shelf-track">
              {rows.map((event) => (
                <li
                  className={`shelf-item briefing-row ${selectedId === event.public_id ? "is-selected" : ""}`}
                  key={event.public_id}
                  data-disease={event.disease_group ?? "unknown"}
                >
                  <EventOverline event={event} now={now} />
                  <EventHeadline
                    event={event}
                    selectedId={selectedId}
                    onSelect={onSelect}
                    query={query}
                  />
                  <EventMeta event={event} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  }

  return (
    <div className="briefing-feed" ref={feedRef}>
      <FeedShortcutHint />
      {groupByDay(events).map(([day, rows]) => (
        <section className="briefing-section" key={day}>
          <h2 className="date-heading">
            {day === new Date().toISOString().slice(0, 10) ? "Today · " : ""}
            {new Intl.DateTimeFormat("en-GB", {
              day: "numeric",
              month: "long",
              year: "numeric",
              timeZone: "UTC",
            }).format(new Date(`${day}T00:00:00Z`))}
            <span>
              {rows.length} {rows.length === 1 ? "event" : "events"}
            </span>
          </h2>
          {rows.map((event) => (
            <BriefingRow
              key={event.public_id}
              event={event}
              selectedId={selectedId}
              onSelect={onSelect}
              query={query}
              now={now}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
