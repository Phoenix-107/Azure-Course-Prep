# Readiness Tracker Dashboard

A dashboard that scores how prepared a student is, then builds an adaptive daily study plan from that score and the exam date. It is **rule-based and explainable**: no ML, no runtime LLM cost. An LLM is optional and only used to word the coach note.

---

## 1. Purpose and scope

| In scope | Out of scope (for the hackathon) |
|---|---|
| Per-topic and overall readiness score | Predictive ML models |
| Study mode: Intensive, Steady, Polish | Calendar integrations and notifications |
| Daily plan generated from readiness and exam date | Multiple simultaneous exams (listed as an extension) |
| Cold-start diagnostic for users with no history | Login |
| Replanning after every session | |
| Chart.js dashboard | |

---

## 2. Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| How readiness is computed | Weighted formula in Python (`backend/readiness.py`) | Transparent, free, easy to explain to judges |
| Data sources | Reuse `attempts`, `card_state`, `review_log` | No new tracking code |
| Unknown topics | `None` ("unknown"), treated as 0 only inside the planner | Distinguishes "weak" from "not started" |
| Mode selection | Pressure ratio = work needed / time available | Gives a tight plan to unprepared users and a relaxed, pinpoint plan to prepared ones |
| Plan freshness | Recomputed on request (each page load and after each session) | Plan always reflects current readiness |
| LLM use | Optional coach note only; code does all the maths | Keeps numbers correct and cost near zero |

---

## 3. Data flow

```
SETUP
  user enters exam date, daily minutes, target -> POST /api/exams

ANY TIME THE DASHBOARD LOADS
  GET /api/readiness
     -> read attempts, card_state, review_log
     -> per-topic readiness (0-100 or null) -> overall readiness
  GET /api/plan/today
     -> pressure ratio -> mode
     -> allocate today's minutes: due cards -> weak topics -> new topics -> mock
     -> save to study_plan, return checklist + coach note

AFTER A STUDY SESSION
  quiz or flashcards finished -> dashboard refetches -> plan updates
```

---

## 4. Data model (additions)

```sql
CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  course TEXT,
  exam_date TEXT NOT NULL,            -- YYYY-MM-DD
  target_score INTEGER DEFAULT 85,
  daily_minutes INTEGER DEFAULT 45
);

CREATE TABLE IF NOT EXISTS study_plan (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  plan_date TEXT NOT NULL,
  activity TEXT NOT NULL,             -- 'flashcards' | 'quiz' | 'mock' | 'diagnostic' | 'review'
  topic_id TEXT,
  minutes INTEGER,
  done INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS readiness_snapshots (   -- powers trend line and weekly delta
  user_id TEXT, snap_date TEXT, overall REAL,
  PRIMARY KEY (user_id, snap_date)
);
```

Per-topic readiness is **computed on the fly** (a function or SQL view), so there is no `topic_readiness` table to keep in sync. Save one snapshot per day for the trend line.

---

## 5. Readiness formulas (`backend/readiness.py`)

### Per-topic signals

| Signal | Definition |
|---|---|
| `quiz_accuracy` | Weighted share of correct answers, latest 10 attempts, recent ones weighted more (0-1). `None` if no attempts |
| `card_mastery` | (Cards with interval >= 21 days - cards with high lapses) / total cards, clamped to 0-1. `None` if no cards started |
| `recency_factor` | `max(0, 1 - days_since_last_activity / 14)` |

```python
def topic_readiness(quiz_acc, card_mastery, recency):
    parts, weights = [], []
    if quiz_acc is not None:     parts.append(quiz_acc);     weights.append(0.45)
    if card_mastery is not None: parts.append(card_mastery); weights.append(0.35)
    if not parts:
        return None                                  # unknown, not zero
    parts.append(recency); weights.append(0.20)
    return round(100 * sum(p * w for p, w in zip(parts, weights)) / sum(weights), 1)
```

Normalising by the weights that exist means a topic with only quiz data is not unfairly penalised for having no cards yet.

### Overall

```python
def overall(topics):                      # topics: [{readiness, weight}]
    known = [t for t in topics if t["readiness"] is not None]
    if not known: return None
    return sum(t["readiness"] * t["weight"] for t in known) / sum(t["weight"] for t in known)
```

---

## 6. Mode selection

```python
TARGET = 85
MIN_PER_POINT = 3

def pressure(topics, days_left, daily_minutes):
    needed = sum(max(0, TARGET - (t["readiness"] or 0)) * t["weight"] * MIN_PER_POINT
                 for t in topics)
    available = max(1, days_left) * daily_minutes
    return needed / available

def choose_mode(p, has_activity):
    if not has_activity or p > 1.0: return "intensive"
    if p >= 0.5:                    return "steady"
    return "polish"
```

| Mode | Plan style |
|---|---|
| **Intensive** (pressure > 1.0, or no activity) | Every day full, all topics, daily quiz plus cards, mock every 3-4 days |
| **Steady** (0.5 - 1.0) | Focus on topics under 60, lighter on the rest, weekly mock |
| **Polish** (< 0.5) | 2-3 weakest topics only, due cards, short sessions, mock every 5-7 days |

---

## 7. Cold start

1. User registers and sets an exam: no data, so mode = Intensive.
2. Day 1 plan = one **diagnostic**: `GET /api/quiz/diagnostic` (10-15 questions across all topics).
3. After the diagnostic, readiness exists, so the mode is recomputed. A student who already knows the material moves straight to Steady or Polish.

---

## 8. Daily plan generator

Priority order for today's minutes:

1. **Due flashcards** (count from the Flash Cards Coach; about 25 seconds per card, capped at 40% of the day).
2. **Weak-topic quizzes**, minutes split in proportion to `gap x weight`.
3. **New or uncovered topics** (Intensive and Steady only).
4. **Mock exam** on scheduled days.
5. **Taper**: in the last 48 hours, review only, no new material.

```python
def build_day_plan(topics, daily_minutes, mode, due_cards, days_left):
    plan, left = [], daily_minutes
    if days_left <= 2:                                   # taper
        return [{"activity": "review", "minutes": daily_minutes}]
    if due_cards:
        card_min = min(-(-due_cards * 25 // 60), int(left * 0.4))
        plan.append({"activity": "flashcards", "minutes": card_min, "count": due_cards})
        left -= card_min
    limit = {"polish": 3, "steady": 5}.get(mode, len(topics))
    weak = sorted(({**t, "gap": max(0, TARGET - (t["readiness"] or 0)) * t["weight"]}
                   for t in topics), key=lambda t: t["gap"], reverse=True)
    weak = [t for t in weak if t["gap"] > 0][:limit]
    total = sum(t["gap"] for t in weak) or 1
    for t in weak:
        plan.append({"activity": "quiz", "topic_id": t["id"],
                     "minutes": max(5, round(left * t["gap"] / total))})
    return plan
```

Mock days: add `{"activity": "mock", "minutes": 40}` when `days_since_last_mock` reaches the interval for the current mode.

### Coach note (template, LLM optional)

```python
def coach_note(mode, days_left, overall_score, weakest):
    if mode == "intensive":
        return f"{days_left} days left and readiness at {overall_score:.0f}%. Full days ahead, starting with {weakest[0]}."
    if mode == "steady":
        return f"You are on track. Focus on {', '.join(weakest[:2])} this week."
    return f"You are ahead of schedule, so today is light. A short session on {weakest[0]} is enough."
```

Optional upgrade: send the same numbers to the LLM and ask for a 3-sentence encouraging note with "do not change the numbers".

---

## 9. API contract

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/exams` | Save exam date, daily minutes, target |
| GET | `/api/readiness?user_id=` | `{overall, delta_7d, mode, days_left, topics:[{id, name, readiness}]}` |
| GET | `/api/plan/today?user_id=` | `{mode, minutes_total, items:[...], coach_note}` |
| POST | `/api/plan/{id}/done` | Mark an item complete |
| GET | `/api/readiness/trend?user_id=` | Snapshots plus projected readiness on exam day (linear fit) |

---

## 10. Dashboard layout (`dashboard.html`, `js/dashboard.js`)

1. **Header:** exam countdown and a mode badge.
2. **Readiness gauge:** overall score and weekly delta (Chart.js doughnut).
3. **Topic bars:** red under 50, amber 50-75, green above 75, grey for unknown. Click a topic to open `quiz.html?topic=<id>` or `flashcards.html?topic=<id>`.
4. **Today's plan:** checklist with minutes per item and a total.
5. **Coach note:** a short message explaining why today looks the way it does.
6. **Trend line:** snapshots over time with a dashed projection to exam day.

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

---

## 11. How it plugs into the other components

| Component | What the tracker takes or gives |
|---|---|
| **Smart Quiz Builder** | Reads `attempts`; links to topic quizzes, the diagnostic and the mock endpoint |
| **Flash Cards Coach** | Reads `card_state` and `review_log`; gets the due count; owns the `exams` table that the card scheduler uses for its exam cap |
| **Azure Explainer Bot** | Optional: count "explainer completed" as coverage, and recommend explainers for topics under 40 ("Start with the explainer") |
| **Shared** | `topics` table (with `weight`), `api.js` |

---

## 12. Build checklist

- [x] Topic readiness bar chart and gauge
- [x] `topic_readiness()` with unit tests
- [x] Exam setup form and `/api/exams`
- [x] `pressure()` and `choose_mode()`
- [x] `build_day_plan()` and the persisted plan checklist
- [x] Connect to real `attempts` and `card_state`
- [x] Diagnostic plan for new users
- [x] Daily snapshot, trend line, and exam-day projection
- [x] Coach note (template first)

## 13. Testing scenarios

| Scenario | Expected result |
|---|---|
| New user, no data | Mode Intensive, plan = diagnostic |
| After diagnostic with 90% accuracy, 20 days left | Mode Polish, 2-3 topics, short plan |
| 3 days left, readiness 40 | Intensive; taper rule applies in the last 2 days |
| User skips a week | Pressure rises; mode moves up; banner explains |
| Topic with quiz data only | Readiness computed from quiz and recency, not penalised for no cards |

## 14. Risks

| Risk | Mitigation |
|---|---|
| Formula feels arbitrary | Show the inputs on the dashboard ("Quiz 70%, Cards 40%") and keep the constants in one config block |
| Too little data early on | Show "based on N answers" and mark low-confidence topics |
| Plan overload | Cap total minutes to `daily_minutes`; flashcards at most 40% |
| Circular dependency between components | Tracker only **reads** other tables; it writes only `exams`, `study_plan`, snapshots |
