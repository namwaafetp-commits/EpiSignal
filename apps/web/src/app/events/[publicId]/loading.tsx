import "@/components/event-content.css";

/** An article-shaped placeholder, so the map shell never stands in for an event. */
export default function Loading() {
  return (
    <main className="event-content" aria-busy="true">
      <div className="event-content__hero">
        <p className="event-content__kicker">Loading event</p>
        <h1 className="event-content__loading-title">
          Loading reported event…
        </h1>
      </div>
    </main>
  );
}
