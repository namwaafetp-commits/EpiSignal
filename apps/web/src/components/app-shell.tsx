"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { trackEvent } from "../lib/analytics";
import { ThemeToggle } from "./theme-toggle";

export function TopNavigation() {
  const pathname = usePathname();
  const params = useSearchParams();
  const query = params.toString();
  const suffix = query ? `?${query}` : "";
  const onBriefing =
    pathname === "/briefing" || Boolean(pathname?.startsWith("/events"));

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="top-navigation">
        <Link
          className="wordmark"
          href={`/${suffix}`}
          aria-label="EpiSignal home"
        >
          <Image
            className="wordmark-mark wordmark-mark--light"
            src="/episignal-mark.png"
            alt=""
            width={110}
            height={96}
            priority
          />
          <Image
            className="wordmark-mark wordmark-mark--dark"
            src="/episignal-mark-dark.png"
            alt=""
            width={110}
            height={96}
            priority
          />
          EpiSignal<span className="wordmark-dot">.</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link
            href={`/${suffix}`}
            aria-current={pathname === "/" ? "page" : undefined}
            onClick={() =>
              trackEvent({ name: "view_switch", properties: { view: "map" } })
            }
          >
            Map
          </Link>
          <Link
            href={`/briefing${suffix}`}
            aria-current={onBriefing ? "page" : undefined}
            onClick={() =>
              trackEvent({
                name: "view_switch",
                properties: { view: "briefing" },
              })
            }
          >
            Briefing
          </Link>
        </nav>
        <div className="navigation-tools">
          <Link
            className="nav-search"
            href={`/briefing${suffix}#event-search`}
            aria-label="Search events"
          >
            <Search size={18} aria-hidden="true" />
            <span>Search</span>
          </Link>
          <ThemeToggle />
        </div>
      </header>
    </>
  );
}
