"""
FastAPI Backend Application for Azure AZ-900 Scholar Prep.
Provides REST API endpoints for topics, smart adaptive quizzes, attempt logging,
and dashboard readiness analytics. Serves frontend static assets.
"""

import json
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.db import get_db_connection, init_db
from backend.cards_router import router as cards_router
from backend import srs

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


# --- Lifecycle Events ---

@app.on_event("startup")
def on_startup():
    init_db()


# --- API Routes ---

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
        weighted_readiness_sum = 0.0
        total_weight_sum = 0.0

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

            # Topic Readiness Formula:
            # 70% Accuracy + 30% Question Bank Coverage
            # If no attempts yet, readiness is 0.0
            if t_count > 0:
                t_readiness = round(min(100.0, (t_acc * 0.7) + (coverage * 30.0)), 1)
            else:
                t_readiness = 0.0

            weighted_readiness_sum += t_readiness * weight
            total_weight_sum += weight

            topics_breakdown.append({
                "id": tid,
                "name": name,
                "weight": weight,
                "total_questions": q_count,
                "attempts": t_count,
                "correct": t_correct,
                "accuracy": t_acc,
                "coverage_pct": round(coverage * 100, 1),
                "readiness": t_readiness,
                "target_accuracy": 80.0  # AZ-900 Target passing threshold
            })

        overall_readiness = round(weighted_readiness_sum / total_weight_sum, 1) if total_weight_sum > 0 else 0.0

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
