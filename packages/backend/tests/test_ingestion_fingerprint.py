from episignal_backend.ingestion.fingerprint import content_hash


def test_content_hash_fits_the_signal_column() -> None:
    assert len(content_hash("Ebola - DRC", "4665 confirmed cases.")) == 64


def test_content_hash_ignores_whitespace_only_differences() -> None:
    assert content_hash("Ebola - DRC", "4665  confirmed\n cases.") == content_hash(
        "Ebola - DRC", "4665 confirmed cases."
    )


def test_content_hash_changes_when_a_reported_number_changes() -> None:
    assert content_hash("Ebola - DRC", "4665 confirmed cases.") != content_hash(
        "Ebola - DRC", "4670 confirmed cases."
    )


def test_content_hash_changes_when_the_title_changes() -> None:
    assert content_hash("Ebola - DRC", "same body") != content_hash("Ebola - Uganda", "same body")


def test_content_hash_does_not_confuse_title_and_body_boundaries() -> None:
    assert content_hash("a", "b") != content_hash("a b", "")
