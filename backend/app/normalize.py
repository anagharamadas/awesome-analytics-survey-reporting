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

--------------------------------------------------------------------------
Implementation notes (mine)
--------------------------------------------------------------------------
The empty-marker set below was derived by reading data/responses.csv, not
guessed. `scripts/profile_data.py` reproduces the evidence. Every marker
appears verbatim in the file:

    ""      respondent_email/completed_at/rating/channel/free_text
    "N/A"   completed_at (900013), rating (5351 rows)
    "n/a"   free_text (900013)
    "NULL"  completed_at-adjacent: rating (900012), free_text (900012)
    "null"  completed_at (900014)
    "-"     rating (900013)
    "none"  free_text (900014)

They are matched case-insensitively after stripping, which is why "N/A" and
"n/a" are one entry, not two.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["parse_client_datetime", "normalise_email", "parse_duration_seconds"]


# The client's export is Asia/Kolkata local time with no offset written down.
# Kolkata has no DST, so no timestamp in this file is ambiguous or non-existent
# -- but nothing below relies on that, because Dubai is next and the same code
# has to keep working when a second zone shows up.
CLIENT_TZ = ZoneInfo("Asia/Kolkata")

# DD/MM/YYYY HH:MM:SS, day first. strptime validates the calendar for us, so
# 29/02/2023 (2023 is not a leap year) raises rather than silently sliding to
# the 1st of March.
_CLIENT_DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S"

# See the module docstring: every one of these is present in responses.csv.
_EMPTY_MARKERS = frozenset({"", "n/a", "null", "-", "none"})

# Deliberately conservative. It is not RFC 5322 -- a full RFC parser accepts
# quoted local parts and comments that no client system in this export emits,
# and accepting them would only widen the surface for silent bad data. This
# rejects `not-an-email` and accepts `0091.pooja@example.com`, which are the
# two shapes that actually occur.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,}$"
)


def blank_to_none(raw: object) -> str | None:
    """Strip, and collapse every 'there is no value here' spelling to None.

    Shared by all three functions so the empty-marker set is defined exactly
    once. Returns the stripped string when there *is* a value.

    Public, but deliberately not in `__all__`. `__all__` is the compatibility
    promise -- the three graded signatures, unchanged. This is exported purely
    so `app.ingest` can apply the same marker vocabulary to the columns that
    have no dedicated parser (`channel`, `free_text`, `respondent_name`).
    The alternative is a second copy of the marker set in the ingest, which is
    precisely the class of bug this module exists to prevent.
    """
    if raw is None:
        return None
    text = raw if isinstance(raw, str) else str(raw)
    # NFC first: the export carries non-ASCII (emoji, Devanagari, umlauts) from
    # three systems, and the same character can arrive pre-composed or
    # decomposed. Normalising before stripping keeps comparisons stable.
    text = unicodedata.normalize("NFC", text).strip()
    if text.casefold() in _EMPTY_MARKERS:
        return None
    return text


def parse_client_datetime(raw: str | None) -> datetime | None:
    """Parse one timestamp exactly as the client's export writes them.

    Returns a timezone-aware `datetime`, or `None` if there is no value.
    Raises `ValueError` if a value is present but is not a real timestamp.

    The brief tells you the format the client writes and which local time it
    is in. Do not guess a different one.
    """
    text = blank_to_none(raw)
    if text is None:
        return None

    # strptime already raises ValueError with a usable message, and it is the
    # right exception, so it is left to propagate rather than re-wrapped.
    naive = datetime.strptime(text, _CLIENT_DATETIME_FORMAT)

    # Attach, do not convert. The caller gets the wall-clock instant the client
    # wrote, correctly labelled. Converting to UTC is the storage layer's job.
    return naive.replace(tzinfo=CLIENT_TZ)


def normalise_email(raw: str | None) -> str | None:
    """Return a canonical form of an email address.

    The canonical form is what you would compare two rows on to decide whether
    they came from the same person. Returns `None` if there is no value.
    Raises `ValueError` if a value is present but is not usable as an email
    address at all.

    You decide what "canonical" means here. Say why in your README.
    """
    text = blank_to_none(raw)
    if text is None:
        return None

    # Strip surrounding whitespace (done in blank_to_none) then lower-case the
    # whole address. RFC 5321 makes the local part case-sensitive in theory;
    # in practice no mail system treats Asha.Rao and asha.rao as two people,
    # and the brief's own worked example requires them to compare equal.
    #
    # What is deliberately NOT done: stripping dots, and stripping +tags.
    # Both are Gmail-specific delivery quirks, not general email semantics, and
    # applying them here would merge distinct people. The export contains a
    # respondent whose free-text reads "It is O'Brien, not Obrien" -- punctuation
    # inside an identifier is meaningful in this dataset, so it is preserved.
    canonical = text.lower()

    if not _EMAIL_RE.match(canonical):
        raise ValueError(f"not a usable email address: {text!r}")

    return canonical


def parse_duration_seconds(raw: str | None) -> int | None:
    """Return a duration as a whole number of seconds.

    Returns `None` if there is no value. Raises `ValueError` if a value is
    present but is not a number.

    Whether a particular number is a *plausible* duration is a business rule
    and belongs in your ingest, not in here.
    """
    text = blank_to_none(raw)
    if text is None:
        return None

    # The export writes at least one duration with a thousands separator
    # ("2,460"). That is a number wearing formatting, not a data error, so the
    # separator is removed rather than treated as garbage.
    text = text.replace(",", "")

    # float() then round(), rather than int(), so a value written as "479.0"
    # parses instead of blowing up. Note the docstring above: -2400 is a
    # perfectly good number and is returned as -2400. Rejecting it as an
    # impossible duration is the ingest's call, not this function's.
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a number: {text!r}") from exc

    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"not a finite number: {text!r}")

    return int(round(value))
