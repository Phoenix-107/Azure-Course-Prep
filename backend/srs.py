"""
Spaced Repetition System (SRS) using the SM-2 algorithm.
Handles card scheduling, preview intervals, dev time-travel, and quiz error boosting.
"""

import datetime
import json
import math
from typing import Any, Dict, Optional, Union

# Global dev offset for time-travel testing
DEV_DAY_OFFSET = 0


def get_today() -> str:
    """Return the current simulated date as YYYY-MM-DD string."""
    today = datetime.date.today() + datetime.timedelta(days=DEV_DAY_OFFSET)
    return today.isoformat()


def advance_days(days: int) -> str:
    """Advance the simulated date offset by specified days."""
    global DEV_DAY_OFFSET
    DEV_DAY_OFFSET += days
    return get_today()


def set_day_offset(offset: int) -> str:
    """Explicitly set the simulated date offset."""
    global DEV_DAY_OFFSET
    DEV_DAY_OFFSET = offset
    return get_today()


def reset_day_offset() -> str:
    """Reset the simulated date offset back to zero."""
    global DEV_DAY_OFFSET
    DEV_DAY_OFFSET = 0
    return get_today()


def review(
    state: Dict[str, Any],
    rating: int,
    exam_date: Optional[Union[str, datetime.date]] = None,
) -> Dict[str, Any]:
    """
    Calculate next SM-2 state based on rating (0=Again, 1=Hard, 2=Good, 3=Easy).
    Returns a new dict with updated ease, interval, repetitions, lapses, due_date, and last_reviewed.
    Does NOT mutate the original state.
    """
    if rating not in (0, 1, 2, 3):
        raise ValueError(f"Invalid rating: {rating}. Must be 0, 1, 2, or 3.")

    ease = float(state.get("ease", 2.5))
    interval = int(state.get("interval", 0))
    repetitions = int(state.get("repetitions", 0))
    lapses = int(state.get("lapses", 0))

    if rating == 0:  # Again
        repetitions = 0
        interval = 1
        ease = max(1.3, ease - 0.2)
        lapses += 1
    else:  # Hard (1), Good (2), Easy (3)
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 3
        else:
            interval = math.floor(interval * ease + 0.5)

        if rating == 1:  # Hard
            ease = max(1.3, ease - 0.15)
        elif rating == 3:  # Easy
            ease += 0.15
        # Good (2): ease remains unchanged

        repetitions += 1

    # Apply exam cap if exam_date provided
    today_str = get_today()
    today_date = datetime.date.fromisoformat(today_str)

    if exam_date:
        if isinstance(exam_date, str):
            exam_date_obj = datetime.date.fromisoformat(exam_date)
        else:
            exam_date_obj = exam_date

        days_left = (exam_date_obj - today_date).days
        interval = max(1, min(interval, days_left - 1))

    due_date = (today_date + datetime.timedelta(days=interval)).isoformat()

    return {
        "ease": round(ease, 4),
        "interval": interval,
        "repetitions": repetitions,
        "lapses": lapses,
        "due_date": due_date,
        "last_reviewed": today_str,
    }


def preview_intervals(
    state: Dict[str, Any],
    exam_date: Optional[Union[str, datetime.date]] = None,
) -> Dict[str, int]:
    """
    Return resulting interval for each rating 0-3 WITHOUT mutating the input state.
    Keys are strings "0", "1", "2", "3" (or integers).
    """
    return {
        str(r): review(state, r, exam_date)["interval"]
        for r in range(4)
    }


def boost_card_for_question(conn, question_id: int, user_id: str) -> Optional[int]:
    """
    Create or boost a flashcard linked to a quiz question when answered incorrectly.
    - Find card with source_question_id = question_id.
    - If none, create one from quiz question (front=question, back=correct option trimmed <=15 words).
    - Upsert card_state with due_date=today and lapses incremented (ease/interval otherwise preserved).
    - Never creates duplicate cards (handles UNIQUE front constraint).
    """
    cursor = conn.cursor()

    card_row = cursor.execute(
        "SELECT id, topic_id FROM cards WHERE source_question_id = ?",
        (question_id,)
    ).fetchone()

    if card_row:
        card_id = card_row["id"]
    else:
        q_row = cursor.execute(
            "SELECT id, topic_id, question, options_json, answer_index FROM questions WHERE id = ?",
            (question_id,)
        ).fetchone()

        if not q_row:
            return None

        options = json.loads(q_row["options_json"])
        correct_idx = q_row["answer_index"]
        correct_text = options[correct_idx] if 0 <= correct_idx < len(options) else ""

        # Trim to under 15 words
        words = correct_text.strip().split()
        back = " ".join(words[:15]) if len(words) > 15 else correct_text.strip()

        cursor.execute(
            """
            INSERT INTO cards (topic_id, front, back, type, source_question_id)
            VALUES (?, ?, ?, 'basic', ?)
            ON CONFLICT(front) DO UPDATE SET
                source_question_id = excluded.source_question_id
            """,
            (q_row["topic_id"], q_row["question"], back, question_id)
        )

        created_card = cursor.execute(
            "SELECT id FROM cards WHERE front = ?",
            (q_row["question"],)
        ).fetchone()

        if not created_card:
            return None
        card_id = created_card["id"]

    today = get_today()

    # Upsert card_state for this user with due_date = today and lapses incremented
    cursor.execute(
        """
        INSERT INTO card_state (card_id, user_id, ease, interval, repetitions, due_date, lapses)
        VALUES (?, ?, 2.5, 0, 0, ?, 1)
        ON CONFLICT(card_id, user_id) DO UPDATE SET
            due_date = excluded.due_date,
            lapses = card_state.lapses + 1
        """,
        (card_id, user_id, today)
    )
    conn.commit()
    return card_id
