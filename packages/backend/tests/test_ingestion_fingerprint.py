from episignal_backend.ingestion.fingerprint import content_hash, verify_content_hash


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


def test_content_hash_ignores_unicode_normalization_form() -> None:
    # Built from explicit code points so the source file's own normalization
    # cannot silently collapse the two forms before the test even runs.
    precomposed = "C" + "ô" + "te d'Ivoire"  # o-circumflex, one code point
    decomposed = "C" + "o" + "̂" + "te d'Ivoire"  # "o" + combining circumflex
    assert precomposed != decomposed
    assert content_hash("Cholera", precomposed) == content_hash("Cholera", decomposed)


def test_verify_content_hash_matches_valid_inputs() -> None:
    title = "Measles outbreak in Pennsylvania"
    body = "Two cases confirmed by health department."
    stored = content_hash(title, body)
    assert verify_content_hash(title, body, stored) is True


def test_verify_content_hash_rejects_swapped_or_mismatched_body() -> None:
    title = "Pennsylvania reports measles deaths"
    stored = content_hash(title, "Authentic Pennsylvania measles body")
    corrupted_body = "Health officials in Luanda, Angola reported 50 confirmed cases of cholera."
    assert verify_content_hash(title, corrupted_body, stored) is False


def test_verify_content_hash_rejects_swapped_or_mismatched_title() -> None:
    body = "Authentic Luanda cholera report body"
    stored = content_hash("Cholera in Luanda", body)
    corrupted_title = "Pennsylvania reports measles deaths"
    assert verify_content_hash(corrupted_title, body, stored) is False


def test_verify_content_hash_rejects_missing_or_invalid_hash() -> None:
    title = "Cholera in Luanda"
    body = "50 cases"
    assert verify_content_hash(title, body, "") is False
    assert verify_content_hash(title, body, None) is False  # type: ignore[arg-type]


def test_verify_content_hash_handles_none_body_gracefully() -> None:
    title = "Empty body signal"
    stored = content_hash(title, "")
    assert verify_content_hash(title, None, stored) is True
