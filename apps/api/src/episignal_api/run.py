"""Local development server for `pnpm dev`."""

import uvicorn

from episignal_api.factory import load_runtime_settings


def main() -> None:
    settings = load_runtime_settings()
    uvicorn.run(
        "episignal_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=settings.env == "development",
    )


if __name__ == "__main__":
    main()
