import { ExternalLink } from "lucide-react";
import Link from "next/link";
import type { RelatedEvent } from "@/lib/related-events";
import type { EventDetailResponse } from "@/lib/api-events";
import { dateLabel } from "@/lib/api-events";
import type { DashboardEvent } from "@/lib/api-dashboard";
import "./event-content.css";

const LEAD_SOURCE_COUNT = 3;

type FlexibleSummary = {
  title: string;
  bullets: string[];
  takeaway?: string;
};

export function EventBrief({
  event,
}: {
  event: DashboardEvent | EventDetailResponse;
}) {
  const payload = event.summary_payload;

  if (isFlexibleSummary(payload)) {
    return (
      <section className="event-content__brief" aria-labelledby="brief-heading">
        <h2 id="brief-heading">THE BRIEF</h2>
        <ul>
          {payload.bullets.map((bullet, index) => (
            <li key={`${index}-${bullet}`}>{bullet}</li>
          ))}
        </ul>
        {payload.takeaway ? (
          <p className="event-content__takeaway">
            <span>Takeaway</span>
            {payload.takeaway}
          </p>
        ) : null}
      </section>
    );
  }

  if ("summaries" in event && event.summaries[0]) {
    const summary = event.summaries[0];
    if (hasStructuredBrief(summary)) {
      return (
        <section
          className="event-content__brief"
          aria-labelledby="brief-heading"
        >
          <h2 id="brief-heading">THE BRIEF</h2>
          {summary.trajectory ? (
            <p className="event-content__trajectory">{summary.trajectory}</p>
          ) : null}
          <div className="event-content__legacy-brief">
            <h3>The Snapshot</h3>
            <p>{summary.snapshot.join(" | ")}</p>
            <h3>Key Driver</h3>
            <p>{summary.key_driver}</p>
            <h3>Response</h3>
            <p>{summary.response}</p>
            <h3>Public/Global Risk</h3>
            <p>{summary.risk}</p>
          </div>
        </section>
      );
    }
    if (summary.summary) return <LegacyBrief summary={summary.summary} />;
  }

  return <LegacyBrief summary={event.summary} />;
}

export function SourceList({
  sources,
}: {
  sources: EventDetailResponse["sources"];
}) {
  if (!sources.length) {
    return (
      <section
        className="event-content__section"
        aria-labelledby="sources-heading"
      >
        <h2 id="sources-heading">SOURCES · 0</h2>
        <p className="event-content__muted">No linked sources are available.</p>
      </section>
    );
  }

  const lead = sources.slice(0, LEAD_SOURCE_COUNT);
  const rest = sources.slice(LEAD_SOURCE_COUNT);

  return (
    <section
      className="event-content__section"
      aria-labelledby="sources-heading"
    >
      <h2 id="sources-heading">SOURCES · {sources.length}</h2>
      <ol className="event-content__sources">
        {lead.map((source, index) => (
          <SourceRow key={source.signal_id} source={source} index={index} />
        ))}
      </ol>
      {rest.length > 0 && (
        /* <details> keeps the full trail one click away without client JS. */
        <details className="event-content__more-sources">
          <summary>
            Show {rest.length} more source{rest.length === 1 ? "" : "s"}
          </summary>
          <ol className="event-content__sources" start={LEAD_SOURCE_COUNT + 1}>
            {rest.map((source, index) => (
              <SourceRow
                key={source.signal_id}
                source={source}
                index={index + LEAD_SOURCE_COUNT}
              />
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function SourceRow({
  source,
  index,
}: {
  source: EventDetailResponse["sources"][number];
  index: number;
}) {
  return (
    <li>
      <span className="event-content__source-number">
        {String(index + 1).padStart(2, "0")}
      </span>
      <div>
        <a href={source.url} target="_blank" rel="noreferrer">
          {source.title}
          <ExternalLink aria-hidden="true" size={14} strokeWidth={1.75} />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        <p>
          {source.source_name} ·{" "}
          {source.published_at
            ? dateLabel(source.published_at)
            : dateLabel(source.first_seen_at)}
          {source.is_official ? " · Official source" : ""}
        </p>
      </div>
    </li>
  );
}

function LegacyBrief({ summary }: { summary: string | null }) {
  return (
    <section className="event-content__brief" aria-labelledby="brief-heading">
      <h2 id="brief-heading">THE BRIEF</h2>
      <p>{summary || "No summary is available for this event yet."}</p>
    </section>
  );
}

function isFlexibleSummary(value: unknown): value is FlexibleSummary {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  return (
    typeof payload.title === "string" &&
    Array.isArray(payload.bullets) &&
    payload.bullets.length > 0 &&
    payload.bullets.every((bullet) => typeof bullet === "string") &&
    (payload.takeaway === undefined || typeof payload.takeaway === "string")
  );
}

function hasStructuredBrief(
  summary: EventDetailResponse["summaries"][number],
): summary is EventDetailResponse["summaries"][number] & {
  snapshot: string[];
  key_driver: string;
  response: string;
  risk: string;
} {
  return (
    Array.isArray(summary.snapshot) &&
    summary.key_driver !== null &&
    summary.response !== null &&
    summary.risk !== null
  );
}

export function RelatedReporting({ related }: { related: RelatedEvent[] }) {
  if (!related.length) return null;

  return (
    <section
      className="event-content__section"
      aria-labelledby="related-heading"
    >
      <h2 id="related-heading">RELATED REPORTING</h2>
      <p className="event-content__muted event-content__related-note">
        Matched on disease group, place, host and reporting window. These events
        are not confirmed to be epidemiologically linked.
      </p>
      <ol className="event-content__related">
        {related.map(({ event, score, reasons }) => (
          <li key={event.public_id}>
            <Link href={`/events/${encodeURIComponent(event.public_id)}`}>
              {event.headline}
            </Link>
            <p>
              <span className="event-content__match" aria-hidden="true">
                {score}
              </span>
              <span className="sr-only">Match score {score}. </span>
              {reasons.join(" · ")}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
