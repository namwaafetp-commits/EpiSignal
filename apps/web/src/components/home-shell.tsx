import Link from "next/link";

export type ApiShellStatus = "loading" | "ready" | "unavailable";

const STATUS_LABELS: Record<ApiShellStatus, string> = {
  loading: "Checking API",
  ready: "API connected",
  unavailable: "API unavailable",
};

export function HomeShell({ apiStatus }: { apiStatus: ApiShellStatus }) {
  const statusLabel = STATUS_LABELS[apiStatus];

  return (
    <>
      <header className="masthead">
        <Link className="brand" href="/">
          EpiSignal
        </Link>
        <nav aria-label="Primary navigation">
          <a href="#explore">Explore</a>
          <a href="#data">Data</a>
          <a href="#about">About</a>
        </nav>
        <span className={`system-pill system-pill--${apiStatus}`}>
          {statusLabel}
        </span>
      </header>
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <p className="eyebrow">Open global outbreak intelligence</p>
          <h1 id="hero-title">
            What is happening in infectious disease right now?
          </h1>
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
            Search becomes available when the first evidence source is
            connected.
          </p>
        </section>
        <section
          id="explore"
          className="explore-grid"
          aria-label="Global activity"
        >
          <div className="map-placeholder">
            <p className="map-label">Global activity map</p>
            <p>
              Event records will appear after source ingestion is connected.
            </p>
          </div>
          <aside
            className="readiness-card"
            aria-label="Foundation status"
            data-mobile-role="bottom-sheet"
          >
            <p className="eyebrow">System status</p>
            <h2>Ready for evidence.</h2>
            <p>
              The public shell is online. Connect the first source to begin
              building traceable events.
            </p>
            <p className="components">Database · PostGIS · API</p>
          </aside>
        </section>
      </main>
    </>
  );
}
