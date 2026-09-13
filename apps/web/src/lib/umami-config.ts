export function getUmamiScriptProps() {
  const websiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
  const scriptUrl = process.env.NEXT_PUBLIC_UMAMI_SCRIPT_URL;

  if (!websiteId || !scriptUrl) return null;

  return {
    id: "episignal-umami",
    src: scriptUrl,
    strategy: "afterInteractive" as const,
    "data-website-id": websiteId,
    "data-auto-track": "true",
    "data-auto-pageview": "false",
    "data-exclude-search": "true",
  };
}
