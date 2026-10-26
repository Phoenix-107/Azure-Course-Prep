"""
Development & Diagnostic Router for Azure AZ-900 Prep.
Exposes utility endpoints for time simulation and state resetting.
STRICTLY ISOLATED from production or guarded by administrative authentication.
"""

import os
import secrets
from fastapi import APIRouter, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from backend.db import get_db_connection
from backend import srs

# Optional security header for staging or admin-enabled environments
API_KEY_HEADER = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def verify_admin_secret(api_key: str = Security(API_KEY_HEADER)):
    """
    Dependency that enforces administrative authentication.
    Compares provided X-Admin-Key against ADMIN_API_KEY environment variable.
    """
    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin authentication misconfigured on server (ADMIN_API_KEY is not set).",
        )
    if not api_key or not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing administrative API key.",
        )
    return True


class AdvanceDaysRequest(BaseModel):
    days: int


class ResetCardsRequest(BaseModel):
    user_id: str


router = APIRouter(prefix="/api/dev", tags=["Development Utilities"])


@router.post("/advance-days")
def dev_advance_days(payload: AdvanceDaysRequest):
    """Dev-only: Shift the simulated date offset to test due dates."""
    new_today = srs.advance_days(payload.days)
    return {
        "status": "success",
        "days_advanced": payload.days,
        "offset": srs.DEV_DAY_OFFSET,
        "today": new_today,
    }


@router.post("/reset-cards")
def dev_reset_cards(payload: ResetCardsRequest):
    """Dev-only: Reset all card_state and review_log records for a user."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM card_state WHERE user_id = ?", (payload.user_id,))
        conn.execute("DELETE FROM review_log WHERE user_id = ?", (payload.user_id,))
        conn.commit()
        return {"status": "success", "user_id": payload.user_id, "message": "Cards progress reset."}
    finally:
        conn.close()
