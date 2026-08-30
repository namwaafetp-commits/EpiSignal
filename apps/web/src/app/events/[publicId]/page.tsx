import { formatVerificationStatus } from "@/lib/api-events";
import type { EventDetailResponse } from "@/lib/api-events";
import { getEventDetail } from "@/lib/api-events";
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
    <main>
      <section className="hero" aria-labelledby="event-title">
        <p className="eyebrow">Event · {detail.public_id}</p>
        <h1 id="event-title" className="text-balance">
          {headline}
        </h1>
        <div className="flex flex-wrap gap-2 mt-3">
          {detail.disease && (
            <span className="inline-flex items-center px-2.5 py-1 rounded text-sm font-semibold bg-amber-100 text-amber-900 border border-amber-200">
              {detail.disease}
            </span>
          )}
          <span className="inline-flex items-center px-2.5 py-1 rounded text-sm font-medium bg-slate-100 text-slate-700">
            {detail.status}
          </span>
          <span className="px-2.5 py-1 rounded bg-amber-50 font-medium text-amber-900 border border-amber-200 text-sm">
            {formatVerificationStatus(detail.verification_status)}
          </span>
          {(detail.admin1 || detail.country_code) && (
            <span className="inline-flex items-center px-2.5 py-1 rounded text-sm font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
              {[detail.admin1 ?? detail.admin2, detail.country_code]
                .filter(Boolean)
                .join(", ")}
            </span>
          )}
        </div>
        {detail.article_count > 0 && (
          <p className="text-sm text-slate-500 mt-2">
            {detail.article_count} articles · Updated{" "}
            {dateLabel(detail.latest_report_at)}
          </p>
        )}
      </section>

      <section className="evidence-section" aria-labelledby="overview-heading">
        {/* What happened */}
        {detail.summary && (
          <article className="evidence-card">
            <h2
              id="overview-heading"
              className="text-lg font-bold text-slate-900 mb-2"
            >
              Overview
            </h2>
            <p className="text-slate-700 leading-relaxed">{detail.summary}</p>
            {detail.summaries[0]?.latest_development && (
              <p className="text-sm text-slate-600 mt-2">
                <span className="font-medium">Latest development: </span>
                {detail.summaries[0].latest_development}
              </p>
            )}
            {detail.summaries[0]?.uncertainties?.length ? (
              <div className="mt-3">
                <p className="text-sm font-medium text-slate-600">
                  Uncertainties / conflicts
                </p>
                <ul className="list-disc pl-5 text-sm text-slate-600">
                  {detail.summaries[0].uncertainties.map((u: string) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>
        )}

        {/* How many cases / deaths — latest known counts */}
        <article className="evidence-card">
          <h2 className="text-lg font-bold text-slate-900 mb-2">
            Latest known counts
          </h2>
          {latest ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
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
            <p className="text-sm text-slate-500">
              No structured counts have been extracted for this event yet.
            </p>
          )}
          {latest?.observation_date && (
            <p className="text-xs text-slate-500 mt-2">
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
          <article className="evidence-card">
            <h2 className="text-lg font-bold text-slate-900 mb-2">Timeline</h2>
            <ol className="border-l border-slate-200 pl-4 space-y-3">
              {detail.observations.map((obs, idx) => (
                <li key={idx} className="text-sm">
                  <time className="font-medium text-slate-700">
                    {obs.observation_date
                      ? new Intl.DateTimeFormat("en-GB", {
                          dateStyle: "medium",
                        }).format(new Date(obs.observation_date))
                      : obs.reported_at
                        ? dateLabel(obs.reported_at)
                        : "Date unknown"}
                  </time>
                  <div className="text-slate-600">
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
          <article className="evidence-card">
            <h2 className="text-lg font-bold text-slate-900 mb-2">Sources</h2>
            <ul className="space-y-2">
              {detail.sources.map(
                (
                  source: NonNullable<EventDetailResponse["sources"]>[number],
                ) => (
                  <li
                    key={source.signal_id}
                    className="text-sm flex flex-col sm:flex-row sm:items-start sm:justify-between py-2 border-b border-slate-100"
                  >
                    <div className="min-w-0 mr-4">
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-blue-700 hover:text-blue-900 break-words"
                      >
                        {source.title}
                      </a>
                      <div className="text-xs text-slate-600 mt-1">
                        <span className="font-medium">
                          {source.source_name}
                        </span>
                        {source.is_official ? " · Official source" : ""}
                        {" · "}
                        {source.published_at
                          ? dateLabel(source.published_at)
                          : dateLabel(source.first_seen_at)}
                        {" · "}
                        <span className="text-slate-500">
                          {source.relationship_type.replaceAll("_", " ")}
                        </span>
                      </div>
                    </div>
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="whitespace-nowrap text-xs font-medium text-blue-600 hover:text-blue-800 mt-1 sm:mt-0 shrink-0"
                    >
                      Original ↗
                    </a>
                  </li>
                ),
              )}
            </ul>
            {detail.summaries[0]?.model_id && (
              <p className="text-xs text-slate-400 mt-2">
                Latest summary generated by {detail.summaries[0].model_id}.
                Every claim above remains traceable to the source row it came
                from.
              </p>
            )}
          </article>
        )}

        <div className="mt-4">
          <Link
            href="/events"
            className="text-sm text-blue-700 hover:text-blue-900"
          >
            ← Back to events
          </Link>
        </div>
      </section>
    </main>
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
    <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-slate-900">
        {typeof value === "number" ? String(value) : "—"}
      </div>
      {dataAsOf && (
        <div className="text-xs text-slate-400">As of {dataAsOf}</div>
      )}
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
