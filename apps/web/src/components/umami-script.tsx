"use client";

import Script from "next/script";
import { getUmamiScriptProps } from "../lib/umami-config";

export function UmamiScript() {
  const props = getUmamiScriptProps();
  if (!props) return null;

  return (
    <Script
      {...props}
      onLoad={() => window.dispatchEvent(new Event("episignal-umami-ready"))}
    />
  );
}
