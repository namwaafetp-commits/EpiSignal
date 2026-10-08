import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UmamiScript } from "./umami-script";

vi.mock("next/script", () => ({
  default: (props: Record<string, unknown>) => <script {...props} />,
}));

describe("UmamiScript", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    document.body.innerHTML = "";
  });

  it("renders the configured tracker before hydration", () => {
    vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
    vi.stubEnv(
      "NEXT_PUBLIC_UMAMI_SCRIPT_URL",
      "https://stats.example/script.js",
    );

    render(<UmamiScript />);

    expect(document.querySelector("#episignal-umami")).toMatchObject({
      id: "episignal-umami",
      src: "https://stats.example/script.js",
      dataset: {
        websiteId: "website-id",
        autoTrack: "true",
        autoPageview: "false",
        excludeSearch: "true",
      },
    });
  });
});
