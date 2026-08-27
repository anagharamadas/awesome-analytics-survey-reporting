"""
Pure functions that turn one raw CSV field into one clean Python value.

READ THIS, IT IS GRADED SEPARATELY.

Your ingest must import and use these three functions rather than doing the
same work inline. After you submit, we drop our own pytest file into
`backend/tests/` and run it against this module on your repo, unchanged. It
imports only these three names. Keep the signatures exactly as they are.

Keep them pure: no database, no I/O, no logging, no global state. Add private
helpers in this file if you want to.

Two shared rules for all three functions:

* The client's export has more than one way of writing "there is no value
  here". Returning `None` for all of them is correct. The same handful of empty
  markers turns up across the columns of `data/responses.csv`, and we only test
  the ones that actually occur in that file, so reading the file is a
  legitimate and expected way to find out what they are. Treat the whole set as
  empty in all three functions.
* A value that is *present* but not parseable is a data error, not an empty
  value. Raise `ValueError` for those, so your ingest can put them in
  `rejects.csv` with a reason instead of silently turning them into `None`.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["parse_client_datetime", "normalise_email", "parse_duration_seconds"]


def parse_client_datetime(raw: str | None) -> datetime | None:
    """Parse one timestamp exactly as the client's export writes them.

    Returns a timezone-aware `datetime`, or `None` if there is no value.
    Raises `ValueError` if a value is present but is not a real timestamp.

    The brief tells you the format the client writes and which local time it
    is in. Do not guess a different one.
    """
    raise NotImplementedError


def normalise_email(raw: str | None) -> str | None:
    """Return a canonical form of an email address.

    The canonical form is what you would compare two rows on to decide whether
    they came from the same person. Returns `None` if there is no value.
    Raises `ValueError` if a value is present but is not usable as an email
    address at all.

    You decide what "canonical" means here. Say why in your README.
    """
    raise NotImplementedError


def parse_duration_seconds(raw: str | None) -> int | None:
    """Return a duration as a whole number of seconds.

    Returns `None` if there is no value. Raises `ValueError` if a value is
    present but is not a number.

    Whether a particular number is a *plausible* duration is a business rule
    and belongs in your ingest, not in here.
    """
    raise NotImplementedError
