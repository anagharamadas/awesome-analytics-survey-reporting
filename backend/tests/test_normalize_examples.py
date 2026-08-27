"""
Two examples per function, so you can see the shape of the contract.

These are NOT the tests we grade with. Ours are longer and are built from the
values that actually appear in `data/responses.csv`. Passing these three tests
means very little; read the data.

Run with:  docker compose exec backend pytest
"""

import pytest

from app.normalize import (
    normalise_email,
    parse_client_datetime,
    parse_duration_seconds,
)


def test_datetime_happy_path():
    got = parse_client_datetime("17/03/2026 09:15:00")
    assert got is not None
    assert (got.year, got.month, got.day) == (2026, 3, 17)
    assert got.tzinfo is not None, "we compare instants, so it has to be aware"


def test_datetime_empty_is_none():
    assert parse_client_datetime("") is None


def test_email_happy_path():
    assert normalise_email("Asha.Rao@example.com") == normalise_email(
        "asha.rao@example.com"
    )


def test_email_garbage_raises():
    with pytest.raises(ValueError):
        normalise_email("not-an-email")


def test_duration_happy_path():
    assert parse_duration_seconds("479") == 479


def test_duration_empty_is_none():
    assert parse_duration_seconds("") is None
