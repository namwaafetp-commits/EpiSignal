# Umami operations guide

EpiSignal is prepared to send privacy-preserving, client-side analytics to a
separately self-hosted Umami service. This guide covers the production setup;
no production service or environment has been created by this repository task.
Use Umami 3.2.0 or newer: EpiSignal disables automatic page views and relies on
the `data-auto-pageview` tracker setting to keep event-detail identifiers out
of collected URLs.

## Production setup

1. Create a separate Umami service in Coolify. Keep it isolated from the
   EpiSignal application and database.
2. Configure Umami's database using the database engine, connection details,
   and persistent storage required by the selected Umami release.
3. Configure a dedicated analytics hostname/domain and its TLS certificate in
   Coolify. The tracker URL must point to that hostname's `script.js`.
4. Create the EpiSignal website inside Umami using the public EpiSignal web
   hostname.
5. Obtain the website ID from the Umami website settings.
6. Set these EpiSignal web build environment variables:

   ```env
   NEXT_PUBLIC_UMAMI_WEBSITE_ID=<website-id>
   NEXT_PUBLIC_UMAMI_SCRIPT_URL=https://analytics.example.com/script.js
   ```

   Do not commit the real website ID or hostname to the repository.
7. Redeploy EpiSignal so the public variables are included in the Next.js web
   build.
8. Verify analytics reception by opening the public site, navigating between
   Map, Briefing, and an event page, and checking that page views and approved
   custom events appear in Umami. Confirm that search text, event IDs, signal
   content, and full source URLs are absent from event properties.
9. Document and test backup/update procedures for the Umami database and
   persistent storage before relying on the analytics history.

## Safety and behavior

If either environment variable is missing, EpiSignal omits the Umami script
and all analytics calls become no-ops. The site must continue working normally.
The integration does not add advertising trackers, session replay,
fingerprinting, Google Analytics, or Meta Pixel.

Umami receives only the approved low-cardinality event names and properties
implemented in the web analytics helper. Search parameters are excluded from
automatic page-view collection. Page views are sent manually with the bounded
paths `/`, `/briefing`, and `/events/:public_id`; event pages never send their
real public ID, headline, or referrer. Source clicks send only a bounded,
normalized domain value.

## Briefing ranking aggregate sync

The ranking worker reads Umami from the server side; browser page requests do
not carry the Umami API token and the public dashboard API never calls Umami.
The worker uses the self-hosted Umami API under `/api`, authenticates with a
server-only Bearer token, and requests:

```text
GET /api/websites/:websiteId/event-data-pivot
    ?startAt=<unix milliseconds>
    &endAt=<unix milliseconds>
    &eventName=event_impression|briefing_event_open
    &page=<1-based page>
    &pageSize=<bounded page size>
```

This targets Umami's documented event-data pivot response: rows provide
`sessionId`, `eventName`, `propertyKeys`, and `propertyValues`. The worker
uses a rolling 48-hour window, deduplicates by `(event_id, sessionId)` in
memory, and discards session identifiers before the database upsert. Only
`event_impression` rows with `surface=briefing` contribute impressions;
`briefing_event_open` contributes opens. Unknown or malformed public IDs are
skipped and counted, never stored.

The aggregate table stores counts, baseline CTR, Bayesian-smoothed CTR,
percentile engagement, the exact window, and calculation time. If Umami is
unavailable or the aggregate is older than the one-hour freshness bound, the
dashboard falls back to recency-only ordering. Configure the worker with
`BRIEFING_RANKING_ENABLED`, `UMAMI_BASE_URL`, `UMAMI_WEBSITE_ID`,
`UMAMI_API_TOKEN`, and `UMAMI_TIMEOUT_SECONDS`; the flag remains `false` until
the shadow period has been reviewed.

This repository does not pin the separately hosted Umami release. Before
enabling the worker, operators must verify that the installed Umami version
supports the documented `event-data-pivot` endpoint and Bearer-token
authentication, then run the sync against a non-production window and confirm
that logs contain counts and error types only.
