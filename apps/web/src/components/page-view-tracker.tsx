"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { trackPageView } from "../lib/analytics";

export function PageViewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    let sent = false;
    const send = () => {
      if (sent || typeof window.umami?.track !== "function") return;
      sent = trackPageView(pathname ?? "");
    };

    send();
    if (!sent) {
      const script =
        document.querySelector<HTMLScriptElement>("#episignal-umami");
      script?.addEventListener("load", send, { once: true });
      return () => script?.removeEventListener("load", send);
    }
  }, [pathname]);

  return null;
}
