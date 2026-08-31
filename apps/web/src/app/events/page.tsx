import { getEventList } from "@/lib/api-events";
import { formatCountryLocation } from "@/lib/country";
import Link from "next/link";

const DISEASES = [
  "all",
  "Dengue",
  "Measles",
  "Cholera",
  "Avian influenza",
  "COVID-19",
  "Mpox",
  "Ebola virus disease",
] as const;

const COUNTRIES = ["all", "TH", "CD", "YE", "AO", "PH"] as const;

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const disease =
    params.disease && params.disease !== "all" ? params.disease : undefined;
  const country =
    params.country && params.country !== "all" ? params.country : undefined;
  const status =
    params.status && params.status !== "all" ? params.status : undefined;

  const feed = await getEventList({ limit: 50, disease, country, status });

  return (
    <main>
      <section className="hero" aria-labelledby="events-title">
        <p className="eyebrow">Events</p>
        <h1 id="events-title">Epidemiological Events</h1>
        <p className="hero-intro">
          Each event assembles many reports of the same real-world outbreak.
          Case counts, places, and statuses are kept with their sources and
          never overwritten.
        </p>
      </section>

      <section className="evidence-section" aria-labelledby="filters-heading">
        <div className="flex flex-wrap gap-4 mb-6">
          <FilterGroup
            param="disease"
            current={disease}
            values={DISEASES}
            label="Disease"
          />
          <FilterGroup
            param="country"
            current={country}
            values={COUNTRIES}
            label="Country"
          />
          <FilterGroup
            param="status"
            current={status}
            values={["all", "monitoring", "ongoing", "resolved", "unknown"]}
            label="Status"
          />
        </div>

        {feed.status === "unavailable" && (
          <p className="empty-state">
            Events unavailable. The API could not load events.
          </p>
        )}
        {feed.status === "ready" && feed.data.total === 0 && (
          <p className="empty-state">
            No events match these filters. Try broadening the search.
          </p>
        )}
        {feed.status === "ready" && feed.data.items.length > 0 && (
          <div className="evidence-layout">
            <div className="evidence-list" aria-live="polite">
              {feed.data.items.map((event) => (
                <article key={event.public_id} className="evidence-card">
                  <div className="flex flex-wrap gap-2 mb-2">
                    {event.disease && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-200">
                        {event.disease}
                      </span>
                    )}
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                      {event.status}
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                      {event.verification_status.replaceAll("_", " ")}
                    </span>
                    {event.country_code && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
                        {formatCountryLocation(
                          event.admin1,
                          event.country_code,
                        )}
                      </span>
                    )}
                  </div>

                  <h3 className="text-lg font-bold text-slate-900 mb-2">
                    {event.headline ?? event.public_id}
                  </h3>
                  {event.headline && (
                    <p className="text-sm text-slate-500 mb-1">
                      {event.public_id}
                    </p>
                  )}

                  {event.summary && (
                    <p className="text-sm text-slate-700 mb-2 line-clamp-3">
                      {event.summary}
                    </p>
                  )}

                  <div className="flex flex-wrap gap-4 text-xs text-slate-500 mt-2">
                    <time dateTime={event.latest_report_at}>
                      Updated {dateLabel(event.latest_report_at)}
                    </time>
                    <span>{event.article_count} articles</span>
                  </div>

                  <div className="mt-3 pt-2 border-t border-slate-100">
                    <Link
                      href={`/events/${encodeURIComponent(event.public_id)}`}
                      className="source-link text-sm font-medium text-blue-600 hover:text-blue-800"
                    >
                      View event
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function FilterGroup({
  param,
  current,
  values,
  label,
}: {
  param: "disease" | "country" | "status";
  current: string | undefined;
  values: readonly string[];
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-sm font-medium text-slate-600">{label}</label>
      <div className="flex flex-wrap gap-1">
        {values.map((value) => {
          const isActive = (current ?? "all") === value;
          return (
            <a
              key={value}
              className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-medium ${
                isActive
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              href={hrefWithParam(param, value, current)}
            >
              {value}
            </a>
          );
        })}
      </div>
    </div>
  );
}

function hrefWithParam(
  param: string,
  value: string,
  current: string | undefined,
): string {
  const next = new URLSearchParams();
  if (current && value === current) {
    // Clicking active deselects.
    next.delete(param);
  } else if (value !== "all") {
    next.set(param, value);
  }
  // Strip the current filter from the href since we only know one; the server
  // will rebuild from searchParams. This page doesn't carry other filters in href.
  const query = next.toString();
  return query ? `/events?${query}` : "/events";
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
