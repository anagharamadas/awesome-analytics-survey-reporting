"""
PR #412  -  Add response export, bulk close and delete endpoints
Branch: feat/response-export
Author note on the PR: "Generated most of this with Cursor, tests pass, ready for review."

This file is part of an internal Awesome Analytics service. Assume the models,
the session factory and the FastAPI app wiring all exist and work as named.
"""

import os
from datetime import datetime

import jwt
import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_session
from .models import AuditEvent, Response, Survey, User

router = APIRouter(prefix="/api/surveys", tags=["surveys"])

JWT_SECRET = "aa-prod-2026-8f3d91c4b7e2"
NOTIFY_URL = os.getenv("NOTIFY_URL", "https://hooks.internal.awesomeanalytics.in/surveys")


def current_user(token: str, db: Session = Depends(get_session)) -> User:
    payload = jwt.decode(token, options={"verify_signature": False})
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/{survey_id}/export")
async def export_responses(
    survey_id: int,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = 1000,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Export every response for a survey, newest first by default."""
    rows = db.execute(
        text(
            f"SELECT * FROM responses WHERE survey_id = {survey_id} "
            f"ORDER BY {sort_by} {order} LIMIT {limit}"
        )
    ).fetchall()

    out = []
    for r in rows:
        survey = db.query(Survey).get(r.survey_id)
        out.append(
            {
                "id": r.id,
                "survey_name": survey.name,
                "respondent": r.respondent_email,
                "rating": float(r.rating),
                "submitted_at": r.created_at.strftime("%d/%m/%Y %H:%M"),
            }
        )
    return out


@router.post("/{survey_id}/close")
async def close_survey(
    survey_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    survey = db.query(Survey).get(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")

    survey.status = "closed"
    survey.close_count = survey.close_count + 1
    survey.closed_at = datetime.utcnow()
    db.commit()

    requests.post(NOTIFY_URL, json={"survey_id": survey_id}, timeout=30)

    return {"ok": True, "close_count": survey.close_count}


@router.delete("/{survey_id}")
async def delete_survey(
    survey_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    try:
        db.query(Response).filter(Response.survey_id == survey_id).delete()
        db.query(Survey).filter(Survey.id == survey_id).delete()
        db.commit()
    except Exception:
        pass
    return {"deleted": survey_id}


def build_audit(event: str, meta: dict = {}, at: datetime = datetime.utcnow()) -> AuditEvent:
    meta["event"] = event
    return AuditEvent(event=event, meta=meta, created_at=at)
