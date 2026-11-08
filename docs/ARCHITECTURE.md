# Architecture

```
Browser (static HTML/JS)  -->  Caddy  -->  FastAPI (app/main.py)
                                              |-- service.py   case desk operations
                                              |-- engine.py    ALL times, lateness, scores, routing (pure functions)
                                              |-- guardrails.py checks on AI / human reply text
                                              |-- llm.py       MockLLM | OpenAI-compatible client (optional)
                                              `-- db.py        SQLite file on a Docker volume
```

## Code map

| Path | Role |
|---|---|
| `app/main.py` | HTTP API and static page |
| `app/service.py` | import, duplicate proposals, decisions, drafts (`Desk`) |
| `app/engine.py` | `analyze(evidence)` -> attempts vs deadline, score state, warnings, blockers, gates, suggested action |
| `app/guardrails.py` | citation check, number/time conflict check, commitment check |
| `app/drafting.py` | deterministic reply template (mock AI and AI-failure fallback) |
| `app/llm.py` | `MockLLM`, `OpenAICompatLLM` (Vultr Serverless Inference), 20s default timeout |
| `app/fixtures.py` | synthetic course DEMO 3060: cases A, B, C, D, policy `POL-LATE-v1` |
| `app/db.py` | schema and connection helper |
| `app/static/` | Case Queue, Evidence View, Decision Desk |

## Data model (SQLite)

`cases` (course, assignment, student pseudo-id, owner, status) 1-N `evidence` (source type, ref id, timestamp, summary, **source_text**, payload) ; `recommendations` (source rules/ai/score_change, rationale, uncertainty, evidence ids, policy version) ; `decisions` (actor, role, action, timestamp, note, from/to status) ; `response_drafts` (**body_ai**, body_edited, body_final, verified, unverified, flags, ai_status) ; `review_items` ; `duplicates`.

Source text (what people wrote, what policy says) and AI-generated text are stored in separate columns and tables. Evidence ids are unique per case; merging cases copies evidence by ref id without duplicates.

## Status flow

`New -> TA review -> Awaiting professor | Awaiting student info -> Closed`. Actions map as: Approve and Reject -> Closed; Hold -> TA review (flagged on hold); Escalate -> Awaiting professor; Request student info -> Awaiting student info. Closed cases accept no further decisions.

## Rules that gate decisions (`engine.py`, `service.permissions`)

- **Blockers** (nobody can Approve/Reject): missing policy, insufficient evidence (unreadable/empty file, student claim with no record), records conflict (recorded late deduction contradicts attempt times).
- **Gates** (professor only): attempt-basis ambiguity, unexplained score difference, alternate evidence. A professor Approve on the attempt-basis gate must name the counted attempt; it is stored as approval evidence (`APR-<case>-<n>`).
- Escalate is TA-only. Notes are required for everything except Approve.
- On a professor approval the stored final reply is made consistent with the decision: the template's "decision pending" sentences are removed, a deterministic statement citing the `APR-` evidence id is added (recommendations only; no Canvas change, nothing sent), and human edits are kept. Text that still claims a pending decision in other words is rejected (409) instead of approved.
- Score recommendations exist only after a professor approval, are recorded as rows, and never leave the database.

## AI guardrails (`guardrails.py`)

1. Citations must exist in the case's evidence; unknown ids (including policies) are removed and flagged; a "verified" claim left without citations becomes "unverified".
2. Arithmetic, labelled scores (rubric total, entered, posted, final, deduction), minutes and clock times in AI text are compared with the engine; conflicts are flagged with the code value.
3. Commitment language (will regrade, waive, change the grade) is flagged.
4. The same checks run on the human-edited text at approval; flagged text cannot be approved.
5. On any LLM exception or timeout the draft falls back to the rules-only template and the UI says "AI unavailable, rules-only view".

## HTTP API

`GET /health`, `GET /api/config`, `GET /api/models`, `GET /api/cases`, `GET /api/cases/{id}`, `POST|PUT /api/cases/{id}/draft`, `POST /api/cases/{id}/draft/check`, `POST /api/cases/{id}/decision`, `POST /api/cases/{id}/score-recommendation`, `POST /api/duplicates/{id}/confirm|dismiss`, `POST /api/messages/import`, `POST /api/demo/reset?confirm=true`.

## Known limits

Role in requests is trusted (demo only). One uvicorn worker. The guardrail number checks are pattern-based and will not catch every phrasing.
