# Smart Quiz Builder

Topic quizzes and practice mocks for Azure revision. Questions are generated from course notes **once** by an LLM, validated with code, stored in SQLite, and then sampled randomly in every session. Sessions never call the LLM.

---

## 1. Purpose and scope

| In scope | Out of scope (for the hackathon) |
|---|---|
| Topic quizzes (random sample from the question bank) | Per-session LLM generation |
| Practice mock (stratified across topics, mixed with hand-written questions) | Item Response Theory or any ML model |
| Diagnostic quiz (used by the Readiness Tracker on day 1) | Timed exam proctoring |
| Wrong answers resurface more often | User login |
| Recording every attempt for other components | |

---

## 2. Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| When to call the LLM | Once per chunk, at upload time, via an offline script | Zero runtime cost and no live-demo dependency |
| Where questions live | SQLite `questions` table | Fast random sampling, easy to inspect |
| Quality control | Pydantic schema + grounding check + duplicate check | Catches malformed and hallucinated questions without a second model call |
| Variety per session | Random sample + shuffled options | Different quiz every time from the same bank |
| Mock style | 2-3 real mock questions passed as few-shot examples; `is_mock` flag separates hand-written ones | Generated questions match the real exam style |
| Answer checking | Server-side (`POST /api/quiz/attempt`) | Correct answers are not exposed in the page source, and the attempt is recorded in the same call |
| User identity | `user_id` string stored in `localStorage` | No auth needed for the demo |

---

## 3. Data flow

```
ONE-TIME (offline script)
  notes (PDF/DOCX/TXT) -> extract text -> split by headings into chunks
     -> per chunk: LLM call (prompt + few-shot mock examples)
     -> parse JSON -> VALIDATE -> insert into questions (tagged by topic)

EVERY SESSION (no LLM)
  user picks topic -> GET /api/quiz -> weighted random sample, options shuffled
     -> user answers -> POST /api/quiz/attempt -> correct? + explanation
     -> attempt saved -> score screen
```

---

## 4. Data model

```sql
CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY,            -- e.g. 'storage', 'networking'
  name TEXT NOT NULL,
  weight REAL DEFAULT 1.0         -- exam weight, used by Readiness Tracker
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_name TEXT,
  topic_id TEXT REFERENCES topics(id),
  text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chunk_id INTEGER REFERENCES chunks(id),
  topic_id TEXT REFERENCES topics(id),
  question TEXT NOT NULL UNIQUE,
  options_json TEXT NOT NULL,     -- JSON array of 4 strings
  answer_index INTEGER NOT NULL,  -- 0..3
  explanation TEXT,
  source_quote TEXT,
  is_mock INTEGER DEFAULT 0,      -- 1 = hand-written mock question
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  question_id INTEGER REFERENCES questions(id),
  topic_id TEXT,
  correct INTEGER NOT NULL,       -- 0 or 1
  mode TEXT,                      -- 'topic' | 'mock' | 'diagnostic'
  answered_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attempts_user_topic ON attempts(user_id, topic_id);
```

---

## 5. Generation pipeline (`backend/generate/make_quiz.py`)

### Steps

1. Read files from `data/notes/` (`pypdf` for PDF, `python-docx` for Word, plain read for TXT).
2. Split by headings (or every ~500 words if there are none). Save each piece to `chunks` with a `topic_id`.
3. For each chunk, call the LLM with the prompt below.
4. Validate. Insert the questions that pass. Retry a chunk once on failure, then skip it and log it.

### Prompt

```
Create 5 multiple-choice questions from the text below.
Match the style and difficulty of these examples: {mock_examples_json}
Return ONLY a JSON array. Each item:
{"question": str, "options": [4 strings], "answer_index": 0-3,
 "explanation": str, "source_quote": str}
Rules:
- Exactly one option is correct; distractors must be plausible.
- source_quote must be copied verbatim from the text.
- Only ask about facts stated in the text.

TEXT:
{chunk_text}
```

### Validation (`backend/llm.py`)

```python
import re
from pydantic import BaseModel, Field, field_validator

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()

class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=10)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str
    source_quote: str

    @field_validator("options")
    @classmethod
    def options_distinct(cls, v):
        if len({norm(o) for o in v}) != 4:
            raise ValueError("options must be distinct")
        return v

def is_grounded(q: GeneratedQuestion, chunk_text: str) -> bool:
    return norm(q.source_quote) in norm(chunk_text)
```

Checks applied to every generated question:

| Check | Done by |
|---|---|
| Valid JSON with all fields | Pydantic |
| Exactly 4 distinct options, answer index 0-3 | Pydantic validator |
| `source_quote` really appears in the chunk | `is_grounded()` |
| Not a duplicate | `UNIQUE(question)` plus a lowercase comparison before insert |

---

## 6. API contract

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/topics` | List topics (used by all components) |
| GET | `/api/quiz?topic=<id>&n=10&user_id=<id>` | Weighted random sample, options shuffled, **no answers in the response** |
| GET | `/api/mock?n=20&user_id=<id>` | Stratified sample across topics, includes `is_mock` questions |
| GET | `/api/quiz/diagnostic?n=12` | Sample across all topics for the cold-start diagnostic |
| POST | `/api/quiz/attempt` | Body `{user_id, question_id, chosen_index, mode}`. Returns `{correct, answer_index, explanation}` |

### Sampling with resurfacing

```python
import random, json

def sample_questions(conn, topic_id, user_id, n=10):
    rows = conn.execute("SELECT * FROM questions WHERE topic_id = ?", (topic_id,)).fetchall()
    wrong = {r["question_id"] for r in conn.execute(
        """SELECT question_id FROM attempts
           WHERE user_id = ? AND correct = 0
           AND answered_at >= datetime('now', '-14 days')""", (user_id,))}
    weights = [3.0 if r["id"] in wrong else 1.0 for r in rows]   # wrong answers 3x as likely
    picked, pool, w = [], rows[:], weights[:]
    for _ in range(min(n, len(pool))):
        i = random.choices(range(len(pool)), weights=w)[0]
        picked.append(pool.pop(i)); w.pop(i)
    return picked
```

Before returning, shuffle each question's options and **map back** the correct index on the server (or store the chosen text rather than the index) so the check stays correct.

### Mock composition

- 70% new questions from the bank, 30% previously seen or previously wrong.
- Spread evenly across topics, or by `topics.weight`.
- Always include hand-written `is_mock = 1` questions.

---

## 7. Frontend (`quiz.html`, `js/quiz.js`)

Screens: **topic picker**, **question card** (one at a time, progress bar), **feedback** (right/wrong plus explanation), **score summary** (per-topic breakdown, "Retry wrong ones" button).

```javascript
// js/api.js (shared by every page)
export const userId = localStorage.getItem("uid") ||
  (localStorage.setItem("uid", crypto.randomUUID()), localStorage.getItem("uid"));
export const get = (url) => fetch(url).then(r => r.json());
export const post = (url, body) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
               body: JSON.stringify(body) }).then(r => r.json());
```

```javascript
// js/quiz.js (core loop)
const questions = await get(`/api/quiz?topic=${topic}&n=10&user_id=${userId}`);
// render questions[i]; on option click:
const result = await post("/api/quiz/attempt",
  { user_id: userId, question_id: q.id, chosen_index, mode: "topic" });
// show result.correct and result.explanation, then go to the next question
```

---

## 8. How it plugs into the other components

| Component | Connection |
|---|---|
| **Flash Cards Coach** | After a wrong answer, `quiz/attempt` calls `srs.boost_card_for_question(question_id, user_id)`. This makes the related card due today, or creates it from the question's explanation |
| **Readiness Tracker** | Reads `attempts` for per-topic quiz accuracy and recency. Calls `/api/quiz/diagnostic` on day 1 and `/api/mock` on mock days |
| **Azure Explainer Bot** | The explainer's "Practice this topic" button links to `quiz.html?topic=<id>` |
| **Shared** | `topics` table, `db.py`, `api.js` |

---

## 9. Build checklist

- [ ] `db.py` creates the tables; seed 3 topics and 10 hand-written questions
- [ ] `GET /api/quiz` and `POST /api/quiz/attempt` working (test in `/docs`)
- [ ] Quiz UI with feedback and score screen
- [ ] Resurfacing weights and the mock endpoint
- [ ] `make_quiz.py` with validation, then run it on the real notes
- [ ] Diagnostic endpoint
- [ ] Hook the wrong-answer call to the flashcard boost

## 10. Testing

- Unit-test `GeneratedQuestion` with bad data (3 options, duplicate options, index 4, missing quote).
- Unit-test `is_grounded()` with extra whitespace and different casing.
- Manually check 20 generated questions against the notes before the demo.
- Confirm that the same topic gives different questions on consecutive requests.

## 11. Risks

| Risk | Mitigation |
|---|---|
| LLM returns invalid JSON | Strip code fences, parse in try/except, retry once, skip and log |
| Wrong or ungrounded answers | Grounding check plus a manual spot check of a sample |
| Too few questions for a topic | Log counts per topic after generation; generate more or add hand-written ones |
| Shuffled options break the answer index | Test the shuffle-and-check path explicitly |
| API key exposed | Key only in `.env` on the server; the browser never calls the LLM |
