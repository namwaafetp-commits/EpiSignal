"""Small, privacy-preserving client for the Umami event-data API."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


class UmamiApiError(RuntimeError):
    """An Umami request failed or returned an unusable response."""


@dataclass(frozen=True)
class UmamiEventRecord:
    """The short-lived subset of an Umami event needed by the sync job."""

    event_name: str
    session_id: str
    properties: Mapping[str, str]


class UmamiClient:
    """Read event aggregates from a self-hosted Umami instance."""

    def __init__(
        self,
        *,
        base_url: str,
        website_id: str,
        api_token: str,
        timeout: float = 15.0,
        page_size: int = 1_000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        api_base = base_url.rstrip("/")
        if not api_base.endswith("/api"):
            api_base += "/api"
        self._client = httpx.Client(
            base_url=api_base,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_token}",
            },
            timeout=timeout,
            transport=transport,
        )
        self._website_id = website_id
        self._page_size = page_size

    def __enter__(self) -> "UmamiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_event_records(
        self,
        event_name: str,
        start: datetime,
        end: datetime,
    ) -> list[UmamiEventRecord]:
        records: list[UmamiEventRecord] = []
        page = 1
        while True:
            try:
                response = self._client.get(
                    f"/websites/{self._website_id}/event-data-pivot",
                    params={
                        "startAt": int(start.timestamp() * 1000),
                        "endAt": int(end.timestamp() * 1000),
                        "eventName": event_name,
                        "page": page,
                        "pageSize": self._page_size,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except httpx.TimeoutException as error:
                raise UmamiApiError("Umami request timed out") from error
            except httpx.HTTPStatusError as error:
                raise UmamiApiError(
                    f"Umami request failed with HTTP {error.response.status_code}"
                ) from error
            except httpx.HTTPError as error:
                raise UmamiApiError("Umami request failed") from error
            except ValueError as error:
                raise UmamiApiError("Umami response was not valid JSON") from error

            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise UmamiApiError("Umami response shape was invalid")
            count = payload.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise UmamiApiError("Umami response shape was invalid")

            for row in payload["data"]:
                record = self._parse_record(row, event_name)
                if record is not None:
                    records.append(record)

            data_length = len(payload["data"])
            if data_length == 0 or page * self._page_size >= count:
                return records
            page += 1

    @staticmethod
    def _parse_record(row: Any, requested_event_name: str) -> UmamiEventRecord | None:
        if not isinstance(row, dict):
            return None
        session_id = row.get("sessionId")
        property_keys = row.get("propertyKeys")
        property_values = row.get("propertyValues")
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or not isinstance(property_keys, list)
            or not isinstance(property_values, list)
            or len(property_keys) != len(property_values)
        ):
            return None
        properties: dict[str, str] = {}
        for key, value in zip(property_keys, property_values, strict=True):
            if (
                isinstance(key, str)
                and key in {"event_id", "surface", "position_bucket"}
                and isinstance(value, str)
            ):
                properties[key] = value
        event_name = row.get("eventName", requested_event_name)
        if not isinstance(event_name, str) or not event_name:
            event_name = requested_event_name
        return UmamiEventRecord(
            event_name=event_name,
            session_id=session_id,
            properties=properties,
        )
