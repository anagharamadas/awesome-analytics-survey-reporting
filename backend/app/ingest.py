"""
Ingest entry point.

Run it with:

    docker compose exec backend python -m app.ingest

The CSVs are mounted read-only at /data. Write `rejects.csv` wherever you like
and commit it to the repo.

Everything below the argument parsing is yours.
"""

from __future__ import annotations

import os
import sys

DATA_DIR = os.getenv("DATA_DIR", "/data")
SURVEYS_CSV = os.path.join(DATA_DIR, "surveys.csv")
RESPONSES_CSV = os.path.join(DATA_DIR, "responses.csv")


def run() -> int:
    """Load both CSVs. Return a process exit code."""
    print(f"surveys:   {SURVEYS_CSV}")
    print(f"responses: {RESPONSES_CSV}")
    raise NotImplementedError("TODO: this is yours")


if __name__ == "__main__":
    sys.exit(run())
