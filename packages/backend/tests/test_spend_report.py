from datetime import UTC, datetime, timedelta
from decimal import Decimal

from episignal_backend.ai.spend import trailing_spend


class FakeRow:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter(self._values)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def one(self):
        return self._rows[0]

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, total, rows):
        self._queue = [FakeResult([total]), FakeResult(rows)]

    def execute(self, statement):
        return self._queue.pop(0)


def test_trailing_spend_totals_and_breaks_down() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    session = FakeSession(
        (23, 27, Decimal("0.0390")),
        [
            ("google/gemini-3.5-flash-lite", "extraction", "rejected", 9, 11, Decimal("0.022782")),
            ("google/gemini-3.5-flash-lite", "extraction", "accepted", 4, 6, Decimal("0.009063")),
        ],
    )

    summary = trailing_spend(session, window_days=30, now=now)

    assert summary.requests == 23
    assert summary.signals == 27
    assert summary.cost_usd == Decimal("0.039000")
    assert summary.since == now - timedelta(days=30)
    assert summary.breakdown[0].model_id == "google/gemini-3.5-flash-lite"
    assert summary.breakdown[0].purpose == "extraction"
    assert summary.breakdown[0].outcome == "rejected"
    assert summary.breakdown[0].requests == 9
    assert summary.breakdown[0].signals == 11


def test_an_empty_ledger_reports_zero_rather_than_none() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    session = FakeSession((0, 0, 0), [])

    summary = trailing_spend(session, window_days=30, now=now)

    assert summary.requests == 0
    assert summary.signals == 0
    assert summary.cost_usd == Decimal("0")
    assert summary.breakdown == ()
