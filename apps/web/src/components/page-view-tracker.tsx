"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { trackPageView } from "../lib/analytics";

export function PageViewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    const send = () => trackPageView(pathname ?? "");
    send();
    window.addEventListener("episignal-umami-ready", send);
    return () => window.removeEventListener("episignal-umami-ready", send);
  }, [pathname]);

  return null;
}
