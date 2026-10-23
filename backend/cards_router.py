"""
Flashcards Coach API Router for Azure AZ-900 Prep.
Provides endpoints for due card queries, SM-2 review logging, analytics, and dev utilities.
"""

import datetime
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_db_connection
from backend import srs

router = APIRouter()


# --- Pydantic Models ---

class ReviewRequest(BaseModel):
    user_id: str
    card_id: int
    rating: int = Field(..., ge=0, le=3, description="0=Again, 1=Hard, 2=Good, 3=Easy")


class ReviewResponse(BaseModel):
    due_date: str
    interval: int
    ease: float


class AdvanceDaysRequest(BaseModel):
    days: int


class ResetCardsRequest(BaseModel):
    user_id: str


class ExamCreateRequest(BaseModel):
    user_id: str
    exam_date: datetime.date
    course: str = "AZ-900"
    target_score: int = Field(85, ge=0, le=100)
    daily_minutes: int = Field(45, ge=1, le=600)


class CardOut(BaseModel):
    id: int
    topic_id: str
    front: str
    back: str
    type: str
    hint: Optional[str] = None
    is_new: bool
    intervals: Dict[str, int]


class DueCardsResponse(BaseModel):
    cards: List[CardOut]
    due_count: int
    new_count: int
    estimated_minutes: int
    today: str


class TopicLapse(BaseModel):
    topic_id: str
    topic_name: str
    lapses: int


class CardsStatsResponse(BaseModel):
    user_id: str
    due_today: int
    reviewed_today: int
    accuracy_today: float
    streak: int
    total_cards: int
    mastered: int
    per_topic_lapses: List[TopicLapse]


# --- Helper Functions ---

def get_latest_exam_date(conn, user_id: str) -> Optional[str]:
    """Return user's latest exam date string if registered."""
    row = conn.execute(
        "SELECT exam_date FROM exams WHERE user_id = ? ORDER BY exam_date DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    return row["exam_date"] if row else None


# --- Endpoints ---

@router.get("/api/cards/due", response_model=DueCardsResponse)
def get_due_cards(
    user_id: str = Query(..., description="Scholar ID"),
    new_limit: int = Query(15, ge=0, le=100, description="Max new cards to serve"),
    topic: Optional[str] = Query(None, description="Optional topic filter ID")
):
    """
    Return due cards first (due_date <= today), then new cards (up to new_limit).
    Creates card_state records for new cards when they are served.
    """
    if not isinstance(new_limit, int):
        new_limit = 15
    if not isinstance(topic, str):
        topic = None

    today = srs.get_today()
    conn = get_db_connection()
    try:
        exam_date = get_latest_exam_date(conn, user_id)

        # 1. Fetch due cards (card_state already exists and due_date <= today)
        due_query = """
        SELECT c.id, c.topic_id, c.front, c.back, c.type, c.hint,
               cs.ease, cs.interval, cs.repetitions, cs.lapses, cs.due_date, cs.last_reviewed
        FROM cards c
        JOIN card_state cs ON c.id = cs.card_id AND cs.user_id = ?
        WHERE cs.due_date <= ?
        """
        params: List[Any] = [user_id, today]

        if topic and topic.strip() and topic.lower() != "all":
            due_query += " AND c.topic_id = ?"
            params.append(topic.strip())

        due_query += " ORDER BY cs.due_date ASC, c.id ASC"
        due_rows = conn.execute(due_query, params).fetchall()

        # 2. Fetch new cards (no card_state exists yet for this user)
        new_query = """
        SELECT c.id, c.topic_id, c.front, c.back, c.type, c.hint
        FROM cards c
        LEFT JOIN card_state cs ON c.id = cs.card_id AND cs.user_id = ?
        WHERE cs.card_id IS NULL
        """
        new_params: List[Any] = [user_id]

        if topic and topic.strip() and topic.lower() != "all":
            new_query += " AND c.topic_id = ?"
            new_params.append(topic.strip())

        new_query += " ORDER BY c.id ASC LIMIT ?"
        new_params.append(new_limit)

        new_rows = conn.execute(new_query, new_params).fetchall() if new_limit > 0 else []

        cards_out: List[CardOut] = []

        # Process due cards
        for r in due_rows:
            curr_state = {
                "ease": r["ease"],
                "interval": r["interval"],
                "repetitions": r["repetitions"],
                "lapses": r["lapses"]
            }
            cards_out.append(
                CardOut(
                    id=r["id"],
                    topic_id=r["topic_id"],
                    front=r["front"],
                    back=r["back"],
                    type=r["type"] or "basic",
                    hint=r["hint"],
                    is_new=False,
                    intervals=srs.preview_intervals(curr_state, exam_date=exam_date)
                )
            )

        # Process and initialize new cards
        for r in new_rows:
            # Create card_state row for new card when served
            conn.execute(
                """
                INSERT OR IGNORE INTO card_state
                    (card_id, user_id, ease, interval, repetitions, due_date, lapses)
                VALUES (?, ?, 2.5, 0, 0, ?, 0)
                """,
                (r["id"], user_id, today)
            )

            initial_state = {
                "ease": 2.5,
                "interval": 0,
                "repetitions": 0,
                "lapses": 0
            }
            cards_out.append(
                CardOut(
                    id=r["id"],
                    topic_id=r["topic_id"],
                    front=r["front"],
                    back=r["back"],
                    type=r["type"] or "basic",
                    hint=r["hint"],
                    is_new=True,
                    intervals=srs.preview_intervals(initial_state, exam_date=exam_date)
                )
            )

        conn.commit()

        due_count = len(due_rows)
        new_count = len(new_rows)
        total_count = due_count + new_count
        # ~25 seconds per card
        estimated_minutes = max(1, math.ceil(total_count * 25 / 60)) if total_count > 0 else 0

        return DueCardsResponse(
            cards=cards_out,
            due_count=due_count,
            new_count=new_count,
            estimated_minutes=estimated_minutes,
            today=today
        )
    finally:
        conn.close()


@router.post("/api/cards/review", response_model=ReviewResponse)
def review_card(payload: ReviewRequest):
    """
    Validate rating (0-3) and card existence, calculate next SM-2 interval and ease,
    save card_state, log review_log, and return next review schedule.
    """
    conn = get_db_connection()
    try:
        # Check card exists
        card = conn.execute("SELECT id FROM cards WHERE id = ?", (payload.card_id,)).fetchone()
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")

        # Load current state
        state_row = conn.execute(
            """
            SELECT ease, interval, repetitions, lapses, due_date, last_reviewed
            FROM card_state
            WHERE card_id = ? AND user_id = ?
            """,
            (payload.card_id, payload.user_id)
        ).fetchone()

        if state_row:
            state = {
                "ease": state_row["ease"],
                "interval": state_row["interval"],
                "repetitions": state_row["repetitions"],
                "lapses": state_row["lapses"]
            }
        else:
            state = {"ease": 2.5, "interval": 0, "repetitions": 0, "lapses": 0}

        exam_date = get_latest_exam_date(conn, payload.user_id)
        new_state = srs.review(state, payload.rating, exam_date=exam_date)

        # Update card_state
        conn.execute(
            """
            INSERT INTO card_state (card_id, user_id, ease, interval, repetitions, due_date, last_reviewed, lapses)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id, user_id) DO UPDATE SET
                ease = excluded.ease,
                interval = excluded.interval,
                repetitions = excluded.repetitions,
                due_date = excluded.due_date,
                last_reviewed = excluded.last_reviewed,
                lapses = excluded.lapses
            """,
            (
                payload.card_id,
                payload.user_id,
                new_state["ease"],
                new_state["interval"],
                new_state["repetitions"],
                new_state["due_date"],
                new_state["last_reviewed"],
                new_state["lapses"]
            )
        )

        # Log review with simulated timestamp
        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        simulated_ts = f"{srs.get_today()} {current_time}"
        conn.execute(
            """
            INSERT INTO review_log (card_id, user_id, rating, reviewed_at)
            VALUES (?, ?, ?, ?)
            """,
            (payload.card_id, payload.user_id, payload.rating, simulated_ts)
        )

        conn.commit()

        return ReviewResponse(
            due_date=new_state["due_date"],
            interval=new_state["interval"],
            ease=new_state["ease"]
        )
    finally:
        conn.close()


@router.get("/api/cards/stats", response_model=CardsStatsResponse)
def get_card_stats(user_id: str = Query(..., description="Scholar ID")):
    """
    Return due_today, reviewed_today, accuracy_today, streak, total_cards,
    mastered (interval >= 21), and per-topic lapses.
    """
    today = srs.get_today()
    conn = get_db_connection()
    try:
        # 1. due_today
        due_row = conn.execute(
            "SELECT COUNT(*) as count FROM card_state WHERE user_id = ? AND due_date <= ?",
            (user_id, today)
        ).fetchone()
        due_today = due_row["count"] if due_row else 0

        # 2. reviewed_today and accuracy_today
        today_reviews = conn.execute(
            """
            SELECT rating FROM review_log
            WHERE user_id = ? AND substr(reviewed_at, 1, 10) = ?
            """,
            (user_id, today)
        ).fetchall()

        reviewed_today = len(today_reviews)
        not_again_count = sum(1 for r in today_reviews if r["rating"] > 0)
        accuracy_today = round((not_again_count / reviewed_today) * 100, 1) if reviewed_today > 0 else 0.0

        # 3. Streak calculation
        rev_dates_rows = conn.execute(
            """
            SELECT DISTINCT substr(reviewed_at, 1, 10) as rev_date
            FROM review_log
            WHERE user_id = ?
            ORDER BY rev_date DESC
            """,
            (user_id,)
        ).fetchall()

        rev_dates = [datetime.date.fromisoformat(r["rev_date"]) for r in rev_dates_rows]
        today_date = datetime.date.fromisoformat(today)
        yesterday_date = today_date - datetime.timedelta(days=1)

        streak = 0
        if rev_dates:
            # Check if streak is active (ends today or yesterday)
            most_recent = rev_dates[0]
            if most_recent in (today_date, yesterday_date):
                curr = most_recent
                streak = 1
                for prev in rev_dates[1:]:
                    if (curr - prev).days == 1:
                        streak += 1
                        curr = prev
                    else:
                        break

        # 4. total_cards in system
        total_cards_row = conn.execute("SELECT COUNT(*) as count FROM cards").fetchone()
        total_cards = total_cards_row["count"] if total_cards_row else 0

        # 5. mastered (interval >= 21)
        mastered_row = conn.execute(
            "SELECT COUNT(*) as count FROM card_state WHERE user_id = ? AND interval >= 21",
            (user_id,)
        ).fetchone()
        mastered = mastered_row["count"] if mastered_row else 0

        # 6. per-topic lapses
        topic_lapses_rows = conn.execute(
            """
            SELECT t.id, t.name, COALESCE(SUM(cs.lapses), 0) as lapses
            FROM topics t
            JOIN cards c ON t.id = c.topic_id
            LEFT JOIN card_state cs ON c.id = cs.card_id AND cs.user_id = ?
            GROUP BY t.id, t.name
            ORDER BY lapses DESC, t.id ASC
            """,
            (user_id,)
        ).fetchall()

        per_topic_lapses = [
            TopicLapse(
                topic_id=r["id"],
                topic_name=r["name"],
                lapses=int(r["lapses"])
            )
            for r in topic_lapses_rows
        ]

        return CardsStatsResponse(
            user_id=user_id,
            due_today=due_today,
            reviewed_today=reviewed_today,
            accuracy_today=accuracy_today,
            streak=streak,
            total_cards=total_cards,
            mastered=mastered,
            per_topic_lapses=per_topic_lapses
        )
    finally:
        conn.close()


@router.get("/api/cards/heatmap")
def get_card_heatmap(user_id: str = Query(..., description="Scholar ID")):
    """Return daily review count for the last 90 days."""
    today_date = datetime.date.fromisoformat(srs.get_today())
    cutoff_date = (today_date - datetime.timedelta(days=90)).isoformat()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT substr(reviewed_at, 1, 10) as day, COUNT(*) as count
            FROM review_log
            WHERE user_id = ? AND substr(reviewed_at, 1, 10) >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (user_id, cutoff_date)
        ).fetchall()

        return [{"date": r["day"], "count": r["count"]} for r in rows]
    finally:
        conn.close()


# --- Dev-Only Utility Endpoints ---

@router.post("/api/dev/advance-days")
def dev_advance_days(payload: AdvanceDaysRequest):
    """Dev-only: Shift the simulated date offset to test due dates."""
    new_today = srs.advance_days(payload.days)
    return {
        "status": "success",
        "days_advanced": payload.days,
        "offset": srs.DEV_DAY_OFFSET,
        "today": new_today
    }


@router.post("/api/dev/reset-cards")
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


@router.post("/api/exams")
def create_exam(payload: ExamCreateRequest):
    """Create or update a user's exam configuration."""
    conn = get_db_connection()
    try:
        update = conn.execute(
            """
            UPDATE exams
            SET course = ?, exam_date = ?, target_score = ?, daily_minutes = ?
            WHERE user_id = ?
            """,
            (
                payload.course,
                payload.exam_date.isoformat(),
                payload.target_score,
                payload.daily_minutes,
                payload.user_id,
            ),
        )
        if update.rowcount == 0:
            cursor = conn.execute(
                """
                INSERT INTO exams (user_id, course, exam_date, target_score, daily_minutes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.user_id,
                    payload.course,
                    payload.exam_date.isoformat(),
                    payload.target_score,
                    payload.daily_minutes,
                ),
            )
            exam_id = cursor.lastrowid
        else:
            row = conn.execute(
                "SELECT id FROM exams WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (payload.user_id,),
            ).fetchone()
            exam_id = row["id"]
        conn.commit()
        return {
            "id": exam_id,
            "user_id": payload.user_id,
            "course": payload.course,
            "exam_date": payload.exam_date.isoformat(),
            "target_score": payload.target_score,
            "daily_minutes": payload.daily_minutes
        }
    finally:
        conn.close()
