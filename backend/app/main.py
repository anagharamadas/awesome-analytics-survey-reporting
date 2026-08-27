"""
FastAPI app. The wiring, CORS and the health check are done for you.

Add your endpoints here or in a router you import - your call.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_session

app = FastAPI(title="Survey Reporting Slice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health(db: Session = Depends(get_session)):
    """Proves the app is up and can reach Postgres."""
    db.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/api/surveys")
def list_surveys(db: Session = Depends(get_session)):
    """TODO: return the surveys. The front end already calls this."""
    return []


@app.get("/api/surveys/{survey_id}/summary")
def survey_summary(survey_id: int, db: Session = Depends(get_session)):
    """TODO: the weekly summary. See section A3 of the brief."""
    return {"survey_id": survey_id, "weeks": []}
