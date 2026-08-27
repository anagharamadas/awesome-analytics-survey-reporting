"""
My tests for app.normalize.

Deliberately built from values that actually appear in data/responses.csv,
because the brief says the graded suite is built the same way. The provided
test_normalize_examples.py shows the shape only; this covers the behaviour the
data actually demands.
"""

from datetime import datetime

import pytest

from app.normalize import (
    normalise_email,
    parse_client_datetime,
    parse_duration_seconds,
)

# Every one of these appears verbatim in data/responses.csv.
EMPTY_MARKERS = ["", "   ", "N/A", "n/a", "NULL", "null", "-", "none"]


@pytest.mark.parametrize("marker", EMPTY_MARKERS)
@pytest.mark.parametrize(
    "fn", [parse_client_datetime, normalise_email, parse_duration_seconds]
)
def test_every_empty_marker_is_none_in_every_function(fn, marker):
    """The brief says treat the whole set as empty in all three functions."""
    assert fn(marker) is None
    assert fn(None) is None


class TestParseClientDatetime:
    def test_is_day_first_not_month_first(self):
        """03/04/2026 is 3 April, not 4 March. Getting this backwards would
        silently move ~2/3 of the dataset into the wrong reporting week."""
        got = parse_client_datetime("03/04/2026 08:15:00")
        assert (got.year, got.month, got.day) == (2026, 4, 3)

    def test_is_timezone_aware_in_client_local_time(self):
        got = parse_client_datetime("17/03/2026 09:15:00")
        assert got.tzinfo is not None
        assert got.utcoffset().total_seconds() == 5.5 * 3600  # IST, +05:30
        assert (got.hour, got.minute, got.second) == (9, 15, 0)

    def test_compares_as_the_correct_instant(self):
        """09:15 IST is 03:45 UTC. The whole point of returning aware
        datetimes is that this comparison holds."""
        got = parse_client_datetime("17/03/2026 09:15:00")
        assert got == datetime.fromisoformat("2026-03-17T03:45:00+00:00")

    def test_impossible_calendar_date_raises(self):
        """29/02/2023 - 2023 is not a leap year. Row 900006."""
        with pytest.raises(ValueError):
            parse_client_datetime("29/02/2023 10:00:00")

    def test_valid_leap_day_still_parses(self):
        assert parse_client_datetime("29/02/2024 10:00:00").day == 29

    @pytest.mark.parametrize(
        "bad",
        [
            "32/01/2026 00:00:00",  # no 32nd
            "01/13/2026 00:00:00",  # month-first input, 13 is not a month
            "2026-03-17 09:15:00",  # ISO, not the client's format
            "17/03/2026",  # date only, no time
            "17/03/2026 25:00:00",  # no 25th hour
        ],
    )
    def test_present_but_unparseable_raises(self, bad):
        with pytest.raises(ValueError):
            parse_client_datetime(bad)


class TestNormaliseEmail:
    def test_case_and_surrounding_whitespace_collapse(self):
        """Rows 900001 and 900002 are the same person from two client systems."""
        assert normalise_email("Priya.Sharma22@example.com") == normalise_email(
            "priya.sharma22@example.com "
        )

    def test_leading_digits_in_local_part_are_kept(self):
        """Row 900017. Valid address; must not be mangled as a number."""
        assert normalise_email("0091.pooja@example.com") == "0091.pooja@example.com"

    def test_dots_are_significant_and_not_stripped(self):
        """Gmail's dot-folding is a delivery quirk of one provider, not email
        semantics. sean.obrien and seanobrien are two different people, and
        row 900003's free text says so out loud."""
        assert normalise_email("sean.obrien@example.com") != normalise_email(
            "seanobrien@example.com"
        )

    def test_plus_tags_are_significant_and_not_stripped(self):
        assert normalise_email("a+one@example.com") != normalise_email(
            "a@example.com"
        )

    def test_is_idempotent(self):
        once = normalise_email("Priya.Sharma22@example.com")
        assert normalise_email(once) == once

    @pytest.mark.parametrize(
        "bad", ["not-an-email", "@example.com", "a@", "a b@example.com", "a@b"]
    )
    def test_unusable_address_raises(self, bad):
        with pytest.raises(ValueError):
            normalise_email(bad)


class TestParseDurationSeconds:
    def test_plain_integer(self):
        assert parse_duration_seconds("479") == 479

    def test_thousands_separator_is_formatting_not_an_error(self):
        """Row 900009 writes 2,460. That is a number wearing a comma."""
        assert parse_duration_seconds("2,460") == 2460

    def test_negative_is_returned_not_rejected(self):
        """Row 900008. The docstring is explicit that plausibility is a
        business rule for the ingest, not for this function."""
        assert parse_duration_seconds("-2400") == -2400

    def test_zero_is_a_value_not_an_absence(self):
        """Row 900014. 0 is falsy in Python - a naive `if not value` would
        turn this into None and lose a real measurement."""
        assert parse_duration_seconds("0") == 0

    def test_returns_a_whole_number(self):
        got = parse_duration_seconds("479.6")
        assert isinstance(got, int) and got == 480

    @pytest.mark.parametrize("bad", ["abc", "12 minutes", "1,2,3.4.5", "--5"])
    def test_present_but_not_a_number_raises(self, bad):
        with pytest.raises(ValueError):
            parse_duration_seconds(bad)
