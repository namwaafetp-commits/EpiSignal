# EpiSignal

Early warning for disease outbreaks. EpiSignal watches official public health
reporting and local news, decides what is worth attention before it is
confirmed, and keeps the distinction between what is interesting and what is
proven.

## Language

### Sources and provenance

**Source**:
The organization that published a document. A publisher is a source; the radar
that found the publisher is not.
_Avoid_: feed, outlet, provider.

**Discovery**:
Learning that an article exists, from metadata alone, without reading it.
_Avoid_: search, crawl.

**Sighting**:
One article as a discovery reported it: a title, a link, a domain, and the time
it was seen. It carries no body and is not yet evidence.
_Avoid_: hit, result.

**Signal**:
One retrieved document from one source, stored with its own text and its own
timestamps. The unit everything downstream reasons about.
_Avoid_: article, item, record.

**Primary**:
Among several signals carrying the same article, the one seen first. The others
are duplicates and point at it.
_Avoid_: canonical, original, master.

### Judgement

**Relevance**:
Whether a signal concerns a public health event at all. Decided before anything
is extracted from it.
_Avoid_: interesting, useful.

**Extraction**:
The structured epidemiological facts read out of a signal's text: disease,
pathogen, places, counts, dates, and how the disease is spreading.
_Avoid_: parse, analysis, enrichment.

**Source span**:
A short passage copied verbatim from the signal's own text, offered as the
support for one extracted fact. A fact without one is a claim the system is
making on its own behalf.
_Avoid_: quote, citation, snippet.

**Grounding**:
Confirming that an extracted fact's source span really occurs in the signal's
text. Grounding is checked, never assumed.
_Avoid_: verification, which in this project means something else entirely.

**Confidence**:
A model's own estimate of how sure it is. One input among several, never a
reason on its own to accept a fact or to promote a signal.
_Avoid_: score, certainty, probability.

**English title**:
An English title for the signal, translated when the source article is not in
English and preserving the original headline when it is. Produced by the
extraction pass so every downstream reader sees what the signal is about in a
common language.
_Avoid_: headline, translated title.

**Brief**:
A five-slot structured English summary of an extraction (`what_where`, `counts`,
`timing`, `spread`, `reporting`). Every slot is filled; unmentioned facts state
their absence honestly.
_Avoid_: summary, bullet points, narrative.

**Slot**:
One fixed category within a brief (`what_where`, `counts`, `timing`, `spread`,
`reporting`). Slots are ordered and non-optional.
_Avoid_: section, field, category.

**Pre-group**:
A bounded grouping of normalized signals by query rule group, publisher
country, and a one-to-two-day window, made before any AI call so that one
representative speaks for the group. Not a story cluster: it uses only facts
that exist before extraction.
_Avoid_: story gate, pre-cluster, batch.

**Representative**:
The one signal in a pre-group chosen for classification and extraction,
ranking official publishers and credibility first, then earliest sighted. The
others wait as deferred; none of them is deleted or promoted to evidence by
this choice.
_Avoid_: primary, canonical pick.

**Deferred**:
A member of a pre-group waiting while its representative is processed.
Deferral is membership, not a processing status; it ends when the group
resolves or expires, and a deferred signal is never counted as corroboration.
_Avoid_: skipped, dropped, queued.

### Human review

**Review case**:
One explicit request for a human decision about one signal, opened with the
reason automation refused to continue. A signal can have several review cases
over its lifetime, but only one may be open at a time.
_Avoid_: queue item, ticket, alert.

**Resolution**:
The recorded human decision that closes a review case. It says who decided,
when, why, and which disease or event was selected when the decision needs one.
It never erases the review case or the evidence that caused it.
_Avoid_: fix, override, approval.

**Dismissal**:
A resolution that deliberately ends automated processing for a signal while
preserving the signal and its review history. It is not deletion and does not
mean the source was wrong.
_Avoid_: ignore, reject, drop.

### The model ladder

**Tier**:
A rung of the model ladder, ordered from cheapest to most capable.
_Avoid_: level, stage.

**Escalation**:
Re-asking a more capable tier after a deterministic check rejected the previous
answer. Never triggered by a document's language or length.
_Avoid_: retry, fallback, upgrade.

**Unavailable**:
The provider could not be asked: refused, timed out, or out of quota. Distinct
from a rejected answer, because nothing was learned and nothing is recorded
against the signal.
_Avoid_: failed, error.

**Cost row**:
The record of one request made to a model: which model, how many tokens, how
long it took, what it cost, and whether its answer was accepted. Written for
refused and rejected requests too.
_Avoid_: log entry, usage record.

### Events and evidence

**Event**:
A real outbreak in the world, assembled from many signals over time. A signal is
reporting; an event is the thing being reported.
_Avoid_: incident, story, cluster.

**Observation**:
One reported measurement attached to an event, keeping the source and the date it
describes. An event's history is its observations, never an overwritten total.
_Avoid_: update, datapoint.

**Delta pass**:
A cheap model call made after a cluster attaches to a recently observed event,
comparing the latest attached brief with the newly attached one and writing
what changed onto the new observation. It summarizes two briefs; it never
re-reads the article and never rewrites an earlier observation.
_Avoid_: follow-up extraction, re-summary, brief merge.

**Location role**:
How a place relates to an event: where it happened, where exposure occurred,
where it was diagnosed, where travel led, who reported it, or what area is
affected. A place with no role is not usable.
_Avoid_: geo, region, tag.

### Places

**Gazetteer**:
The reference list of places the system can recognize, with their coordinates
and their administrative hierarchy. Seeded and reviewed, never written by a
pass, and never extended by a model.
_Avoid_: geo database, lookup table.

**Precision**:
How specific a resolved location actually is: a place, a district, a province,
a country, or nothing. Recorded on every resolution, because a province centroid
and a town centre are both coordinates and only the precision tells them apart.
_Avoid_: accuracy, granularity, zoom.

**Coarsening**:
Answering at a less specific precision when the specific answer is ambiguous.
A province centroid is a true statement about a smaller place inside it; the
most populous candidate is a guess. Coarsening is the system's only response to
ambiguity.
_Avoid_: fallback, approximation, best guess.

**Unresolved**:
A place the article named that the gazetteer could not match. The location is
still recorded, with the words the article used and no coordinate, because a
place that cannot be found is different from a place that was never mentioned.
_Avoid_: not found, failed, null island.

**Early signal score**:
How interesting a signal is for surveillance.

**Evidence score**:
How strongly a signal is supported. Kept separate from the early signal score
permanently; a local report can be highly interesting and weakly supported at the
same time, and merging the two destroys the distinction the product exists to
make.

**Verification status**:
How well corroborated an event is, decided from the standing of the sources that
reported it. Only an official authority can make an event confirmed, and no model
confidence can.
_Avoid_: confirmed, validated, trusted, as bare adjectives.
