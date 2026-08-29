from enum import StrEnum

from sqlalchemy import Enum


class SourceType(StrEnum):
    INTERNATIONAL_ORGANIZATION = "international_organization"
    REGIONAL_PUBLIC_HEALTH_AGENCY = "regional_public_health_agency"
    NATIONAL_PUBLIC_HEALTH_AGENCY = "national_public_health_agency"
    MINISTRY_OF_HEALTH = "ministry_of_health"
    SCIENTIFIC = "scientific"
    HUMANITARIAN = "humanitarian"
    MAJOR_MEDIA = "major_media"
    LOCAL_MEDIA = "local_media"
    OTHER = "other"


class CredibilityTier(StrEnum):
    OFFICIAL = "official"
    HIGH = "high"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


class DiscoveryMethod(StrEnum):
    DIRECT = "direct"
    GDELT = "gdelt"


class FilterRuleGroup(StrEnum):
    TITLE_EXCLUSION = "title_exclusion"
    DOMAIN_BLOCKLIST = "domain_blocklist"
    # Positive evidence, matched as case-folded substring rather than a
    # pattern: rejection has to be precise, inclusion has to be generous.
    TITLE_INCLUSION = "title_inclusion"


class SignalType(StrEnum):
    OUTBREAK_REPORT = "outbreak_report"
    SURVEILLANCE_UPDATE = "surveillance_update"
    CASE_REPORT = "case_report"
    IMPORTED_CASE = "imported_case"
    PUBLIC_HEALTH_ACTION = "public_health_action"
    VACCINATION_CAMPAIGN = "vaccination_campaign"
    RISK_ASSESSMENT = "risk_assessment"
    SITUATION_REPORT = "situation_report"
    RESEARCH = "research"
    RUMOR = "rumor"
    UNKNOWN = "unknown"


class ProcessingStatus(StrEnum):
    FETCHED = "fetched"
    NORMALIZED = "normalized"
    CLASSIFIED = "classified"
    EXTRACTED = "extracted"
    GEOCODED = "geocoded"
    MATCHED = "matched"
    PUBLISHED = "published"
    # Terminal, like FAILED: a duplicate is not processed further, but unlike
    # FAILED it is a correct outcome rather than an error.
    DUPLICATE = "duplicate"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    # Terminal, like DUPLICATE: the keyword gate found no evidence in the
    # title that this article concerns a public health event. The row and its
    # title are preserved so a widened keyword list can re-gate it.
    FILTERED = "filtered"

    # Terminal, like FAILED/DUPLICATE: a dismissed signal is preserved for
    # provenance and audit, but no automated stage selects it.
    DISMISSED = "dismissed"


class Precision(StrEnum):
    """How specific a resolved location actually is.

    Ordered from most to least specific. `unresolved` is a real answer, not a
    missing one: the article named a place the gazetteer could not match, which
    is different from the article naming no place at all.
    """

    PLACE = "place"
    ADMIN2 = "admin2"
    ADMIN1 = "admin1"
    COUNTRY = "country"
    UNRESOLVED = "unresolved"


class AiPurpose(StrEnum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    # The delta pass after an attach: two briefs compared, not an article read.
    FOLLOW_UP = "follow_up"


class AiProvider(StrEnum):
    """Who serves a roster rung. The ladder stays one ladder; the adapter is
    chosen per rung from this value."""

    OPENROUTER = "openrouter"
    GEMINI = "gemini"


class AiOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    # The provider never answered: refused, timed out, or out of quota. Kept
    # apart from REJECTED because nothing was learned about the signal, so the
    # signal must stay selectable rather than be sent for review.
    UNAVAILABLE = "unavailable"


class EventType(StrEnum):
    OUTBREAK = "outbreak"
    CLUSTER = "cluster"
    SINGLE_CASE = "single_case"
    IMPORTED_CASE = "imported_case"
    SEASONAL_SURVEILLANCE = "seasonal_surveillance"
    ZOONOTIC_EVENT = "zoonotic_event"
    FOODBORNE_OUTBREAK = "foodborne_outbreak"
    HEALTHCARE_ASSOCIATED_OUTBREAK = "healthcare_associated_outbreak"
    UNKNOWN_DISEASE_EVENT = "unknown_disease_event"
    OTHER = "other"


class EventStatus(StrEnum):
    MONITORING = "monitoring"
    ONGOING = "ongoing"
    EXPANDING = "expanding"
    STABLE = "stable"
    DECLINING = "declining"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    OFFICIALLY_CONFIRMED = "officially_confirmed"
    HIGH_CREDIBILITY = "high_credibility"
    SIGNAL = "signal"
    UNVERIFIED = "unverified"
    RUMOR_MONITORING = "rumor_monitoring"


class RelationshipType(StrEnum):
    INITIAL_REPORT = "initial_report"
    UPDATE = "update"
    SUPPORTING_SOURCE = "supporting_source"
    RISK_ASSESSMENT = "risk_assessment"
    PUBLIC_HEALTH_RESPONSE = "public_health_response"
    CORRECTION = "correction"
    BACKGROUND = "background"


class LocationRole(StrEnum):
    PRIMARY = "primary"
    EXPOSURE = "exposure"
    DIAGNOSIS = "diagnosis"
    TRAVEL = "travel"
    REPORTING = "reporting"
    AFFECTED_AREA = "affected_area"


class PipelineChain(StrEnum):
    DAILY = "daily"


class PipelineTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class PipelineRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # Some stage raised. The chain still ran every later stage.
    FAILED = "failed"


class StoryGroupState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class StoryGroupRole(StrEnum):
    REPRESENTATIVE = "representative"
    DEFERRED = "deferred"


class ReviewReason(StrEnum):
    RETRIEVAL_FAILED = "retrieval_failed"
    EXTRACTION_REJECTED = "extraction_rejected"
    DISEASE_UNRESOLVED = "disease_unresolved"
    LOCATION_UNRESOLVED = "location_unresolved"
    EVENT_MATCH_AMBIGUOUS = "event_match_ambiguous"
    CONTENT_INTEGRITY = "content_integrity"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReviewResolution(StrEnum):
    RETRY_RETRIEVAL = "retry_retrieval"
    RETRY_EXTRACTION = "retry_extraction"
    ASSIGN_DISEASE = "assign_disease"
    RETRY_GEOCODING = "retry_geocoding"
    LINK_EVENT = "link_event"
    CREATE_EVENT = "create_event"
    DISMISS = "dismiss"
    RECOVERED_AUTOMATICALLY = "recovered_automatically"


def vocabulary(enum_class: type[StrEnum], name: str) -> Enum:
    """Store a controlled vocabulary as its lowercase values, not member names."""
    return Enum(
        enum_class,
        native_enum=False,
        create_constraint=True,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )
