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
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


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


def vocabulary(enum_class: type[StrEnum], name: str) -> Enum:
    """Store a controlled vocabulary as its lowercase values, not member names."""
    return Enum(
        enum_class,
        native_enum=False,
        create_constraint=True,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )
