# Azure Course Prep

A web app that helps Scholars revise for the Microsoft AZ900 Azure course. It combines four tools in one place:

| Feature | What it does |
|---|---|
| **Topical Quiz** | Random quizzes by topic, plus practice mocks built from a question bank |
| **Flash Cards Coach** | Spaced-repetition flashcards (SM-2) with a daily due list |
| **Readiness Tracker** | Dashboard that scores readiness per topic and builds a study plan from the exam date |
| **Azure Explainer Bot** | Topic-by-topic explanations of Azure concepts using simple African scenarios (school, market, business) |

AI is used only to **pre-generate content** (questions, cards, explanations) and for one optional follow-up chat. Everything else is plain code, so the app is cheap to run and works even if the API is down.

---

## The stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Frontend | HTML, CSS, vanilla JavaScript | What you already know. No framework, no build step |
| Charts | Chart.js (loaded by a `<script>` tag) | Readiness gauge, topic bars and trend line with little code |
| Backend | Python with FastAPI | Beginner-friendly, and Pydantic validates LLM JSON for you |
| Database | SQLite | A single file, no server, free, and enough for a hackathon |
| LLM access | Anthropic Python SDK (or any provider's SDK) | Used in offline generation scripts and one optional chat endpoint |
| Note extraction | `pypdf` (PDF) and `python-docx` (Word) | Pulls text out of uploaded notes before chunking |
| Config and secrets | `python-dotenv` and a `.env` file | Keeps the API key out of your code and out of GitHub |
| Hosting | Render, Railway or PythonAnywhere (free tiers) | FastAPI serves your HTML files too, so there is one deployment |
| Tools | VS Code, Git and GitHub, Live Server, FastAPI's built-in `/docs` page | `/docs` auto-generates a test page for every endpoint |

---

## Project structure

```
azure-prep/
├── backend/
│   ├── main.py            # FastAPI app and routes
│   ├── db.py              # SQLite connection and table setup
│   ├── srs.py             # SM-2 scheduling
│   ├── readiness.py       # readiness score and planner
│   ├── llm.py             # LLM calls and validation
│   └── generate/          # offline scripts: quizzes, cards, explainer topics
├── frontend/
│   ├── index.html
│   ├── quiz.html
│   ├── flashcards.html
│   ├── dashboard.html
│   ├── explainer.html
│   ├── css/styles.css
│   └── js/                # api.js, quiz.js, cards.js, dashboard.js, chat.js
├── data/
│   ├── topics.json        # reviewed Azure explainer cards
│   ├── notes/             # course notes (PDF, DOCX, TXT)
│   └── app.db             # SQLite file (created automatically)
├── requirements.txt
├── .env                   # your API key (never commit this)
├── .env.example
├── .gitignore
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.10 or newer
- Git
- VS Code (with the Live Server extension, optional)
- An LLM API key (only needed for content generation and the optional chat)

### 1. Clone the project

```bash
git clone https://github.com/<your-username>/azure-prep.git
cd azure-prep
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
fastapi
uvicorn
anthropic
pypdf
python-docx
python-dotenv
pydantic
```

### 4. Add your API key

Copy the example file and edit it:

```bash
cp .env.example .env
```

Inside `.env`:

```
ANTHROPIC_API_KEY=your_key_here
```

Make sure `.gitignore` contains:

```
.env
venv/
data/app.db
__pycache__/
```

### 5. Run the app

```bash
uvicorn backend.main:app --reload
```

Open:

- App: http://127.0.0.1:8000
- API test page (auto-generated): http://127.0.0.1:8000/docs

FastAPI serves the files in `frontend/`, so you do not need a second server.

---

## Generating content (offline, run once)

Put your course notes in `data/notes/`, then run the generation scripts to fill the database:

```bash
python -m backend.generate.make_quiz        # MCQs from notes
python -m backend.generate.make_cards       # flashcards from notes
python -m backend.generate.make_topics      # Azure explainer cards
```

Each script chunks the notes, calls the LLM, **validates** the JSON (required fields, answer index in range, no duplicates, `source_quote` found in the source text), and saves the result to SQLite or `data/topics.json`. Review the explainer cards by hand before the demo.

After generation, the app runs without calling the LLM, except for the optional "Ask a question" box.

---

## How it fits together

```
Browser (HTML/CSS/JS)
   │  fetch()
   ▼
FastAPI (Python)  ──►  SQLite  (questions, cards, progress)
   │
   └──► LLM API  (only for generation scripts and optional chat)
```

- The **browser never calls the LLM directly**, so the API key stays on the server.
- Charts on the dashboard use Chart.js via a script tag:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

---

## Deployment

1. Push the project to GitHub (without `.env`).
2. Create a free web service on Render, Railway or PythonAnywhere.
3. Set the start command:
   ```
   uvicorn backend.main:app --host 0.0.0.0 --port $PORT
   ```
4. Add `ANTHROPIC_API_KEY` as an environment variable in the host's dashboard.
5. Commit `data/app.db` with pre-generated content (or run the generation scripts on the server) so the demo has data.

---

## Notes and limitations

- No login system. Progress is tied to a simple name or session ID.
- SM-2 is used for flashcards. FSRS could replace it later.
- Azure service names and features change, so each explainer card should carry a "last reviewed" date and be checked against Microsoft Learn.
- Analogies are simplifications. Each explainer card includes a "where the analogy breaks" section.

## Build order

1. Folder structure, a FastAPI hello route, and a static `index.html`
2. SQLite tables and hand-written sample questions and cards
3. Quiz and flashcard pages with their endpoints
4. Readiness calculation and Chart.js dashboard
5. Explainer bot from a hand-written `topics.json`
6. LLM generation scripts and content fill

## License

MIT (or your choice)
