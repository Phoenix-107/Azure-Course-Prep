# Azure Explainer Bot (AI Study Buddy)

A guided, topic-by-topic bot that explains Azure concepts in plain language using everyday African scenarios (school, market, small business). It is **not** an open-ended chatbot: explanations are generated once offline, reviewed by a human, and served as static JSON. A small optional endpoint answers follow-up questions about the current topic.

---

## 1. Purpose and scope

| In scope | Out of scope (for the hackathon) |
|---|---|
| Topic menu and one structured explanation card per topic | Free-form chat across all of Azure |
| Chat-bubble presentation of each card | Vector search or RAG |
| Quick-check question per topic | Conversation memory |
| Optional "Ask a question" limited to the current topic | Voice |
| Progress tracking in the browser | Accounts |
| Optional "Explain it differently" (cached) | Full Swahili translation (future work) |

---

## 2. Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| Interaction style | Topic menu, then explanation card, then optional follow-up | Beginners never face a blank text box |
| Content source | LLM drafts offline, human reviews, stored in `data/topics.json` | Zero runtime cost, accuracy under our control |
| Runtime dependency | None for core content | Works even if the API or Wi-Fi fails on demo day |
| Persona | Friendly tutor (for example "Mwalimu Cloud") | Gives the "bot" feel with no extra engineering |
| Accuracy guard | Allowed-services whitelist, no prices or limits, "where the analogy breaks" section | Prevents invented products and misleading analogies |
| Follow-up chat | One constrained endpoint with the topic card as context | Keeps answers on topic and cheap |
| Progress | `localStorage` | No backend state needed |

---

## 3. Data flow

```
OFFLINE (once)
  topic list -> LLM per topic -> JSON card -> validate -> human review -> data/topics.json

RUNTIME (core, no LLM)
  open bot -> topic menu -> pick topic
     -> load card from topics.json -> render bubbles with short delays:
        1. one sentence   2. story   3. mapping table
        4. where the analogy breaks + real Azure services
        5. quick check -> feedback
     -> buttons: [Next topic] [Practice this topic] [Explain differently] [Ask a question]

RUNTIME (optional, uses LLM)
  Ask a question -> POST /api/ask {topic_id, question}
     -> backend sends card + question to LLM -> short answer
```

---

## 4. Concept-to-scenario map (the core content)

Define this first. Each row seeds one topic.

| Azure concept | Scenario | Where the analogy fits |
|---|---|---|
| Cloud basics | Renting instead of owning | No upfront cost, shared infrastructure |
| Virtual Machine | Renting a stall at a market instead of building a shop | You get space and run your business there |
| Blob Storage | School records room with labelled boxes | Cheap, large file storage |
| Scalability / autoscale | A shop that hires helpers on market day and sends them home after | Pay for capacity only when needed |
| Regions / availability zones | A business with branches in different towns | Redundancy and resilience |
| Pay-as-you-go pricing | Prepaid electricity tokens | Pay for what you use |
| Identity and roles (Entra ID / RBAC) | Headteacher, teacher and student hold different keys | Least-privilege access |
| Virtual Network and firewall | School compound with a gate and a watchman | Controlled entry |
| Serverless (Azure Functions) | A mobile-money agent paid per transaction | Code runs only when triggered |
| Database | School register or shopkeeper's ledger | Organised, searchable records |
| Backup and recovery | Copy of exam results at the district office | Recovery if the original is lost |
| Monitoring | Owner checks the till and stock each evening | Visibility into what is happening |
| Shared responsibility | Landlord secures the building, tenant locks the shop | Provider and customer split security duties |

Vary examples across regions (mobile money, SACCOs, matatu stages, boda boda, market-day traders, school fee systems) so it does not feel tied to one country.

---

## 5. Card template and data

Every card has the same six parts: one-sentence definition, story (5-7 simple sentences), mapping table, where the analogy breaks, real Azure service names, quick check.

```json
{
  "id": "autoscale",
  "title": "Scalability and Autoscale",
  "level": "beginner",
  "last_reviewed": "2026-10-22",
  "scenario_hint": "market-day traders hiring temporary helpers",
  "azure_services": ["Virtual Machine Scale Sets", "App Service autoscale"],
  "card": {
    "one_sentence": "...",
    "story": "...",
    "mapping": [{ "story_item": "Extra helpers", "azure_item": "Extra instances" }],
    "analogy_limit": "...",
    "quick_check": { "question": "...", "options": ["...", "...", "..."], "answer_index": 1 }
  }
}
```

Use the same `id` as the matching row in the `topics` table when one exists, so the "Practice this topic" button works.

---

## 6. Generation pipeline (`backend/generate/make_topics.py`)

Prompt (run once per topic):

```
You are a friendly tutor explaining Azure to complete beginners in Africa.
Topic: {title}. Scenario hint: {scenario_hint}.

Return ONLY JSON with:
one_sentence, story (5-7 simple sentences), mapping [{story_item, azure_item}],
analogy_limit, azure_services [], quick_check {question, options[3], answer_index}.

Rules:
- Plain English, short sentences, no unexplained acronyms.
- Respectful, realistic everyday setting (school, market or small business).
- Avoid stereotypes; people in the story are capable business owners and teachers.
- Use only accurate Azure service names from this list: {allowed_services}.
- Do not mention prices or specific limits.
```

### Validation

```python
ALLOWED_SERVICES = {"Azure Virtual Machines", "Azure Blob Storage", "Azure Functions",
                    "Virtual Machine Scale Sets", "Microsoft Entra ID", "Azure Monitor",
                    "Azure Backup", "Azure SQL Database", "Azure Virtual Network"}  # extend and verify on Microsoft Learn

def validate_card(card: dict) -> list[str]:
    errors = []
    for field in ("one_sentence", "story", "mapping", "analogy_limit", "azure_services", "quick_check"):
        if field not in card: errors.append(f"missing {field}")
    if any(s not in ALLOWED_SERVICES for s in card.get("azure_services", [])):
        errors.append("service not in whitelist")
    qc = card.get("quick_check", {})
    if not (0 <= qc.get("answer_index", -1) < len(qc.get("options", []))):
        errors.append("bad answer_index")
    sentences = [s for s in card.get("story", "").split(".") if s.strip()]
    if not 5 <= len(sentences) <= 8: errors.append("story length")
    if any(len(s.split()) > 25 for s in sentences): errors.append("long sentence")
    return errors
```

**Human review is mandatory.** With 12-15 topics, read every card and compare it to Microsoft Learn's AZ-900 material before setting `last_reviewed`.

---

## 7. Backend

Static content needs no route if FastAPI serves `data/` (or copy `topics.json` into `frontend/`).

```python
# backend/main.py (optional follow-up route)
from pydantic import BaseModel

class Ask(BaseModel):
    topic_id: str
    question: str

@app.post("/api/ask")
def ask(body: Ask):
    card = TOPICS[body.topic_id]                       # loaded from topics.json at startup
    r = client.messages.create(
        model="claude-haiku-5-5", max_tokens=400,
        system=("You are a friendly Azure tutor for beginners. Answer ONLY about this topic, "
                "using simple words and an everyday African example. If the question is off-topic, "
                f"say so politely. Topic card: {card}"),
        messages=[{"role": "user", "content": body.question[:500]}],
    )
    return {"answer": r.content[0].text}
```

Safeguards: cap question length, cap `max_tokens`, optionally limit requests per user per day, and wrap the call in try/except so the UI shows "The tutor is resting, try again" on failure.

---

## 8. Frontend (`explainer.html`, `js/chat.js`)

Render the card as a sequence of chat bubbles with a short typing delay:

```javascript
import { get } from "./api.js";

const topics = await get("/data/topics.json");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function showTopic(id) {
  const t = topics.find(x => x.id === id).card;
  await bubble(t.one_sentence);
  await bubble(t.story);
  await bubble(mappingTable(t.mapping));
  await bubble(`Where this breaks: ${t.analogy_limit}`);
  quickCheck(t.quick_check, id);
}

async function bubble(content) {
  const el = addBubble("typing...");
  await sleep(600);
  el.innerHTML = content;
}
```

Quick-check feedback: highlight the chosen option, show correct or incorrect, then store `{topicId, passed}` in `localStorage`. Buttons after the card: **Next topic**, **Practice this topic** (`quiz.html?topic=<id>`), **Explain differently**, **Ask a question**.

"Explain differently": one LLM call with `{topic_id, scenario: "school" | "market" | "business"}`, cached in a dict or JSON file per pair so it is never regenerated.

---

## 9. How it plugs into the other components

| Component | Connection |
|---|---|
| **Smart Quiz Builder** | "Practice this topic" opens the quiz for the same topic id |
| **Flash Cards Coach** | Optional "Add to flashcards" on the one-sentence bubble inserts a card for the concept |
| **Readiness Tracker** | Optional: send "explainer completed" as a coverage signal, and recommend the explainer for topics under 40 |
| **Shared** | `topics` ids, `api.js`, the same FastAPI app serving `frontend/` and `data/` |

The explainer is the **most independent** component: it can ship on its own, so build it early if you need a safe demo fallback.

---

## 10. Build checklist

- [ ] Choose 6 core topics (cloud basics, VM, storage, scaling, identity, pricing)
- [ ] Hand-write one card and build the bubble UI around it
- [ ] Topic menu and "Next topic" navigation
- [ ] Run `make_topics.py` for all topics, validate, review by hand
- [ ] Quick-check feedback and `localStorage` progress
- [ ] "Practice this topic" link into the quiz
- [ ] `/api/ask` with guardrails
- [ ] "Explain differently" with caching
- [ ] Add the remaining topics

## 11. Testing

- Every card passes `validate_card()`.
- Every Azure service name matches Microsoft Learn.
- Reading-level check: a non-technical friend can follow each story.
- Ask three off-topic questions and confirm the bot politely declines.
- Turn off the network: the menu and all cards still work.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Analogy teaches a wrong idea | "Where it breaks" section and human review |
| Hallucinated Azure services or features | Whitelist; avoid prices and limits |
| Stereotyped portrayal | Prompt rules; portray capable, modern businesses (mobile money, e-commerce, SACCOs) |
| Outdated Azure names | `last_reviewed` on each card; re-check against Microsoft Learn |
| API failure on demo day | Core content is static JSON; follow-up chat is optional |
