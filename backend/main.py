"""
FastAPI Backend Application for Azure AZ-900 Scholar Prep.
Provides REST API endpoints for topics, smart adaptive quizzes, attempt logging,
and dashboard readiness analytics. Serves frontend static assets.
"""

import json
import random
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Path as PathParameter, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.db import get_db_connection, init_db
from backend.cards_router import router as cards_router
from backend import srs
from backend.readiness import (
    build_day_plan,
    choose_mode,
    coach_note,
    overall,
    pressure,
    topic_readiness,
)

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Azure Scholar AZ-900 API",
    description="Backend API for Azure AZ-900 Preparation Platform",
    version="1.0.0"
)

# Enable CORS for local client development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Flashcards Coach router
app.include_router(cards_router)

# In-memory session tracking for randomized question option orders
# Key: (user_id, question_id) -> {"shuffled_to_orig": list[int], "orig_to_shuffled": list[int], "timestamp": float}
SESSION_SHUFFLE_CACHE: Dict[Tuple[str, int], dict] = {}


def cleanup_session_cache():
    """Prune session shuffle mappings older than 2 hours."""
    now = time.time()
    expired = [k for k, v in SESSION_SHUFFLE_CACHE.items() if now - v.get("timestamp", 0) > 7200]
    for k in expired:
        SESSION_SHUFFLE_CACHE.pop(k, None)


# --- Pydantic Request & Response Models ---

class TopicOut(BaseModel):
    id: str
    name: str
    weight: float
    question_count: int


class QuizQuestionOut(BaseModel):
    id: int
    topic_id: str
    topic_name: str
    question: str
    options: List[str]


class AttemptRequest(BaseModel):
    user_id: str
    question_id: int
    chosen_index: int = Field(..., ge=0, le=3)
    mode: str = "topic"  # 'topic' | 'mock' | 'diagnostic'


class AttemptResponse(BaseModel):
    correct: bool
    correct_index: int
    explanation: str


class PlanDoneRequest(BaseModel):
    user_id: str


# --- Lifecycle Events ---

@app.on_event("startup")
def on_startup():
    init_db()


# --- API Routes ---

def _activity_date(timestamp: Optional[str]) -> Optional[date]:
    if not timestamp:
        return None
    try:
        return date.fromisoformat(timestamp[:10])
    except ValueError:
        return None


def _readiness_summary(conn, user_id: str) -> dict:
    today = date.fromisoformat(srs.get_today())
    topics_rows = conn.execute(
        """
        SELECT t.id, t.name, t.weight, COUNT(q.id) AS question_count
        FROM topics t
        LEFT JOIN questions q ON t.id = q.topic_id
        GROUP BY t.id, t.name, t.weight
        ORDER BY t.id
        """
    ).fetchall()
    attempts_rows = conn.execute(
        """
        SELECT question_id, topic_id, correct, answered_at, mode
        FROM attempts
        WHERE user_id = ?
        ORDER BY answered_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    card_rows = conn.execute(
        """
        SELECT c.topic_id, cs.interval, cs.lapses, cs.last_reviewed
        FROM card_state cs
        JOIN cards c ON c.id = cs.card_id
        WHERE cs.user_id = ?
        """,
        (user_id,),
    ).fetchall()

    attempts_by_topic = defaultdict(list)
    cards_by_topic = defaultdict(list)
    for attempt in attempts_rows:
        attempts_by_topic[attempt["topic_id"]].append(attempt)
    for card in card_rows:
        cards_by_topic[card["topic_id"]].append(card)

    topic_metrics = []
    for topic in topics_rows:
        topic_id = topic["id"]
        attempts = attempts_by_topic.get(topic_id, [])
        recent_attempts = attempts[:10]
        if recent_attempts:
            weights = range(len(recent_attempts), 0, -1)
            quiz_accuracy = sum(
                float(attempt["correct"]) * weight
                for attempt, weight in zip(recent_attempts, weights)
            ) / sum(weights)
        else:
            quiz_accuracy = None

        started_cards = cards_by_topic.get(topic_id, [])
        card_mastery = None
        if started_cards:
            mastered = sum(
                1 for card in started_cards
                if card["interval"] >= 21 and card["lapses"] < 3
            )
            card_mastery = mastered / len(started_cards)

        activity_dates = [
            activity_date
            for activity_date in (
                [_activity_date(attempt["answered_at"]) for attempt in attempts]
                + [_activity_date(card["last_reviewed"]) for card in started_cards]
            )
            if activity_date is not None
        ]
        last_activity = max(activity_dates) if activity_dates else None
        days_since_activity = (today - last_activity).days if last_activity else 14
        recency = min(1.0, max(0.0, 1.0 - days_since_activity / 14.0))
        readiness_score = topic_readiness(quiz_accuracy, card_mastery, recency)
        topic_metrics.append({
            "id": topic_id,
            "name": topic["name"],
            "weight": float(topic["weight"]),
            "readiness": readiness_score,
            "quiz_accuracy": round(quiz_accuracy * 100, 1) if quiz_accuracy is not None else None,
            "card_mastery": round(card_mastery * 100, 1) if card_mastery is not None else None,
            "recency": round(recency * 100, 1),
            "attempts": len(attempts),
        })

    exam_row = conn.execute(
        """
        SELECT exam_date, daily_minutes, target_score, course
        FROM exams
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    exam_date = exam_row["exam_date"] if exam_row else None
    exam_passed = bool(exam_date and date.fromisoformat(exam_date) < today)
    days_left = max(0, (date.fromisoformat(exam_date) - today).days) if exam_date else None
    daily_minutes = int(exam_row["daily_minutes"]) if exam_row else 45
    target_score = int(exam_row["target_score"]) if exam_row else 85

    known_topics = [
        {"readiness": topic["readiness"], "weight": topic["weight"]}
        for topic in topic_metrics
        if topic["readiness"] is not None
    ]
    overall_score = overall(known_topics)
    has_activity = any(
        attempts_by_topic.values()
    ) or any(card["last_reviewed"] for card in card_rows)
    pressure_score = pressure(
        [{"readiness": topic["readiness"], "weight": topic["weight"]} for topic in topic_metrics],
        days_left if days_left is not None else 30,
        daily_minutes,
        target_score,
    )
    mode = choose_mode(pressure_score, has_activity)

    if overall_score is not None:
        conn.execute(
            """
            INSERT INTO readiness_snapshots (user_id, snap_date, overall)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, snap_date) DO UPDATE SET overall = excluded.overall
            """,
            (user_id, today.isoformat(), overall_score),
        )
        conn.commit()
        baseline = conn.execute(
            """
            SELECT overall FROM readiness_snapshots
            WHERE user_id = ? AND snap_date <= ?
            ORDER BY snap_date DESC LIMIT 1
            """,
            (user_id, (today - timedelta(days=7)).isoformat()),
        ).fetchone()
        delta_7d = round(overall_score - baseline["overall"], 1) if baseline else 0.0
    else:
        delta_7d = 0.0

    weakest_topics = sorted(
        (topic for topic in topic_metrics if topic["readiness"] is not None),
        key=lambda topic: topic["readiness"],
    )
    if not has_activity:
        note = "Start with a diagnostic quiz to establish your baseline across all Azure topics."
    elif not exam_date:
        note = "Set an exam date to get a countdown and a schedule tailored to your remaining study time."
    elif exam_passed:
        note = "Your exam date has passed. Update it to continue receiving an adaptive study plan."
    else:
        note = coach_note(
            mode,
            days_left if days_left is not None else 0,
            overall_score or 0.0,
            [topic["name"] for topic in weakest_topics],
        )

    return {
        "overall": overall_score,
        "delta_7d": delta_7d,
        "mode": mode,
        "days_left": days_left,
        "exam_date": exam_date,
        "exam_passed": exam_passed,
        "daily_minutes": daily_minutes,
        "target_score": target_score,
        "course": exam_row["course"] if exam_row else None,
        "has_activity": has_activity,
        "topics": topic_metrics,
        "coach_note": note,
    }


@app.get("/api/readiness")
def get_readiness(user_id: str = Query(..., description="Unique scholar ID")):
    """Return transparent readiness inputs, exam countdown, and suggested mode."""
    conn = get_db_connection()
    try:
        return _readiness_summary(conn, user_id)
    finally:
        conn.close()


@app.get("/api/readiness/trend")
def get_readiness_trend(user_id: str = Query(..., description="Unique scholar ID")):
    conn = get_db_connection()
    try:
        exam_row = conn.execute(
            "SELECT exam_date FROM exams WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        exam_date = exam_row["exam_date"] if exam_row else None
        rows = conn.execute(
            """
            SELECT snap_date, overall FROM readiness_snapshots
            WHERE user_id = ?
            ORDER BY snap_date
            """,
            (user_id,),
        ).fetchall()
        snapshots = [
            {"date": row["snap_date"], "readiness": float(row["overall"])}
            for row in rows
        ]
        projection = None
        if (
            exam_date
            and snapshots
            and date.fromisoformat(exam_date) >= date.fromisoformat(snapshots[-1]["date"])
        ):
            points = [
                (date.fromisoformat(item["date"]).toordinal(), item["readiness"])
                for item in snapshots
            ]
            mean_x = sum(point[0] for point in points) / len(points)
            mean_y = sum(point[1] for point in points) / len(points)
            denominator = sum((x - mean_x) ** 2 for x, _ in points)
            slope = (
                sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
                if len(points) > 1 and denominator
                else 0.0
            )
            projected = mean_y + slope * (date.fromisoformat(exam_date).toordinal() - mean_x)
            projection = {
                "date": exam_date,
                "readiness": round(min(100.0, max(0.0, projected)), 1),
            }
        return {"snapshots": snapshots, "projection": projection}
    finally:
        conn.close()


@app.get("/api/plan/today")
def get_plan_today(user_id: str = Query(..., description="Unique scholar ID")):
    """Recompute and persist today's adaptive study checklist."""
    readiness = get_readiness(user_id=user_id)
    conn = get_db_connection()
    try:
        today = srs.get_today()
        due_cards = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM card_state
            WHERE user_id = ? AND due_date <= ?
            """,
            (user_id, today),
        ).fetchone()["count"]
        last_mock = conn.execute(
            """
            SELECT answered_at FROM attempts
            WHERE user_id = ? AND mode = 'mock'
            ORDER BY answered_at DESC, id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        activity_anchor_date = _activity_date(last_mock["answered_at"]) if last_mock else None
        if activity_anchor_date is None:
            first_activity = conn.execute(
                """
                SELECT MIN(activity_date) AS activity_date
                FROM (
                    SELECT answered_at AS activity_date FROM attempts WHERE user_id = ?
                    UNION ALL
                    SELECT reviewed_at AS activity_date FROM review_log WHERE user_id = ?
                )
                """,
                (user_id, user_id),
            ).fetchone()
            activity_anchor_date = _activity_date(first_activity["activity_date"])
        days_since_last_mock = (
            max(0, (date.fromisoformat(today) - activity_anchor_date).days)
            if activity_anchor_date
            else None
        )
        planning_days_left = readiness["days_left"] if readiness["days_left"] is not None else 999

        if not readiness["has_activity"]:
            plan = [{"activity": "diagnostic", "minutes": readiness["daily_minutes"]}]
        else:
            plan = build_day_plan(
                [
                    {"id": topic["id"], "readiness": topic["readiness"], "weight": topic["weight"]}
                    for topic in readiness["topics"]
                ],
                readiness["daily_minutes"],
                readiness["mode"],
                due_cards,
                planning_days_left,
                readiness["target_score"],
                days_since_last_mock,
            )

        existing_rows = conn.execute(
            "SELECT id, activity, topic_id, done FROM study_plan WHERE user_id = ? AND plan_date = ?",
            (user_id, today),
        ).fetchall()
        completed = {
            (row["activity"], row["topic_id"]): bool(row["done"])
            for row in existing_rows
        }
        conn.execute("DELETE FROM study_plan WHERE user_id = ? AND plan_date = ?", (user_id, today))
        for item in plan:
            cursor = conn.execute(
                """
                INSERT INTO study_plan (user_id, plan_date, activity, topic_id, minutes, done)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    today,
                    item["activity"],
                    item.get("topic_id"),
                    item["minutes"],
                    int(completed.get((item["activity"], item.get("topic_id")), False)),
                ),
            )
            item["id"] = cursor.lastrowid
            item["done"] = bool(completed.get((item["activity"], item.get("topic_id")), False))
        conn.commit()
        return {
            "mode": readiness["mode"],
            "minutes_total": sum(item["minutes"] for item in plan),
            "items": plan,
            "coach_note": readiness["coach_note"],
        }
    finally:
        conn.close()


@app.post("/api/plan/{plan_id}/done")
def mark_plan_item_done(
    payload: PlanDoneRequest,
    plan_id: int = PathParameter(..., ge=1),
):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "UPDATE study_plan SET done = 1 WHERE id = ? AND user_id = ?",
            (plan_id, payload.user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study plan item not found")
        conn.commit()
        return {"id": plan_id, "done": True}
    finally:
        conn.close()


@app.get("/api/topics", response_model=List[TopicOut])
def get_topics():
    """Return all AZ-900 topics along with their total question counts."""
    conn = get_db_connection()
    try:
        query = """
        SELECT t.id, t.name, t.weight, COUNT(q.id) as question_count
        FROM topics t
        LEFT JOIN questions q ON t.id = q.topic_id
        GROUP BY t.id, t.name, t.weight
        ORDER BY t.weight DESC, t.id ASC;
        """
        rows = conn.execute(query).fetchall()
        return [
            TopicOut(
                id=r["id"],
                name=r["name"],
                weight=float(r["weight"]),
                question_count=int(r["question_count"])
            )
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/quiz", response_model=List[QuizQuestionOut])
def get_quiz(
    topic: Optional[str] = Query(None, description="Topic ID or 'all' for mixed mock"),
    n: int = Query(5, ge=1, le=50, description="Number of questions to sample"),
    user_id: str = Query(..., description="Unique persistent scholar ID"),
    mode: str = Query("topic", description="Quiz mode: topic | mock | diagnostic")
):
    """
    Sample questions from SQLite with 3x weighting for questions answered incorrectly
    by user_id within the last 14 days. Options are randomized per session,
    and correct answer indices are stripped from the response for security.
    """
    cleanup_session_cache()
    conn = get_db_connection()
    try:
        # 1. Fetch available questions matching topic criteria
        if topic and topic.lower() != "all":
            questions_query = """
            SELECT q.id, q.topic_id, q.question, q.options_json, q.answer_index, t.name as topic_name
            FROM questions q
            JOIN topics t ON q.topic_id = t.id
            WHERE q.topic_id = ?
            """
            rows = conn.execute(questions_query, (topic,)).fetchall()
        else:
            questions_query = """
            SELECT q.id, q.topic_id, q.question, q.options_json, q.answer_index, t.name as topic_name
            FROM questions q
            JOIN topics t ON q.topic_id = t.id
            """
            rows = conn.execute(questions_query).fetchall()

        if not rows:
            return []

        # 2. Resurfacing algorithm: 3x weight for questions answered wrong in past 14 days
        wrong_attempts = conn.execute(
            """
            SELECT question_id
            FROM attempts
            WHERE user_id = ? AND correct = 0
              AND answered_at >= datetime('now', '-14 days')
            """,
            (user_id,)
        ).fetchall()
        wrong_q_ids = {r["question_id"] for r in wrong_attempts}

        weights = [3.0 if r["id"] in wrong_q_ids else 1.0 for r in rows]

        # 3. Weighted random sampling without replacement
        sample_size = min(n, len(rows))
        picked_rows = []
        pool = list(rows)
        w_pool = list(weights)

        for _ in range(sample_size):
            if not pool:
                break
            chosen_idx = random.choices(range(len(pool)), weights=w_pool, k=1)[0]
            picked_rows.append(pool.pop(chosen_idx))
            w_pool.pop(chosen_idx)

        # 4. Prepare response and store session mapping for shuffled options
        quiz_output = []
        for r in picked_rows:
            orig_options = json.loads(r["options_json"])
            orig_correct_idx = r["answer_index"]

            # Generate random permutation of indices [0, 1, 2, 3]
            indices = list(range(len(orig_options)))
            random.shuffle(indices)

            shuffled_options = [orig_options[i] for i in indices]

            # Mapping from shuffled position -> original position
            shuffled_to_orig = indices
            # Mapping from original position -> shuffled position
            orig_to_shuffled = {orig: shuf for shuf, orig in enumerate(indices)}

            # Save in server-side session cache for secure answer verification
            session_key = (user_id, r["id"])
            SESSION_SHUFFLE_CACHE[session_key] = {
                "shuffled_to_orig": shuffled_to_orig,
                "orig_to_shuffled": orig_to_shuffled,
                "orig_correct_idx": orig_correct_idx,
                "timestamp": time.time()
            }

            quiz_output.append(
                QuizQuestionOut(
                    id=r["id"],
                    topic_id=r["topic_id"],
                    topic_name=r["topic_name"],
                    question=r["question"],
                    options=shuffled_options
                )
            )

        return quiz_output
    finally:
        conn.close()


@app.post("/api/quiz/attempt", response_model=AttemptResponse)
def submit_attempt(payload: AttemptRequest):
    """
    Verify question correctness against SQLite, log the attempt,
    and return whether the answer was correct, the correct index (in client's shuffled layout),
    and the educational explanation.
    """
    conn = get_db_connection()
    try:
        q_row = conn.execute(
            "SELECT id, topic_id, answer_index, explanation, options_json FROM questions WHERE id = ?",
            (payload.question_id,)
        ).fetchone()

        if not q_row:
            raise HTTPException(status_code=404, detail="Question not found")

        orig_correct_index = q_row["answer_index"]
        session_key = (payload.user_id, payload.question_id)
        session_info = SESSION_SHUFFLE_CACHE.get(session_key)

        if session_info:
            # Map client's shuffled chosen index to the original index
            original_chosen_idx = session_info["shuffled_to_orig"][payload.chosen_index]
            is_correct = (original_chosen_idx == orig_correct_index)
            client_correct_index = session_info["orig_to_shuffled"][orig_correct_index]
        else:
            # Fallback if session expired or direct API call
            is_correct = (payload.chosen_index == orig_correct_index)
            client_correct_index = orig_correct_index

        # Insert attempt record
        conn.execute(
            """
            INSERT INTO attempts (user_id, question_id, topic_id, correct, mode)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.user_id,
                payload.question_id,
                q_row["topic_id"],
                1 if is_correct else 0,
                payload.mode
            )
        )
        conn.commit()

        # Boost or create a spaced repetition flashcard on wrong answer
        if not is_correct:
            try:
                srs.boost_card_for_question(conn, payload.question_id, payload.user_id)
            except Exception:
                # Failure here must never break quiz answering
                pass

        return AttemptResponse(
            correct=is_correct,
            correct_index=client_correct_index,
            explanation=q_row["explanation"] or "No detailed explanation provided."
        )
    finally:
        conn.close()


@app.get("/api/dashboard/stats")
def get_dashboard_stats(user_id: str = Query(..., description="Unique scholar ID")):
    """
    Aggregate overall exam readiness percentage, total questions attempted,
    overall accuracy, and per-topic readiness breakdown with trend data for Chart.js.
    """
    conn = get_db_connection()
    try:
        # 1. Fetch all topics with weights and question counts
        topics_rows = conn.execute("""
            SELECT t.id, t.name, t.weight, COUNT(q.id) as question_count
            FROM topics t
            LEFT JOIN questions q ON t.id = q.topic_id
            GROUP BY t.id, t.name, t.weight
            ORDER BY t.id
        """).fetchall()

        # 2. Fetch all attempts by this user
        attempts_rows = conn.execute("""
            SELECT a.id, a.question_id, a.topic_id, a.correct, a.mode, a.answered_at,
                   t.name as topic_name
            FROM attempts a
            LEFT JOIN topics t ON a.topic_id = t.id
            WHERE a.user_id = ?
            ORDER BY a.answered_at DESC
        """, (user_id,)).fetchall()

        total_attempts = len(attempts_rows)
        total_correct = sum(1 for a in attempts_rows if a["correct"] == 1)
        overall_accuracy = round((total_correct / total_attempts * 100), 1) if total_attempts > 0 else 0.0

        # Topic breakdown statistics
        topic_attempts_map = defaultdict(list)
        for a in attempts_rows:
            topic_attempts_map[a["topic_id"]].append(a["correct"])

        topics_breakdown = []
        readiness_entries = []

        for t in topics_rows:
            tid = t["id"]
            name = t["name"]
            weight = float(t["weight"])
            q_count = int(t["question_count"])

            t_atts = topic_attempts_map.get(tid, [])
            t_count = len(t_atts)
            t_correct = sum(1 for c in t_atts if c == 1)
            t_acc = round((t_correct / t_count * 100), 1) if t_count > 0 else 0.0

            # Unique questions attempted in this topic
            unique_attempted = len({
                a["question_id"] for a in attempts_rows if a["topic_id"] == tid
            })

            coverage = (unique_attempted / q_count) if q_count > 0 else 0.0

            # Use rule-based readiness formula aligned with the design doc.
            # Only topics with attempts are considered known; otherwise they contribute
            # as unknown and are excluded from the weighted average.
            if t_count > 0:
                quiz_acc = t_acc / 100.0
                card_mastery = min(1.0, coverage)
                recency = 1.0 if t_count > 0 else 0.0
                t_readiness = topic_readiness(quiz_acc, card_mastery, recency)
            else:
                t_readiness = None

            readiness_entries.append({"id": tid, "readiness": t_readiness, "weight": weight})
            topics_breakdown.append({
                "id": tid,
                "name": name,
                "weight": weight,
                "total_questions": q_count,
                "attempts": t_count,
                "correct": t_correct,
                "accuracy": t_acc,
                "coverage_pct": round(coverage * 100, 1),
                "readiness": 0.0 if t_readiness is None else t_readiness,
                "target_accuracy": 80.0  # AZ-900 Target passing threshold
            })

        overall_readiness = overall(readiness_entries)
        if overall_readiness is None:
            overall_readiness = 0.0

        # Determine weakest topic
        # Prefer topics that have been attempted with lowest accuracy, or lowest readiness
        if topics_breakdown:
            # Sort by readiness ascending, then attempts
            sorted_by_weakness = sorted(topics_breakdown, key=lambda x: (x["readiness"], x["accuracy"]))
            weakest_topic = sorted_by_weakness[0]
        else:
            weakest_topic = None

        # Format recent history (up to last 10 attempts)
        recent_history = [
            {
                "id": a["id"],
                "topic_id": a["topic_id"],
                "topic_name": a["topic_name"] or a["topic_id"],
                "correct": bool(a["correct"]),
                "mode": a["mode"],
                "answered_at": a["answered_at"]
            }
            for a in attempts_rows[:10]
        ]

        return {
            "user_id": user_id,
            "overall_readiness": overall_readiness,
            "total_questions_attempted": total_attempts,
            "total_correct": total_correct,
            "overall_accuracy": overall_accuracy,
            "weakest_topic": weakest_topic,
            "topics": topics_breakdown,
            "recent_history": recent_history
        }
    finally:
        conn.close()


# --- Static Frontend Serving ---

# Static files mount for CSS, JS, Assets
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def serve_index():
    """Root redirect to Dashboard view."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")

@app.get("/dashboard")
def serve_dashboard():
    """Direct route for dashboard."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")

@app.get("/quiz")
def serve_quiz():
    """Direct route for smart quiz builder."""
    return FileResponse(FRONTEND_DIR / "quiz.html")

@app.get("/flashcards")
def serve_flashcards():
    """Direct route for flashcards coach."""
    return FileResponse(FRONTEND_DIR / "flashcards.html")
