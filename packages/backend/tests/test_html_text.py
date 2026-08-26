from episignal_backend.ingestion.html_text import strip_html, strip_html_within

NESTED = (
    '<div class="wysiwyg-content">'
    "<p>Outer opening.</p>"
    '<div class="inner"><p>Inner paragraph.</p></div>'
    "<p>Outer closing.</p>"
    "</div>"
    "<footer><p>Footer must not appear.</p></footer>"
)


def test_strip_html_leaves_double_escaped_markup_alone() -> None:
    # ECDC feed descriptions arrive double-escaped. Decoding a second time would
    # turn the literal text `&lt;p&gt;` into a tag and drop it from the evidence.
    assert strip_html("<p>&amp;lt;p&amp;gt; stays text</p>") == "&lt;p&gt; stays text"


def test_strip_html_separates_adjacent_table_cells() -> None:
    assert strip_html("<td>45</td><td>12</td>") == "45 12"


def test_strip_html_within_stops_at_the_matching_close_tag() -> None:
    # A nested div of the same name must not end the region early, which would
    # truncate the body mid-article.
    text = strip_html_within(NESTED, tag="div", attribute="class", token="wysiwyg-content")
    assert text == "Outer opening. Inner paragraph. Outer closing."


def test_strip_html_within_excludes_everything_outside_the_region() -> None:
    text = strip_html_within(NESTED, tag="div", attribute="class", token="wysiwyg-content")
    assert "Footer" not in text


def test_strip_html_within_joins_several_regions_with_a_blank_line() -> None:
    html = (
        '<div class="wysiwyg-content"><p>First.</p></div>'
        '<div class="wysiwyg-content"><p>Second.</p></div>'
    )
    text = strip_html_within(html, tag="div", attribute="class", token="wysiwyg-content")
    assert text == "First.\n\nSecond."


def test_strip_html_within_matches_a_class_token_not_a_substring() -> None:
    # Drupal composes class attributes from independent lists, so the token must
    # match a whole class and must not match a longer class that contains it.
    html = '<div class="mb-4 wysiwyg-content clearfix"><p>Kept.</p></div>'
    assert strip_html_within(html, tag="div", attribute="class", token="wysiwyg-content") == "Kept."
    other = '<div class="wysiwyg-content-teaser"><p>Dropped.</p></div>'
    assert strip_html_within(other, tag="div", attribute="class", token="wysiwyg-content") == ""


def test_strip_html_within_returns_empty_when_no_region_matches() -> None:
    assert strip_html_within("<p>Nothing.</p>", tag="div", attribute="class", token="x") == ""


def test_strip_html_within_skips_script_and_style_content() -> None:
    html = (
        '<div class="wysiwyg-content"><p>Kept.</p>'
        "<script>var dropped = 1;</script><style>.dropped{}</style></div>"
    )
    text = strip_html_within(html, tag="div", attribute="class", token="wysiwyg-content")
    assert text == "Kept."
