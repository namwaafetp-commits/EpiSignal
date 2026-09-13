/**
 * The root boundary is the OUTER fallback for every route, so it must stay
 * view-neutral. Per-view skeletons live in each segment's own loading.tsx.
 */
export default function Loading() {
  return (
    <div className="v2-page route-skeleton" role="status" aria-busy="true">
      <p className="eyebrow">Global infectious-disease intelligence</p>
      <p className="route-skeleton__message">Loading…</p>
    </div>
  );
}
