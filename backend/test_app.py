"""
Integration verification test script using Python requests and threading.
"""

import time
import threading
import requests
import uvicorn
from backend.main import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")

def run_tests():
    # Start uvicorn server on port 8001 in background daemon thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1.5)  # Wait for server to bind

    base_url = "http://127.0.0.1:8001"
    
    print("--- 1. Testing GET /api/topics ---")
    res = requests.get(f"{base_url}/api/topics")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    topics = res.json()
    assert len(topics) >= 3, f"Expected >= 3 topics, got {len(topics)}"
    print(f"Passed: Found {len(topics)} topics:")
    for t in topics:
        print(f"  - {t['id']}: {t['name']} ({t['question_count']} questions)")

    print("\n--- 2. Testing GET /api/quiz with security verification ---")
    user_id = "test-scholar-001"
    res = requests.get(f"{base_url}/api/quiz?topic=cloud-concepts&n=2&user_id={user_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    questions = res.json()
    assert len(questions) == 2, f"Expected 2 questions, got {len(questions)}"
    for q in questions:
        assert "answer_index" not in q, "SECURITY FAILED: answer_index exposed in client quiz response!"
        assert "source_quote" not in q, "source_quote exposed in client quiz response!"
        assert len(q["options"]) == 4, f"Expected 4 options, got {len(q['options'])}"
        print(f"  - Question ID {q['id']}: {q['question'][:60]}... Options: {len(q['options'])}")

    print("\n--- 3. Testing POST /api/quiz/attempt ---")
    first_q = questions[0]
    attempt_payload = {
        "user_id": user_id,
        "question_id": first_q["id"],
        "chosen_index": 0,
        "mode": "topic"
    }
    res = requests.post(f"{base_url}/api/quiz/attempt", json=attempt_payload)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    attempt_res = res.json()
    assert "correct" in attempt_res
    assert "correct_index" in attempt_res
    assert "explanation" in attempt_res
    print(f"  - Attempt Result: correct={attempt_res['correct']}, correct_index={attempt_res['correct_index']}")
    print(f"  - Explanation: {attempt_res['explanation'][:80]}...")

    print("\n--- 4. Testing GET /api/dashboard/stats ---")
    res = requests.get(f"{base_url}/api/dashboard/stats?user_id={user_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    stats = res.json()
    assert stats["total_questions_attempted"] >= 1
    assert "overall_readiness" in stats
    assert "topics" in stats
    print(f"  - Total Attempted: {stats['total_questions_attempted']}")
    print(f"  - Accuracy: {stats['overall_accuracy']}%")
    print(f"  - Overall Readiness: {stats['overall_readiness']}%")
    print(f"  - Weakest Topic: {stats['weakest_topic']['name'] if stats['weakest_topic'] else 'None'}")

    print("\n--- 5. Testing Static Page Serves ---")
    dash_res = requests.get(f"{base_url}/dashboard")
    assert dash_res.status_code == 200
    assert "Azure Scholar" in dash_res.text

    quiz_res = requests.get(f"{base_url}/quiz")
    assert quiz_res.status_code == 200
    assert "Smart Quiz" in quiz_res.text

    flash_res = requests.get(f"{base_url}/flashcards")
    assert flash_res.status_code == 200
    assert "Flashcards Coach" in flash_res.text

    css_res = requests.get(f"{base_url}/static/css/styles.css")
    assert css_res.status_code == 200
    assert "--azure-primary" in css_res.text

    print("\nALL BACKEND AND FRONTEND INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
