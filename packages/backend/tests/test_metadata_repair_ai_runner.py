from episignal_backend.metadata_repair_ai_runner import parse_arguments


def test_ai_repair_defaults_to_a_dry_run_with_no_unbounded_request_budget() -> None:
    arguments = parse_arguments([])

    assert arguments.apply is False
    assert arguments.limit is None
    assert arguments.max_ai_requests is None


def test_ai_repair_requires_explicit_apply_and_supports_both_limits() -> None:
    arguments = parse_arguments(["--apply", "--limit", "20", "--max-ai-requests", "3"])

    assert arguments.apply is True
    assert arguments.limit == 20
    assert arguments.max_ai_requests == 3
