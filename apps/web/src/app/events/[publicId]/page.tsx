import { formatVerificationStatus, relativeTimeLabel } from "@/lib/api-events";
import type { EventDetailResponse } from "@/lib/api-events";
import { getEventDetail } from "@/lib/api-events";
import { formatCountryLocation } from "@/lib/country";
import Link from "next/link";
import { notFound } from "next/navigation";

export default async function EventPage({
  params,
}: {
  params: Promise<{ publicId: string }>;
}) {
  const { publicId } = await params;
  const detail: EventDetailResponse | null = await getEventDetail(publicId);
  if (!detail) notFound();

  const headline = detail.headline ?? detail.public_id;
  const latest = detail.observations[detail.observations.length - 1];
  const brief = detail.summaries[0];

  return (
    <div className="app-shell event-page-shell">
      <main className="event-page">
        <Link href="/" className="event-page__back">
          ← Back to map
        </Link>
        <section className="event-page__hero" aria-labelledby="event-title">
          <p className="eyebrow">Event · {detail.public_id}</p>
          <div className="event-page__meta">
            <span className={`status-label status-label--${detail.status}`}>
              {detail.status}
            </span>
            <span aria-hidden="true">·</span>
            <span>{detail.disease ?? "Unknown disease"}</span>
            <span className="event-page__verification">
              {formatVerificationStatus(detail.verification_status)}
            </span>
          </div>
          <h1 id="event-title" className="text-balance">
            {headline}
          </h1>
          <p className="event-page__location">
            {formatCountryLocation(
              detail.admin1 ?? detail.admin2,
              detail.country_code,
            )}
          </p>
          <p className="event-page__facts">
            {detail.sources.length || detail.article_count} sources · Updated{" "}
            {relativeTimeLabel(detail.latest_report_at)}
          </p>
        </section>

        <section
          className="event-page__content"
          aria-labelledby="overview-heading"
        >
          {/* What happened */}
          {brief && hasStructuredFlashBrief(brief) ? (
            <StructuredFlashBrief summary={brief} />
          ) : brief ? (
            <article className="event-page__section">
              <h2 id="overview-heading">Event brief</h2>
              <p>{brief.summary}</p>
            </article>
          ) : detail.summary ? (
            <article className="event-page__section">
              <h2 id="overview-heading">Event brief</h2>
              <p>{detail.summary}</p>
            </article>
          ) : null}

          {/* Observation history keeps report dates and provenance; numeric
              extraction is intentionally not part of the public contract. */}
          <article className="event-page__section">
            <h2>Observation history</h2>
            {latest ? (
              <p className="event-page__muted">
                Latest linked report:{" "}
                {latest.reported_at
                  ? dateLabel(latest.reported_at)
                  : "date unknown"}
                .
              </p>
            ) : (
              <p className="event-page__muted">No linked observations yet.</p>
            )}
          </article>

          {/* Timeline — observations */}
          {detail.observations.length > 1 && (
            <article className="event-page__section">
              <h2>Timeline</h2>
              <ol className="event-page__timeline">
                {detail.observations.map((obs, idx) => (
                  <li key={idx} className="text-sm">
                    <time>
                      {obs.observation_date
                        ? new Intl.DateTimeFormat("en-GB", {
                            dateStyle: "medium",
                          }).format(new Date(obs.observation_date))
                        : obs.reported_at
                          ? dateLabel(obs.reported_at)
                          : "Date unknown"}
                    </time>
                    {obs.notes && (
                      <div className="event-page__timeline-facts">
                        {obs.notes}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </article>
          )}

          {/* Sources — traceable provenance */}
          {detail.sources.length > 0 && (
            <article className="event-page__section">
              <h2>Sources</h2>
              <ul className="event-page__sources">
                {detail.sources.map(
                  (
                    source: NonNullable<EventDetailResponse["sources"]>[number],
                  ) => (
                    <li key={source.signal_id} className="event-page__source">
                      <div className="event-page__source-copy">
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="event-page__source-title"
                        >
                          {source.title}
                        </a>
                        <div className="event-page__source-meta">
                          <span>{source.source_name}</span>
                          {source.is_official ? " · Official source" : ""}
                          {" · "}
                          {source.published_at
                            ? dateLabel(source.published_at)
                            : dateLabel(source.first_seen_at)}
                          {" · "}
                          <span>
                            {source.relationship_type.replaceAll("_", " ")}
                          </span>
                        </div>
                      </div>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="event-page__source-original"
                      >
                        Original ↗
                      </a>
                    </li>
                  ),
                )}
              </ul>
              {detail.summaries[0]?.model_id && (
                <p className="event-page__muted event-page__summary-note">
                  Latest summary generated by {detail.summaries[0].model_id}.
                  Every claim above remains traceable to the source row it came
                  from.
                </p>
              )}
            </article>
          )}

          <div className="event-page__bottom-back">
            <Link href="/events" className="event-page__back">
              ← Back to events
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}

function hasStructuredFlashBrief(
  summary: NonNullable<EventDetailResponse["summaries"]>[number],
): summary is typeof summary & {
  snapshot: string[];
  key_driver: string;
  response: string;
  risk: string;
} {
  return (
    summary.snapshot !== null &&
    Array.isArray(summary.snapshot) &&
    summary.key_driver !== null &&
    summary.response !== null &&
    summary.risk !== null
  );
}

function StructuredFlashBrief({
  summary,
}: {
  summary: NonNullable<EventDetailResponse["summaries"]>[number] & {
    snapshot: string[];
    key_driver: string;
    response: string;
    risk: string;
  };
}) {
  return (
    <article className="event-page__section" aria-labelledby="overview-heading">
      <h2 id="overview-heading">{summary.headline}</h2>
      <p className="event-page__muted">{summary.trajectory}</p>
      <h3>The Snapshot</h3>
      <p>{summary.snapshot.join(" | ")}</p>
      <h3>Key Driver</h3>
      <p>{summary.key_driver}</p>
      <h3>Response</h3>
      <p>{summary.response}</p>
      <h3>Public/Global Risk</h3>
      <p>{summary.risk}</p>
    </article>
  );
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}
