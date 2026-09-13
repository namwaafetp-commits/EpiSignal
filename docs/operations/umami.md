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
