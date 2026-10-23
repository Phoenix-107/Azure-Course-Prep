import datetime
from uuid import uuid4

from backend import srs
from backend.cards_router import ExamCreateRequest, create_exam
from backend.db import get_db_connection, init_db
from backend.main import (
    PlanDoneRequest,
    get_plan_today,
    get_readiness,
    get_readiness_trend,
    mark_plan_item_done,
)
from backend.readiness import build_day_plan, overall, pressure, topic_readiness
from backend.seed_cards import seed_cards


def test_topic_readiness_normalizes_available_signals():
    assert topic_readiness(None, None, 1.0) is None
    assert topic_readiness(0.8, None, 0.5) == 70.8
    assert topic_readiness(1.0, 1.0, 1.0) == 100.0
    assert topic_readiness(1.0, 1.0, 2.0) == 100.0


def test_overall_and_study_planning_rules():
    topics = [
        {"readiness": 80.0, "weight": 1.0},
        {"readiness": 60.0, "weight": 2.0},
        {"readiness": None, "weight": 1.0},
    ]
    assert overall(topics) == 66.7
    assert pressure(topics, days_left=20, daily_minutes=45) > 0

    plan = build_day_plan(
        [{"id": "one", "readiness": 20.0, "weight": 1.0}],
        daily_minutes=30,
        mode="intensive",
        due_cards=20,
        days_left=10,
    )
    assert sum(item["minutes"] for item in plan) <= 30
    assert plan[0]["activity"] == "flashcards"
    assert build_day_plan([], 30, "intensive", 4, 2) == [
        {"activity": "review", "minutes": 30}
    ]
    mock_day = build_day_plan(
        [{"id": "one", "readiness": 20.0, "weight": 1.0}],
        daily_minutes=60,
        mode="steady",
        due_cards=0,
        days_left=10,
        days_since_last_mock=7,
    )
    assert sum(item["minutes"] for item in mock_day) <= 60
    assert any(item["activity"] == "mock" for item in mock_day)
    polish_plan = build_day_plan(
        [
            {"id": "known-weak", "readiness": 70.0, "weight": 1.0},
            {"id": "uncovered", "readiness": None, "weight": 1.0},
        ],
        daily_minutes=30,
        mode="polish",
        due_cards=0,
        days_left=10,
    )
    assert [item.get("topic_id") for item in polish_plan] == ["known-weak"]


def test_readiness_tracker_exam_diagnostic_plan_and_snapshots():
    init_db()
    seed_cards()
    srs.reset_day_offset()
    user_id = f"readiness-test-{uuid4().hex}"
    today = datetime.date.fromisoformat(srs.get_today())
    exam_date = today + datetime.timedelta(days=20)

    conn = get_db_connection()
    question = conn.execute("SELECT id, topic_id FROM questions ORDER BY id LIMIT 1").fetchone()
    card = conn.execute(
        "SELECT id FROM cards WHERE topic_id = ? ORDER BY id LIMIT 1",
        (question["topic_id"],),
    ).fetchone()
    conn.close()
    assert card is not None

    try:
        saved_exam = create_exam(ExamCreateRequest(
            user_id=user_id,
            exam_date=exam_date,
            daily_minutes=30,
            target_score=80,
        ))
        assert saved_exam["exam_date"] == exam_date.isoformat()

        cold_start = get_readiness(user_id)
        assert cold_start["mode"] == "intensive"
        assert cold_start["overall"] is None
        assert all(topic["readiness"] is None for topic in cold_start["topics"])

        diagnostic = get_plan_today(user_id)
        assert diagnostic["items"][0]["activity"] == "diagnostic"
        mark_plan_item_done(
            PlanDoneRequest(user_id=user_id),
            diagnostic["items"][0]["id"],
        )
        assert get_plan_today(user_id)["items"][0]["done"] is True

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO attempts (user_id, question_id, topic_id, correct, mode, answered_at)
            VALUES (?, ?, ?, 1, 'diagnostic', ?)
            """,
            (user_id, question["id"], question["topic_id"], f"{today.isoformat()} 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO card_state
                (card_id, user_id, interval, repetitions, due_date, last_reviewed, lapses)
            VALUES (?, ?, 21, 3, ?, ?, 0)
            """,
            (card["id"], user_id, today.isoformat(), today.isoformat()),
        )
        conn.commit()
        conn.close()

        updated = get_readiness(user_id)
        ready_topic = next(topic for topic in updated["topics"] if topic["id"] == question["topic_id"])
        assert ready_topic["quiz_accuracy"] == 100.0
        assert ready_topic["card_mastery"] == 100.0
        assert ready_topic["readiness"] == 100.0
        assert updated["overall"] is not None
        assert len(get_readiness_trend(user_id)["snapshots"]) == 1
    finally:
        conn = get_db_connection()
        conn.execute("DELETE FROM study_plan WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM readiness_snapshots WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM attempts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM card_state WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM exams WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
