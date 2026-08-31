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
          {detail.summary && (
            <article className="event-page__section">
              <h2 id="overview-heading">Overview</h2>
              <p>{detail.summary}</p>
              {detail.summaries[0]?.latest_development && (
                <section
                  className="event-page__latest"
                  aria-labelledby="latest-development-heading"
                >
                  <h3 id="latest-development-heading">Latest development</h3>
                  <p>{detail.summaries[0].latest_development}</p>
                </section>
              )}
              {detail.summaries[0]?.uncertainties?.length ? (
                <div className="event-page__uncertainties">
                  <h3>Uncertainties / conflicts</h3>
                  <ul>
                    {detail.summaries[0].uncertainties.map((u: string) => (
                      <li key={u}>{u}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </article>
          )}

          {/* How many cases / deaths — latest known counts */}
          <article className="event-page__section">
            <h2>Latest known counts</h2>
            {latest ? (
              <div className="event-page__counts">
                <CountBox
                  label="Suspected cases"
                  value={latest.suspected_cases}
                  dataAsOf={latest.observation_date ?? latest.reported_at}
                />
                <CountBox
                  label="Confirmed cases"
                  value={latest.confirmed_cases}
                />
                <CountBox label="Total cases" value={latest.total_cases} />
                <CountBox label="Deaths" value={latest.deaths} />
              </div>
            ) : (
              <p className="event-page__muted">
                No structured counts have been extracted for this event yet.
              </p>
            )}
            {latest?.observation_date && (
              <p className="event-page__muted event-page__as-of">
                Data as of{" "}
                {new Intl.DateTimeFormat("en-GB").format(
                  new Date(latest.observation_date),
                )}
                {latest.reported_at
                  ? ` · Reported ${dateLabel(latest.reported_at)}`
                  : ""}
              </p>
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
                    <div className="event-page__timeline-facts">
                      {typeof obs.total_cases === "number" && (
                        <span className="mr-3">{obs.total_cases} cases</span>
                      )}
                      {typeof obs.confirmed_cases === "number" && (
                        <span className="mr-3">
                          {obs.confirmed_cases} confirmed
                        </span>
                      )}
                      {typeof obs.deaths === "number" && (
                        <span>{obs.deaths} deaths</span>
                      )}
                    </div>
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

function CountBox({
  label,
  value,
  dataAsOf,
}: {
  label: string;
  value: number | null | undefined;
  dataAsOf?: string | null;
}) {
  return (
    <div className="event-page__count">
      <div>{label}</div>
      <div className="event-page__count-value">
        {typeof value === "number" ? String(value) : "—"}
      </div>
      {dataAsOf && <div>As of {dataAsOf}</div>}
    </div>
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
