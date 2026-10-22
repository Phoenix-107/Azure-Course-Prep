# Flash Cards Coach

Spaced-repetition flashcards for Azure revision. Cards are generated from notes once, validated, and scheduled per user with the SM-2 algorithm. The "coach" part adds a daily plan, weak-topic signals and an exam-aware interval cap.

---

## 1. Purpose and scope

| In scope | Out of scope (for the hackathon) |
|---|---|
| Flip-card review loop with four ratings (Again, Hard, Good, Easy) | FSRS (listed as future work) |
| SM-2 scheduling with an exam-date cap | Images, audio, deck sharing |
| Daily new-card limit and a "due today" queue | Mobile app |
| Review summary and streak | User accounts |
| Auto-boost of cards when a quiz answer is wrong | |

---

## 2. Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| Scheduling algorithm | SM-2 in Python (`backend/srs.py`) | About 20 lines, proven, no ML needed |
| Content vs progress | `cards` (shared content) separate from `card_state` (per-user progress) | Many users share one deck |
| Where scheduling runs | Backend only | One source of truth; the dashboard reads the same data |
| Card generation | Offline LLM script, same pipeline and validation as quiz | Reuses what we already built |
| Card style rules | One fact per card, back under 15 words, optional cloze | Good cards matter as much as the algorithm |
| Exam awareness | Cap interval so a card is always due before the exam | Makes the app purpose-built for course revision |

---

## 3. Data flow

```
OFFLINE
  chunks -> LLM (flashcard prompt) -> validate -> insert into cards

REVIEW SESSION
  GET /api/cards/due  -> due cards + up to N new cards
  user sees front -> Show answer -> rates 0-3
  POST /api/cards/review -> srs.review() updates card_state + review_log
  next card -> ... -> summary screen

CROSS-COMPONENT
  quiz answered wrong -> srs.boost_card_for_question() -> card due today
  readiness tracker  -> reads card_state + review_log
```

---

## 4. Data model

```sql
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id TEXT REFERENCES topics(id),
  front TEXT NOT NULL UNIQUE,
  back TEXT NOT NULL,
  type TEXT DEFAULT 'basic',          -- 'basic' | 'cloze'
  hint TEXT,
  source_chunk_id INTEGER,
  source_question_id INTEGER          -- set when created from a quiz question
);

CREATE TABLE IF NOT EXISTS card_state (
  card_id INTEGER REFERENCES cards(id),
  user_id TEXT NOT NULL,
  ease REAL DEFAULT 2.5,
  interval INTEGER DEFAULT 0,         -- days
  repetitions INTEGER DEFAULT 0,
  due_date TEXT NOT NULL,             -- YYYY-MM-DD
  last_reviewed TEXT,
  lapses INTEGER DEFAULT 0,
  PRIMARY KEY (card_id, user_id)
);

CREATE TABLE IF NOT EXISTS review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER,
  user_id TEXT,
  rating INTEGER,                     -- 0 Again, 1 Hard, 2 Good, 3 Easy
  reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_state_due ON card_state(user_id, due_date);
```

A `card_state` row is created the first time a user meets a card (when it is served as a "new" card).

---

## 5. Scheduling logic (`backend/srs.py`)

```python
from datetime import date, timedelta

def review(state: dict, rating: int, exam_date: date | None = None) -> dict:
    """rating: 0=Again, 1=Hard, 2=Good, 3=Easy"""
    today = date.today()
    if rating == 0:
        state["repetitions"] = 0
        state["interval"] = 1
        state["ease"] = max(1.3, state["ease"] - 0.2)
        state["lapses"] += 1
    else:
        if state["repetitions"] == 0:
            state["interval"] = 1
        elif state["repetitions"] == 1:
            state["interval"] = 3
        else:
            state["interval"] = round(state["interval"] * state["ease"])
        if rating == 1:
            state["ease"] = max(1.3, state["ease"] - 0.15)
        elif rating == 3:
            state["ease"] += 0.15
        state["repetitions"] += 1

    if exam_date:                                   # exam cap
        days_left = (exam_date - today).days
        state["interval"] = max(1, min(state["interval"], days_left - 1))

    state["due_date"] = (today + timedelta(days=state["interval"])).isoformat()
    state["last_reviewed"] = today.isoformat()
    return state

def preview_intervals(state: dict, exam_date=None) -> dict:
    """Used to label the buttons: 'Good - 3d'."""
    return {r: review(dict(state), r, exam_date)["interval"] for r in range(4)}
```

### Boost from a wrong quiz answer

```python
def boost_card_for_question(conn, question_id, user_id):
    card = conn.execute("SELECT id FROM cards WHERE source_question_id = ?", (question_id,)).fetchone()
    if not card:
        q = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        # create a card: front = question, back = correct option text (short)
        # insert into cards, set card.id
    # upsert card_state: due_date = today, lapses = lapses + 1
```

---

## 6. Generation pipeline (`backend/generate/make_cards.py`)

```
Create 5 flashcards from this text.
Return ONLY a JSON array. Each item:
{"front": str, "back": str, "type": "basic" or "cloze", "hint": str, "source_quote": str}
Rules:
- One fact per card.
- Back must be under 15 words.
- Cloze cards use ___ for the hidden term.
- source_quote must be copied verbatim from the text.

TEXT:
{chunk_text}
```

Validation (same pattern as the quiz): Pydantic model, back length under 15 words, `source_quote` found in the chunk, duplicate `front` skipped.

---

## 7. API contract

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/cards/due?user_id=&new_limit=15&topic=` | Due cards first, then new cards up to the daily limit. Each card includes `intervals` for the button labels |
| POST | `/api/cards/review` | Body `{user_id, card_id, rating}`. Updates `card_state`, writes `review_log`, returns the new due date |
| GET | `/api/cards/stats?user_id=` | Due count, reviewed today, accuracy, streak, per-topic lapses |
| GET | `/api/cards/heatmap?user_id=` | Reviews per day for the last 90 days (optional) |

The exam date comes from the `exams` table (owned by the Readiness Tracker). If no exam is set, no cap is applied.

---

## 8. Frontend (`flashcards.html`, `js/cards.js`)

1. Fetch `/api/cards/due`.
2. Show the **front** and a "Show answer" button.
3. On flip, show the **back** and four rating buttons labelled with their next interval.
4. POST the rating and show the next card.
5. End with a summary: cards done, accuracy, tomorrow's due count, streak.

Keyboard shortcuts: `Space` flips, `1`-`4` rate. Header line: "24 cards due, about 8 minutes" (due count x ~25 seconds).

CSS note: a flip animation needs only `transform: rotateY(180deg)` with `transform-style: preserve-3d` and `backface-visibility: hidden`.

---

## 9. How it plugs into the other components

| Component | Connection |
|---|---|
| **Smart Quiz Builder** | A wrong answer calls `boost_card_for_question()`, so quiz mistakes become flashcards due today |
| **Readiness Tracker** | Reads `card_state` for card mastery (share of cards with interval >= 21 days, minus lapses) and `review_log` for consistency. Also supplies the due-card count for the daily plan |
| **Azure Explainer Bot** | Optional: an "Add to flashcards" button on the explainer's "in one sentence" bubble creates a card for that concept |
| **Shared** | `topics` table, `exams` table (exam cap), `api.js` |

---

## 10. Build checklist

- [ ] Create tables; seed 10 hand-written cards
- [ ] Flip-card UI with fake data
- [ ] `srs.review()` plus a unit test table (see below)
- [ ] `/api/cards/due` and `/api/cards/review`
- [ ] Interval labels on buttons and the summary screen
- [ ] Stats endpoint, streak, daily limit
- [ ] `make_cards.py` with validation
- [ ] Exam cap and the quiz boost hook

## 11. Testing

Unit-test `review()` with these cases:

| Start state | Rating | Expected |
|---|---|---|
| new card | Good | interval 1, repetitions 1 |
| repetitions 1 | Good | interval 3 |
| repetitions 2, interval 3, ease 2.5 | Good | interval 8 (rounded from 7.5) |
| any | Again | interval 1, repetitions 0, lapses +1, ease -0.2 |
| ease 1.3 | Hard or Again | ease stays at 1.3 |
| exam in 4 days, computed interval 8 | Good | interval 3 |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Overwhelming card backlog | Daily new-card limit; show "due today" only |
| Poor generated cards | Rules in the prompt, 15-word cap, manual review of a sample |
| Dates and time zones | Store dates as `YYYY-MM-DD` and compare on the server only |
| Heavy duplicate cards from boost | Look up by `source_question_id` before creating |
