# EpiSignal — Phase 1 Build Specification

> **Working title:** EpiSignal  
> **Tagline:** Open global outbreak intelligence  
> **Goal:** Build a beautiful, public, searchable, traceable global infectious-disease surveillance platform that converts many public sources into structured epidemiological events.

---

# 1. Product Vision

EpiSignal is **not a normal news aggregator**.

The primary object is an **epidemiological event**, not an article.

Many reports from WHO, ECDC, Africa CDC, ministries of health, reputable media, and other public sources may all describe the same real-world outbreak. EpiSignal should:

1. ingest those reports as individual **signals**,
2. determine whether they are relevant to infectious-disease/public-health surveillance,
3. extract structured epidemiological information,
4. link duplicate/related signals to the same **event**,
5. preserve the history of changing numbers,
6. show every important claim together with its source,
7. allow the user to open the original source URL,
8. display events on an interactive world map,
9. support human-readable and structured search,
10. eventually become an open dataset/API for epidemiologists and researchers.

The guiding idea is:

```text
NEWS / REPORT / BULLETIN
        ↓
      SIGNAL
        ↓
AI + RULES + EMBEDDINGS
        ↓
      EVENT
        ↓
MAP + SEARCH + TIMELINE + SOURCES + DATA
```

---

# 2. Non-Negotiable Product Principle

## Source traceability is mandatory

Every extracted epidemiological fact must preserve provenance.

The UI should never merely say:

> 327 cases

It should be possible to inspect:

```text
327 confirmed cases

Source:
Angola Ministry of Health

Reported:
25 Aug 2026

Original URL:
https://...

Previous value:
285 confirmed cases
23 Aug 2026
```

Users must always be able to open the original source.

AI should help interpret reports, but **AI is not itself the authority**.

Verification comes from evidence and sources.

---

# 3. Phase 1 Objective

Build a production-quality MVP proving that EpiSignal can turn a manageable number of trustworthy sources into a usable global outbreak intelligence product.

Phase 1 should focus on:

- excellent data model,
- source provenance,
- event clustering,
- epidemiological correctness,
- beautiful responsive UI,
- fast search,
- map exploration,
- event timelines,
- transparent AI processing.

Do **not** attempt to ingest the entire internet in Phase 1.

---

# 4. Phase 1 Target Scope

Start with approximately **5–15 high-quality public sources**.

Suggested starting source groups:

- WHO Disease Outbreak News
- WHO regional offices
- ECDC
- Africa CDC
- PAHO
- US CDC outbreak/public-health feeds where suitable
- selected national Ministries of Health
- ReliefWeb where useful
- selected reputable RSS/news feeds
- GDELT later if needed

For the MVP, prioritize **official structured or semi-structured sources** before attempting thousands of local news sites.

---

# 5. Phase 1 Core Features

## Must Have

### Public homepage

- global outbreak map
- current active / recently updated events
- prominent search box
- trending / recently updated diseases
- latest event feed
- responsive design
- fast first-load performance

### Event search

Search by:

- disease
- pathogen
- country
- administrative region
- date range
- event status
- verification status
- keywords

Natural-language search can be added in Phase 1 if straightforward.

Examples:

```text
cholera outbreaks in Africa this month
H5N1 human cases since 2025
measles Southeast Asia
unknown respiratory illness with deaths
```

The system should translate natural language into visible structured filters.

Never hide AI interpretation.

Example UI:

```text
Disease: Cholera
Region: Africa
Period: Last 30 days
Status: Active
```

---

# 6. Core Domain Model

The system should explicitly separate:

```text
SOURCE
SIGNAL
EVENT
EVENT OBSERVATION
```

These are different objects.

---

# 7. Source Model

A **source** represents an organization/feed/provider.

Suggested fields:

```sql
sources

id uuid primary key
name text
source_type text
country_code text nullable
base_url text
feed_url text nullable
credibility_tier text
is_official boolean
language text nullable
active boolean default true
created_at timestamptz
updated_at timestamptz
```

Possible `source_type`:

```text
international_organization
regional_public_health_agency
national_public_health_agency
ministry_of_health
scientific
humanitarian
major_media
local_media
other
```

Possible credibility tier:

```text
official
high
medium
unknown
```

Do not equate "official" with automatically correct.

---

# 8. Signal Model

A **signal** is one article/report/bulletin/post/page that may contain epidemiologically relevant information.

Suggested fields:

```sql
signals

id uuid primary key

source_id uuid references sources(id)

external_id text nullable
url text unique
canonical_url text nullable

title text
raw_text text nullable
summary text nullable

published_at timestamptz nullable
retrieved_at timestamptz not null

language text nullable

content_hash text nullable

relevance_score numeric nullable
public_health_relevant boolean nullable

signal_type text nullable

ai_extraction jsonb nullable
ai_model text nullable
ai_processed_at timestamptz nullable

processing_status text

created_at timestamptz
updated_at timestamptz
```

Possible `signal_type`:

```text
outbreak_report
surveillance_update
case_report
imported_case
public_health_action
vaccination_campaign
risk_assessment
situation_report
research
rumor
unknown
```

Important:

A report containing the word "cholera" must **not automatically create a cholera outbreak**.

For example:

```text
Bangladesh launches preventive cholera vaccination campaign
```

should likely be classified:

```text
signal_type = vaccination_campaign
create_event = false
```

unless it contains evidence of an active event.

---

# 9. Event Model

An **event** represents the real-world epidemiological occurrence.

Suggested fields:

```sql
events

id uuid primary key

public_id text unique
slug text unique

title text

disease_id uuid nullable
pathogen_id uuid nullable

event_type text

status text
verification_status text

country_code text nullable
admin1 text nullable
admin2 text nullable

latitude double precision nullable
longitude double precision nullable

geometry geography(Point,4326) nullable

first_signal_at timestamptz nullable
event_start_date date nullable
last_updated_at timestamptz

attention_score numeric nullable
confidence_score numeric nullable

ai_summary text nullable

created_at timestamptz
updated_at timestamptz
```

Example public ID:

```text
ES-2026-000184
```

Possible `event_type`:

```text
outbreak
cluster
single_case
imported_case
seasonal_surveillance
zoonotic_event
foodborne_outbreak
healthcare_associated_outbreak
unknown_disease_event
other
```

Possible `status`:

```text
monitoring
ongoing
expanding
stable
declining
resolved
unknown
```

Possible `verification_status`:

```text
officially_confirmed
high_credibility
signal
unverified
rumor_monitoring
```

---

# 10. Event-Signal Relationship

One event may have many signals.

One signal may potentially relate to multiple events, although keep Phase 1 simple if needed.

```sql
event_signals

event_id uuid references events(id)
signal_id uuid references signals(id)

relationship_type text
match_score numeric nullable
is_primary boolean default false

created_at timestamptz

primary key (event_id, signal_id)
```

Possible relationships:

```text
initial_report
update
supporting_source
risk_assessment
public_health_response
correction
background
```

---

# 11. Event Observations

Do not overwrite changing case/death numbers.

Every epidemiological update must be represented as an observation.

```sql
event_observations

id uuid primary key
event_id uuid references events(id)
signal_id uuid references signals(id)

observation_date date nullable
reported_at timestamptz nullable

suspected_cases integer nullable
probable_cases integer nullable
confirmed_cases integer nullable
total_cases integer nullable

new_cases integer nullable

deaths integer nullable
new_deaths integer nullable

recoveries integer nullable

hospitalizations integer nullable

cfr numeric nullable

affected_admin_areas integer nullable

notes text nullable

extraction_confidence numeric nullable

created_at timestamptz
```

Example:

```text
12 Aug
confirmed_cases = 4665
deaths = 2184
source = WHO DON

13 Aug
confirmed_cases = 4566
deaths = 2128
source = WHO risk assessment

22 Aug
confirmed_cases = 5514
deaths = 2642
source = ECDC / national surveillance
```

The application must preserve all of them.

Never silently overwrite conflicting numbers.

---

# 12. Epidemiological Date Model

Do not treat all dates as equivalent.

Where possible distinguish:

```text
publication_date
report_date
data_as_of_date
event_start_date
symptom_onset_date
confirmation_date
notification_date
```

Phase 1 can support a subset but the schema should allow expansion.

---

# 13. Geographic Model

The system should distinguish different geographic meanings.

At minimum support:

```text
event_location
exposure_location
diagnosis_location
reporting_location
travel_location
```

This matters for imported infections.

Example:

```text
Andes hantavirus

Exposure:
Argentina

Diagnosis:
France

Travel:
Spain

Local transmission in France:
No
```

Do not reduce this to simply:

```text
country = France
```

---

# 14. Event Location Table

Suggested:

```sql
event_locations

id uuid primary key
event_id uuid references events(id)

location_role text

country_code text nullable
admin1 text nullable
admin2 text nullable
place_name text nullable

latitude double precision nullable
longitude double precision nullable
geometry geography(Point,4326) nullable

geocoding_source text nullable
geocoding_confidence numeric nullable

created_at timestamptz
```

Possible roles:

```text
primary
exposure
diagnosis
travel
reporting
affected_area
```

---

# 15. Disease and Pathogen Tables

Avoid uncontrolled disease naming.

```sql
diseases

id uuid primary key
canonical_name text
slug text unique
icd10 text nullable
synonyms text[] nullable
category text nullable
```

Examples:

```text
Dengue
Measles
Cholera
Ebola virus disease
West Nile virus disease
Avian influenza
Unknown respiratory illness
Unknown disease
```

Optional:

```sql
pathogens

id uuid primary key
canonical_name text
taxonomy text nullable
synonyms text[] nullable
```

---

# 16. Ingestion Pipeline

Initial pipeline:

```text
Scheduler
   ↓
Fetch RSS/API/web page
   ↓
Normalize document
   ↓
Canonicalize URL
   ↓
Content hash
   ↓
Duplicate signal check
   ↓
Store raw signal
   ↓
Relevance classifier
   ↓
Structured extraction
   ↓
Geocoding
   ↓
Candidate event retrieval
   ↓
Event matching
   ↓
Update existing event
OR
Create new event
   ↓
Create observation
   ↓
Update event summary/status
```

---

# 17. Recommended Ingestion Architecture

Use Python workers.

Suggested components:

```text
FastAPI
PostgreSQL
PostGIS
Supabase
Python workers
cron / scheduler
Next.js frontend
```

Possible repository structure:

```text
episignal/

apps/
  web/
  api/

workers/
  ingestion/
  extraction/
  event_matching/
  geocoding/

packages/
  shared/
  schemas/
  epidemiology/

database/
  migrations/
  seeds/

docs/
```

A monorepo is preferred for Phase 1.

---

# 18. Duplicate Signal Detection

Before AI processing, eliminate exact/simple duplicates.

Use:

1. canonical URL,
2. content hash,
3. normalized title similarity,
4. optional embedding similarity.

Example:

```text
Reuters article
→ syndicated copy on Site A
→ syndicated copy on Site B
```

These should usually represent the same underlying signal family rather than generating three independent pieces of evidence.

Keep source URLs where useful, but avoid artificially inflating evidence strength.

---

# 19. Event Matching / Clustering

This is one of the most important Phase 1 components.

A candidate signal should be compared against existing events.

Start with deterministic/rule scoring.

Example:

```text
same disease              +0.30
same country              +0.20
near geographic location  +0.20
compatible date window    +0.15
semantic similarity       +0.15
```

Example logic:

```text
score >= 0.80
→ automatically link

score 0.55–0.79
→ send to stronger classifier / LLM

score < 0.55
→ likely new event
```

The actual weights should be configurable.

Do not bury this logic inside an opaque prompt.

---

# 20. AI Usage Strategy

Use AI selectively.

Recommended layers:

```text
RULES
+
small/cheap classifier
+
embeddings
+
LLM for ambiguous cases
```

Do not send everything to an expensive model.

Potential AI tasks:

- relevance classification
- signal type classification
- disease extraction
- pathogen extraction
- location extraction
- epidemiological number extraction
- date extraction
- imported/local transmission distinction
- event matching
- event summarization
- source comparison
- contradiction detection

---

# 21. Required Structured Extraction Schema

The AI extraction output should be validated using a strict schema.

Example conceptual structure:

```json
{
  "is_public_health_relevant": true,
  "signal_type": "outbreak_report",

  "disease": {
    "name": "Cholera",
    "confidence": 0.97
  },

  "pathogen": {
    "name": "Vibrio cholerae",
    "confidence": 0.91
  },

  "locations": [
    {
      "role": "primary",
      "country": "Angola",
      "admin1": "Luanda",
      "place_name": "Luanda"
    }
  ],

  "epidemiology": {
    "suspected_cases": null,
    "confirmed_cases": 327,
    "total_cases": 327,
    "deaths": 14,
    "new_cases": 42,
    "new_deaths": 3
  },

  "dates": {
    "data_as_of": "2026-08-25",
    "publication_date": "2026-08-25"
  },

  "transmission": {
    "imported": false,
    "local_transmission": true
  },

  "create_or_update_event": true,

  "confidence": 0.94
}
```

Use Pydantic/Zod/JSON Schema validation.

Invalid model output must fail safely.

---

# 22. AI Safety / Trust Rules

The model must never independently declare:

```text
outbreak confirmed
```

Instead it may say:

```text
official source reports...
```

Verification is determined from source provenance.

Examples:

```text
WHO / Ministry / CDC
→ officially_confirmed

multiple independent reputable sources
→ high_credibility

single credible report
→ signal

weak/unverified source
→ unverified
```

The system should expose this distinction in the UI.

---

# 23. Source Discrepancy Handling

If two trustworthy reports disagree:

Do not select one silently.

Example:

```text
SOURCE DISCREPANCY

WHO DON
12 Aug
4,665 cases

WHO risk assessment
13 Aug
4,566 cases

ECDC
22 Aug
5,514 cases
```

The application should:

1. preserve all observations,
2. identify the newest relevant observation,
3. show source and as-of date,
4. optionally flag the discrepancy,
5. allow users to inspect the older values.

---

# 24. Event Summary

Event summaries should be short and evidence-aware.

Bad:

```text
A dangerous epidemic is spreading rapidly.
```

Better:

```text
Cholera activity in Luanda has increased during the past two weeks.
The most recent official report records 327 confirmed cases and 14 deaths.
Three additional districts have reported cases.
```

Every factual claim should have traceable supporting signal(s).

---

# 25. Phase 1 UI Philosophy

The product should feel like:

```text
Google Maps
+
Reuters
+
PubMed
```

Not like a conventional BI dashboard.

Design priorities:

1. beautiful
2. fast
3. understandable to public users
4. powerful for epidemiologists
5. minimal visible complexity
6. progressive disclosure
7. excellent mobile support

---

# 26. Homepage UX

Primary user question:

> What is happening in infectious disease around the world right now?

Recommended desktop layout:

```text
┌───────────────────────────────────────────────────────┐
│ EpiSignal       Search...                About        │
├───────────────────────────────────────────────────────┤
│                                                       │
│ What's happening in global health right now?          │
│                                                       │
│ 🔎 Search disease, country, outbreak, pathogen...     │
│                                                       │
│ ┌─────────────────────────┬─────────────────────────┐ │
│ │                         │ LIVE                    │ │
│ │      WORLD MAP          │                         │ │
│ │                         │ Cholera — Angola        │ │
│ │   ●       ●      ●      │ Ebola — DRC            │ │
│ │                         │ Dengue — Brazil         │ │
│ └─────────────────────────┴─────────────────────────┘ │
│                                                       │
│ Recently updated                                     │
└───────────────────────────────────────────────────────┘
```

---

# 27. Map Behavior

Avoid a giant explosion of pins.

Use progressive detail.

## Global zoom

- clustered activity
- counts
- broad intensity

## Country zoom

- disease clusters
- event counts

## Local zoom

- individual outbreak/event locations

Example:

```text
Thailand

Dengue      7 events
Measles     2 events
Influenza   3 events
```

Only show individual event points when geographically useful.

---

# 28. Map / List / Timeline

Search results should support:

```text
MAP | LIST | TIMELINE
```

All three are first-class views.

### Map

Best for:

- geography
- clusters
- spread

### List

Best for:

- scanning
- PubMed-like discovery
- filtering

### Timeline

Best for:

- progression
- event chronology
- historical surveillance

---

# 29. Result Card

Suggested result card:

```text
CHOLERA

Luanda, Angola

327 confirmed cases
14 deaths

Status:
Ongoing

Verification:
Officially confirmed

Updated:
4 hours ago

Sources:
WHO · Africa CDC · Reuters · +4

[View event]
```

Do not overload cards.

---

# 30. Event Page

This is the core product page.

Suggested structure:

```text
CHOLERA
Luanda, Angola

● Ongoing
✓ Officially confirmed

327 cases
14 deaths
CFR 4.3%

+42 cases this week
+3 deaths this week

--------------------------------

Overview
Timeline
Geography
Sources
Data
```

---

# 31. Event Overview Tab

Show:

- short AI-assisted evidence-backed summary
- latest epidemiological values
- trend indicators
- reason for attention
- verification
- last update
- source count

Example:

```text
Why this event matters

↑ Case count increasing
↗ Geographic expansion
● New deaths reported
✓ Multiple official sources
```

---

# 32. Event Timeline Tab

Render observations chronologically.

Example:

```text
03 Aug
43 suspected cases
First cluster reported

08 Aug
Vibrio cholerae confirmed

14 Aug
Spread to second district

21 Aug
251 cumulative cases

25 Aug
327 cases
14 deaths
```

Also render a simple time-series graph when possible.

Phase 1 graph:

```text
cases over time
deaths over time
```

Do not attempt complicated epi curves unless data quality supports them.

---

# 33. Sources Tab

This tab is essential.

Example:

```text
WHO
Official
25 Aug 2026

Angola Ministry of Health
Official
25 Aug 2026

Africa CDC
Official
24 Aug 2026

Reuters
Major media
24 Aug 2026
```

Each item must contain:

- source name
- title
- publication date
- extracted role
- original URL
- "Open original source"

Never hide the source behind an AI summary.

---

# 34. Data Tab

Show structured data.

Example:

```text
Latest observation

Confirmed cases     327
Deaths               14
CFR                  4.3%
Affected districts    6
Data as of          25 Aug 2026
```

Also show observation history.

Provide:

```text
Download CSV
Download JSON
```

GeoJSON can be added if trivial.

---

# 35. Mobile UX

Mobile should behave closer to Google Maps.

Recommended structure:

```text
SEARCH

MAP

──────────────
bottom sheet
──────────────

Active events
Recently updated
```

Tapping an event should open a bottom sheet first.

The user should not immediately lose the map context.

---

# 36. Visual Design

Suggested design direction:

```text
Background:
off-white / light neutral gray

Primary:
deep navy

Accent:
teal / cyan

Watch:
amber

High concern:
orange

Critical:
red
```

Do not color the whole map red.

Red should be meaningful and rare.

Use whitespace generously.

Avoid the appearance of a government BI dashboard.

---

# 37. Typography

Recommended:

```text
English:
Inter
Geist
IBM Plex Sans

Thai later:
Noto Sans Thai
IBM Plex Sans Thai
```

Use one primary UI family.

---

# 38. Attention Score

Phase 1 may include a simple transparent attention score.

Do **not** present this as pandemic prediction.

Potential components:

```text
severity
case growth
geographic expansion
cross-border spread
novel pathogen
mortality
source confidence
```

Example UI:

```text
Public Health Attention

HIGH

Reasons:
↑ cases increasing
↗ geographic expansion
● deaths reported
✓ official confirmation
```

The reason must be more important than the score.

---

# 39. Technical Stack Recommendation

## Frontend

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
MapLibre GL JS
```

MapLibre is preferred to avoid unnecessary vendor lock-in.

Leaflet is acceptable if simpler.

---

## Backend

```text
FastAPI
Python
Pydantic
```

Alternative:

Next.js server actions/API routes are acceptable for simple CRUD, but Python should handle surveillance/AI workers.

---

## Database

```text
PostgreSQL
PostGIS
```

Supabase is strongly recommended for Phase 1 because it provides:

- hosted Postgres
- auth if needed later
- REST
- realtime if useful later
- storage
- manageable early infrastructure

Auth is **not required for public MVP**.

---

# 40. Search

Start with PostgreSQL.

Use:

```text
GIN indexes
full-text search
pg_trgm
```

Do not introduce Elasticsearch on day one.

Later upgrade to:

```text
Typesense
Meilisearch
OpenSearch
```

only when justified.

---

# 41. Geocoding

Use a free/open approach for Phase 1 where possible.

Possible options:

- OpenStreetMap/Nominatim with appropriate usage policy
- GeoNames
- preloaded administrative boundary datasets
- local gazetteer

Cache every geocoding result.

Do not repeatedly query external geocoding services for the same place.

Build a normalized place lookup table over time.

---

# 42. Scheduler

Phase 1 can use:

```text
cron
GitHub Actions
Supabase scheduled function
VPS scheduler
```

Preferred if running a Python backend:

```text
single worker process
+
cron/APS cheduler/Celery later
```

Avoid complex distributed queues initially.

---

# 43. Processing Status

Every signal should have explicit processing state.

Example:

```text
fetched
normalized
classified
extracted
geocoded
matched
published
failed
needs_review
```

Never let failed AI output disappear silently.

---

# 44. Manual Review

Create a basic internal review screen, even if very simple.

It should show:

```text
Needs review

Signal title
Source
AI disease
AI location
Candidate event
Match score

[Link to event]
[Create new event]
[Ignore]
```

A human-in-the-loop escape hatch will save enormous pain.

This admin tool does not need beautiful design in Phase 1.

---

# 45. Provenance Architecture

Each derived value should ideally support:

```text
value
source signal
extraction method
confidence
date
```

For example:

```json
{
  "field": "confirmed_cases",
  "value": 327,
  "signal_id": "...",
  "confidence": 0.96,
  "data_as_of": "2026-08-25"
}
```

This enables later auditing.

---

# 46. Public API — Phase 1

Provide simple read-only endpoints.

Examples:

```http
GET /api/events
GET /api/events/{public_id}
GET /api/events/{public_id}/observations
GET /api/events/{public_id}/signals
GET /api/diseases
GET /api/countries
```

Filtering:

```http
GET /api/events?
disease=dengue
&country=THA
&from=2026-01-01
&status=ongoing
```

Responses should be clean JSON.

API versioning:

```text
/api/v1/
```

preferred from the beginning.

---

# 47. Data Export

Event pages and search results should eventually allow:

```text
CSV
JSON
GeoJSON
```

Phase 1 minimum:

```text
CSV
JSON
```

---

# 48. SEO / Public Discoverability

Each event should have a stable URL.

Example:

```text
/events/es-2026-000184-cholera-luanda-angola
```

Include metadata for:

```text
disease
location
event status
last update
```

This may eventually make EpiSignal useful through normal search engines.

---

# 49. Performance Requirements

Target:

```text
Homepage initial load < 3 sec on normal connection
Search response < 1 sec for indexed queries
Map interactions feel immediate
Event page < 2 sec typical
```

Do not block rendering on AI.

AI processing happens asynchronously in ingestion workers.

---

# 50. Accessibility

Minimum:

- keyboard-accessible search
- semantic HTML
- good contrast
- non-color indicators for severity/status
- readable maps/cards
- responsive text sizing

Severity cannot be communicated using color alone.

---

# 51. Phase 1 Privacy

The product should contain only public aggregated outbreak information.

Do not ingest:

- patient names
- phone numbers
- precise residential addresses
- personally identifiable case information

If source reports include PII, do not expose it through structured extraction.

Public-health event intelligence is the goal, not case-level surveillance.

---

# 52. Copyright / Content Storage

Prefer storing:

- title
- metadata
- extracted structured facts
- short summary
- source URL

Avoid republishing full copyrighted articles.

For sources where full text is required internally for extraction, ensure storage and use comply with source terms.

Public UI should primarily point users back to the original source.

---

# 53. Seed Diseases

Use a practical initial disease vocabulary.

Suggested:

```text
Cholera
Dengue
Measles
Mpox
Ebola virus disease
Marburg virus disease
Yellow fever
West Nile virus disease
Chikungunya
Avian influenza
Seasonal influenza
COVID-19
MERS
Lassa fever
Rift Valley fever
Polio
Diphtheria
Pertussis
Meningococcal disease
Anthrax
Hantavirus infection
Leptospirosis
Malaria
Zika virus disease
Typhoid fever
Salmonellosis
Unknown respiratory illness
Unknown febrile illness
Unknown disease
```

Do not hardcode only this list.

---

# 54. First Source Connectors

Build source adapters with a common interface.

Conceptual Python interface:

```python
class SourceConnector:
    source_id: str

    async def fetch(self) -> list[RawDocument]:
        ...

    async def normalize(self, document: RawDocument) -> NormalizedSignal:
        ...
```

Implement first:

```text
WHO DON
ECDC
Africa CDC
PAHO
```

Then expand.

---

# 55. Suggested First Build Sequence

## Step 1 — Repository foundation

Create:

```text
Next.js web
FastAPI API
PostgreSQL/PostGIS
shared types
environment configuration
Docker Compose for local dev
```

---

## Step 2 — Database

Implement migrations for:

```text
sources
signals
diseases
pathogens
events
event_signals
event_observations
event_locations
```

Seed disease vocabulary.

---

## Step 3 — Source ingestion

Implement WHO DON first.

Requirements:

- fetch new documents
- canonicalize URL
- prevent duplicate ingestion
- store title/date/text/URL
- processing state

Then implement ECDC.

---

## Step 4 — AI structured extraction

Create strict Pydantic schema.

Run extraction against stored signals.

Do not build event matching until extraction output is stable.

---

## Step 5 — Geocoding

Normalize extracted locations.

Cache results.

Store coordinates + confidence.

---

## Step 6 — Event creation

Initially use conservative rules.

Create new event when there is no strong match.

Do not over-merge.

False merging is more dangerous than temporary duplicate events.

---

## Step 7 — Event matching

Implement candidate retrieval + weighted score.

Add embedding similarity.

Escalate ambiguous cases to LLM.

---

## Step 8 — Public API

Implement:

```text
events list
event detail
observations
sources
filters
```

---

## Step 9 — Homepage UI

Build beautiful global map + event feed.

Desktop and mobile from the beginning.

---

## Step 10 — Event page

Implement:

```text
overview
timeline
sources
data
```

This is the most important page.

---

## Step 11 — Search

Implement structured search.

Then optionally natural-language query parsing.

---

## Step 12 — Admin review

Basic needs-review queue.

---

# 56. MVP Acceptance Criteria

The MVP is considered successful when:

## Data

- at least 4 live sources ingest automatically
- duplicate URLs are not duplicated
- extracted disease/location/numbers are stored structurally
- epidemiological observations are historical, not overwritten
- source URL is preserved for every signal
- user can open original source

## Events

- multiple reports can link to one event
- new reports can update existing events
- conflicting numbers remain traceable
- imported/local distinction is supported
- surveillance updates do not automatically become false outbreaks

## UI

- usable world map
- responsive mobile layout
- list view
- event detail page
- timeline
- sources tab
- source links
- filter/search
- visually polished

## Trust

- verification status is visible
- source provenance is visible
- AI summaries never masquerade as primary evidence
- users can inspect original sources
- AI failures can enter review state

## API

- read-only event API works
- event observations are retrievable
- signal/source links are retrievable

---

# 57. Phase 1 Explicit Non-Goals

Do **not** build yet:

- thousands of sources
- social media scraping
- outbreak forecasting
- pandemic prediction
- automated risk recommendations to the public
- individual patient-level data
- complex accounts/permissions
- paid subscriptions
- native mobile application
- user reviews
- crowdsourced reports
- push notifications
- LINE/Telegram alerts
- advanced epidemiological modeling
- genomic data integration
- GISAID integration
- full multilingual UI

These can come later.

---

# 58. Future Phase 2 Ideas

After Phase 1 works:

```text
hundreds/thousands of sources
multilingual extraction
local-language media
RSS personalization
saved searches
follow disease
follow country
daily briefing
email alerts
LINE/Telegram alerts
historical event reconstruction
research API keys
GeoJSON/Parquet export
advanced source reconciliation
cross-border spread detection
trend detection
public-health attention scoring
```

---

# 59. Future Phase 3

Long-term direction:

```text
Open epidemic intelligence infrastructure
```

Potential capabilities:

- global near-real-time surveillance
- large historical event database
- researcher datasets
- citation-ready permanent event IDs
- open API
- high-quality event ontology
- outbreak comparison
- trend detection
- geographic spread analysis
- machine-assisted source reconciliation
- public-health intelligence briefings

---

# 60. Product Success Metric

Phase 1 should answer this question extremely well:

> **What infectious-disease events are happening, what evidence supports them, how are they changing, and where did the information come from?**

The user should be able to:

### Within 10 seconds

Understand what important infectious-disease events are currently happening.

### Within 30 seconds

Inspect the timeline and original evidence for an event.

### Within 60 seconds

Search/filter/download structured data relevant to their question.

---

# 61. Development Principles

1. **Evidence before AI**
2. **Events before articles**
3. **History before overwrite**
4. **Source provenance everywhere**
5. **Simple UI before feature density**
6. **Structured data before pretty summaries**
7. **Conservative event merging**
8. **Human review for ambiguity**
9. **Public usefulness before monetization**
10. **Build the ontology correctly before scaling ingestion**

---

# 62. Immediate Agent Task

Begin implementation of **EpiSignal Phase 1**.

First deliver:

1. project repository structure,
2. local Docker development environment,
3. PostgreSQL + PostGIS schema/migrations,
4. seed disease table,
5. source connector abstraction,
6. WHO DON connector,
7. ECDC connector,
8. signal ingestion pipeline,
9. strict Pydantic extraction schema,
10. initial public API,
11. initial Next.js responsive UI shell,
12. world map placeholder connected to real event records.

Do not spend excessive time on advanced AI before source ingestion, schema, provenance, and event history are working.

When architectural choices are ambiguous, prioritize:

```text
correct epidemiological representation
> provenance
> simplicity
> scalability
> cleverness
```

---

# 63. Definition of Done for the First Vertical Slice

The first complete vertical slice should demonstrate:

```text
WHO/ECDC source
      ↓
signal fetched
      ↓
stored with URL
      ↓
AI extracts disease/location/cases/deaths/date
      ↓
location geocoded
      ↓
event created
      ↓
observation created
      ↓
event appears on world map
      ↓
user opens event
      ↓
user sees timeline
      ↓
user sees source
      ↓
user clicks original report
```

If this works cleanly for real-world reports, Phase 1 has the correct foundation.

---

# Final Product Principle

> **EpiSignal should never ask users to trust the AI. It should help users inspect the evidence faster.**

That is the product.
