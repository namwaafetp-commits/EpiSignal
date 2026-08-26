import type { EvidenceFeedState } from "@/lib/api-signals";
import Link from "next/link";

export type ApiShellStatus = "loading" | "ready" | "unavailable";

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking API",
  ready: "API connected",
  unavailable: "API unavailable",
};

function countLabel(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function publicationLabel(value: string | null) {
  if (!value) return "Publication date unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function CoverageNotice({ evidenceFeed }: { evidenceFeed: EvidenceFeedState }) {
  if (evidenceFeed.status === "loading") {
    return (
      <aside
        className="coverage-card"
        aria-label="Coverage notice"
        data-mobile-role="bottom-sheet"
      >
        <p className="eyebrow">Loading evidence</p>
        <h2>Checking stored reports.</h2>
      </aside>
    );
  }

  if (evidenceFeed.status === "unavailable") {
    return (
      <aside
        className="coverage-card coverage-card--unavailable"
        aria-label="Coverage notice"
        data-mobile-role="bottom-sheet"
      >
        <p className="eyebrow">Coverage unavailable</p>
        <h2>Evidence feed unavailable.</h2>
        <p>
          The API could not load stored reports. No substitute data is shown.
        </p>
      </aside>
    );
  }

  const { total, source_count: sourceCount } = evidenceFeed.data;
  const shownSources = [
    ...new Set(evidenceFeed.data.items.map((item) => item.source_name)),
  ];
  return (
    <aside
      className="coverage-card"
      aria-label="Coverage notice"
      data-mobile-role="bottom-sheet"
    >
      <p className="eyebrow">Limited coverage</p>
      <h2>
        {countLabel(total, "report", "reports")} from{" "}
        {countLabel(sourceCount, "source", "sources")}
      </h2>
      <p>
        This is an ingestion proof, not comprehensive global surveillance. More
        official regional and national sources are required.
      </p>
      {shownSources.length > 0 ? (
        <p className="components">
          Sources on this page · {shownSources.join(" · ")}
        </p>
      ) : null}
    </aside>
  );
}

export function HomeShell({
  apiStatus,
  evidenceFeed,
}: {
  apiStatus: ApiShellStatus;
  evidenceFeed: EvidenceFeedState;
}) {
  const statusLabel = STATUS_LABELS[apiStatus];
  const items = evidenceFeed.status === "ready" ? evidenceFeed.data.items : [];

  return (
    <>
      <header className="masthead">
        <Link className="brand" href="/">
          EpiSignal
        </Link>
        <nav aria-label="Primary navigation">
          <a href="#explore">Evidence</a>
          <a href="#coverage">Coverage</a>
          <a href="#about">About</a>
        </nav>
        <span className={`system-pill system-pill--${apiStatus}`}>
          {statusLabel}
        </span>
      </header>
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <p className="eyebrow">Traceable outbreak evidence</p>
          <h1 id="hero-title">What are official health sources reporting?</h1>
          <p className="hero-intro">
            Browse source documents exactly as collected. EpiSignal does not yet
            interpret, score, or merge them into outbreak events.
          </p>
          <form
            className="search-preview"
            role="search"
            aria-label="Event search preview"
          >
            <input
              type="search"
              disabled
              placeholder="Search disease, country, outbreak, pathogen…"
            />
            <button type="submit" disabled>
              Search
            </button>
          </form>
          <p className="preview-note">
            Search unlocks after evidence extraction and event matching are
            implemented.
          </p>
        </section>

        <section
          id="explore"
          className="evidence-section"
          aria-labelledby="evidence-title"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Source evidence</p>
              <h2 id="evidence-title">Latest outbreak reports</h2>
            </div>
            <p>Newest publication first · exact stored text</p>
          </div>

          <div className="evidence-layout">
            <div className="evidence-list" aria-live="polite">
              {evidenceFeed.status === "loading" ? (
                <p className="empty-state">Loading stored reports…</p>
              ) : evidenceFeed.status === "unavailable" ? (
                <p className="empty-state">Reports could not be loaded.</p>
              ) : items.length === 0 ? (
                <p className="empty-state">
                  No source evidence has been ingested yet.
                </p>
              ) : (
                items.map((item) => (
                  <article className="evidence-card" key={item.id}>
                    <div className="evidence-meta">
                      <span>{item.source_name}</span>
                      <time dateTime={item.published_at ?? undefined}>
                        {publicationLabel(item.published_at)}
                      </time>
                    </div>
                    <h3>{item.title}</h3>
                    {item.raw_text ? (
                      <details className="evidence-text">
                        <summary>Read stored evidence</summary>
                        <p>{item.raw_text}</p>
                      </details>
                    ) : (
                      <p className="evidence-missing">
                        This source record contains no text body.
                      </p>
                    )}
                    <a
                      className="source-link"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View original source <span aria-hidden="true">↗</span>
                    </a>
                  </article>
                ))
              )}
            </div>
            <div id="coverage">
              <CoverageNotice evidenceFeed={evidenceFeed} />
            </div>
          </div>
        </section>

        <section
          id="about"
          className="about-strip"
          aria-label="About EpiSignal"
        >
          <p className="eyebrow">Evidence before claims</p>
          <p>
            EpiSignal never shows a number without the source text behind it.
            Classification, event matching, and extracted metrics remain absent
            until they can preserve that chain of evidence.
          </p>
        </section>
      </main>
    </>
  );
}
