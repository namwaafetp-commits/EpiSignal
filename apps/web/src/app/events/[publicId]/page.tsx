import {
  EventBrief,
  RelatedReporting,
  SourceList,
} from "@/components/event-content";
import {
  formatVerificationStatus,
  getEventDetail,
  relativeTimeLabel,
} from "@/lib/api-events";
import { getDashboardEvents } from "@/lib/api-dashboard";
import { relatedEvents } from "@/lib/related-events";
import { countryName } from "@/lib/country";
import { notFound } from "next/navigation";

export default async function EventPage({
  params,
}: {
  params: Promise<{ publicId: string }>;
}) {
  const { publicId } = await params;
  const [detail, feed] = await Promise.all([
    getEventDetail(publicId),
    getDashboardEvents(),
  ]);
  if (!detail) notFound();

  const location = locationLabel(
    detail.admin1 ?? detail.admin2,
    detail.country_code,
  );
  const headline = detail.headline || detail.public_id;
  const sourceCount = detail.sources.length || detail.article_count;
  const related = relatedEvents(
    detail,
    feed.status === "ready" ? feed.data.items : [],
  );

  return (
    <main className="event-content">
      <header className="event-content__hero">
        <p className="event-content__kicker">
          {detail.disease_group_label || detail.disease || "Disease unresolved"}
          {" · "}
          {hostLabel(detail.host_sector)}
        </p>
        <p className="event-content__place">{location}</p>
        <h1>{headline}</h1>
        <p className="event-content__facts">
          Updated {relativeTimeLabel(detail.latest_report_at)} · {sourceCount}{" "}
          source
          {sourceCount === 1 ? "" : "s"} ·{" "}
          {formatVerificationStatus(detail.verification_status)}
        </p>
      </header>

      <div className="event-content__body">
        <EventBrief event={detail} />
        <SourceList sources={detail.sources} />
        <RelatedReporting related={related} />
      </div>
    </main>
  );
}

function hostLabel(host: string | undefined) {
  if (host === "both") return "Human / animal";
  return host || "Host unresolved";
}

function locationLabel(place: string | null, countryCode: string | null) {
  const country = countryName(countryCode);
  if (place) return `${place}, ${country}`;
  return countryCode ? country : "Location unresolved";
}
