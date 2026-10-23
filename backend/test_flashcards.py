"""
Pytest test suite for SM-2 spaced repetition logic, cards API endpoints,
and quiz error boost integration.
"""

import datetime
import pytest

from backend import srs
from backend.db import get_db_connection, init_db
from backend.seed_cards import seed_cards
from backend.cards_router import (
    get_due_cards,
    review_card,
    get_card_stats,
    dev_advance_days,
    dev_reset_cards,
    create_exam,
    ReviewRequest,
    AdvanceDaysRequest,
    ResetCardsRequest,
    ExamCreateRequest,
)
from backend.main import submit_attempt, AttemptRequest


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure schema and seed cards are in place, reset day offset."""
    srs.reset_day_offset()
    init_db()
    seed_cards()
    yield
    srs.reset_day_offset()


# ==============================================================================
# 1. SM-2 Scheduling Unit Tests
# ==============================================================================

def test_new_card_good():
    """new card + Good -> interval 1, repetitions 1"""
    new_state = {"ease": 2.5, "interval": 0, "repetitions": 0, "lapses": 0}
    res = srs.review(new_state, rating=2)  # 2 = Good
    assert res["interval"] == 1
    assert res["repetitions"] == 1
    assert res["ease"] == 2.5
    assert res["lapses"] == 0


def test_repetitions_1_good():
    """repetitions 1 + Good -> interval 3"""
    state = {"ease": 2.5, "interval": 1, "repetitions": 1, "lapses": 0}
    res = srs.review(state, rating=2)
    assert res["interval"] == 3
    assert res["repetitions"] == 2
    assert res["ease"] == 2.5


def test_repetitions_2_good():
    """repetitions 2, interval 3, ease 2.5 + Good -> interval 8"""
    state = {"ease": 2.5, "interval": 3, "repetitions": 2, "lapses": 0}
    res = srs.review(state, rating=2)
    assert res["interval"] == 8  # floor(3 * 2.5 + 0.5) = floor(8.0) = 8
    assert res["repetitions"] == 3
    assert res["ease"] == 2.5


def test_any_card_again():
    """any card + Again -> interval 1, repetitions 0, lapses +1, ease -0.2"""
    state = {"ease": 2.5, "interval": 8, "repetitions": 3, "lapses": 1}
    res = srs.review(state, rating=0)  # 0 = Again
    assert res["interval"] == 1
    assert res["repetitions"] == 0
    assert res["lapses"] == 2
    assert res["ease"] == 2.3


def test_ease_floor_clamp():
    """ease 1.3 + Hard or Again -> ease stays 1.3"""
    state = {"ease": 1.3, "interval": 5, "repetitions": 2, "lapses": 1}
    
    # Rating 1 = Hard (ease - 0.15) clamped to 1.3
    res_hard = srs.review(state, rating=1)
    assert res_hard["ease"] == 1.3

    # Rating 0 = Again (ease - 0.2) clamped to 1.3
    res_again = srs.review(state, rating=0)
    assert res_again["ease"] == 1.3


def test_exam_cap_future():
    """exam in 4 days, computed interval 8 + Good -> interval 3"""
    today_date = datetime.date.fromisoformat(srs.get_today())
    exam_date = (today_date + datetime.timedelta(days=4)).isoformat()
    state = {"ease": 2.5, "interval": 3, "repetitions": 2, "lapses": 0}
    
    # Normally 3 * 2.5 + 0.5 = 8; days_left = 4; cap = max(1, min(8, 4 - 1)) = 3
    res = srs.review(state, rating=2, exam_date=exam_date)
    assert res["interval"] == 3


def test_exam_cap_tomorrow():
    """exam tomorrow -> interval is still at least 1"""
    today_date = datetime.date.fromisoformat(srs.get_today())
    exam_date = (today_date + datetime.timedelta(days=1)).isoformat()
    state = {"ease": 2.5, "interval": 3, "repetitions": 2, "lapses": 0}
    
    # days_left = 1; cap = max(1, min(8, 1 - 1)) = 1
    res = srs.review(state, rating=2, exam_date=exam_date)
    assert res["interval"] == 1


def test_preview_intervals_does_not_mutate():
    """preview_intervals does not mutate the input state"""
    state = {"ease": 2.5, "interval": 3, "repetitions": 2, "lapses": 1}
    state_copy = dict(state)
    previews = srs.preview_intervals(state)
    
    assert state == state_copy
    assert "0" in previews and "1" in previews and "2" in previews and "3" in previews
    assert previews["0"] == 1
    assert previews["2"] == 8


# ==============================================================================
# 2. Flashcards API Integration Tests
# ==============================================================================

def test_api_due_ordering_and_limit():
    """Due endpoint returns due cards before new ones and respects new_limit."""
    user_id = "test-scholar-ordering"
    # Reset user state
    dev_reset_cards(ResetCardsRequest(user_id=user_id))

    # Fetch with new_limit = 1
    res = get_due_cards(user_id=user_id, new_limit=1)
    assert res.due_count == 0
    assert res.new_count == 1
    assert len(res.cards) == 1
    assert res.cards[0].is_new is True

    # Review first card as Good (interval 1 -> due tomorrow)
    first_card = res.cards[0]
    rev_res = review_card(ReviewRequest(
        user_id=user_id,
        card_id=first_card.id,
        rating=2
    ))
    assert rev_res.interval == 1

    # Advance time by 1 day
    dev_advance_days(AdvanceDaysRequest(days=1))

    # Now fetch again with new_limit = 3
    res2 = get_due_cards(user_id=user_id, new_limit=3)
    assert res2.due_count == 1
    assert res2.cards[0].id == first_card.id
    assert res2.cards[0].is_new is False
    assert res2.new_count == 3
    assert len(res2.cards) == 4


def test_api_review_updates_card_state_and_log():
    """Review updates card_state and review_log."""
    user_id = "test-scholar-review"
    dev_reset_cards(ResetCardsRequest(user_id=user_id))

    # Get one new card
    res = get_due_cards(user_id=user_id, new_limit=1)
    card = res.cards[0]

    # Post review
    rev = review_card(ReviewRequest(
        user_id=user_id,
        card_id=card.id,
        rating=3  # Easy
    ))
    assert rev.interval == 1
    assert rev.ease == 2.65  # 2.5 + 0.15

    # Check stats endpoint reflects review
    stats = get_card_stats(user_id=user_id)
    assert stats.reviewed_today >= 1
    assert stats.accuracy_today == 100.0


def test_quiz_wrong_attempt_boosts_card_without_duplicates():
    """A wrong quiz attempt creates or boosts exactly one card (no duplicates on repeat)."""
    user_id = "test-scholar-quiz-boost"
    dev_reset_cards(ResetCardsRequest(user_id=user_id))

    # Find a valid question id
    conn = get_db_connection()
    q_row = conn.execute("SELECT id, question, answer_index FROM questions LIMIT 1").fetchone()
    q_id = q_row["id"]
    wrong_chosen_idx = (q_row["answer_index"] + 1) % 4
    conn.close()

    # Submit wrong quiz attempt #1
    attempt_res1 = submit_attempt(AttemptRequest(
        user_id=user_id,
        question_id=q_id,
        chosen_index=wrong_chosen_idx,
        mode="topic"
    ))
    assert attempt_res1.correct is False

    # Check card was created/boosted
    conn = get_db_connection()
    cards_found = conn.execute(
        "SELECT id FROM cards WHERE source_question_id = ?",
        (q_id,)
    ).fetchall()
    assert len(cards_found) == 1, "Expected exactly 1 card created for source_question_id"
    card_id = cards_found[0]["id"]

    state_row = conn.execute(
        "SELECT due_date, lapses FROM card_state WHERE card_id = ? AND user_id = ?",
        (card_id, user_id)
    ).fetchone()
    assert state_row is not None
    assert state_row["due_date"] == srs.get_today()
    assert state_row["lapses"] == 1
    conn.close()

    # Submit wrong quiz attempt #2 (repeat)
    attempt_res2 = submit_attempt(AttemptRequest(
        user_id=user_id,
        question_id=q_id,
        chosen_index=wrong_chosen_idx,
        mode="topic"
    ))
    assert attempt_res2.correct is False

    conn = get_db_connection()
    cards_found2 = conn.execute(
        "SELECT id FROM cards WHERE source_question_id = ?",
        (q_id,)
    ).fetchall()
    assert len(cards_found2) == 1, "Duplicate card created on repeat wrong attempt!"

    state_row2 = conn.execute(
        "SELECT lapses FROM card_state WHERE card_id = ? AND user_id = ?",
        (card_id, user_id)
    ).fetchone()
    assert state_row2["lapses"] == 2
    conn.close()
