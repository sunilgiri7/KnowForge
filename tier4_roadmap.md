# KnowForge — Tier 4 Strategic Roadmap
## The Proactive Intelligence Layer

---

> **Framing**: You built Tier 1–3 in reaction to user actions — upload PDF, ask question, get answer. That is the baseline. The market gap in 2025–2026 is not *better answers* — it is **the app finding you before you find it**. Users who must remember to open your tool will churn. Users who *receive value without asking* become addicts.

---

## What You Have Built (Honest Inventory)

| Capability | Status | Strength |
|---|---|---|
| PDF → structured wiki | ✅ Done | Best-in-class synthesis pipeline |
| Hybrid BM25 + Pinecone retrieval | ✅ Done | Strong, most tools don't do this |
| Contradiction detection | ✅ Done | **No competitor does this today** |
| Temporal fact extraction | ✅ Done | Strong differentiator |
| Knowledge graph (entity linking) | ✅ Done | Solid multi-hop reasoning |
| Version ledger + semantic diff | ✅ Done | Audit trail nobody else has |
| Research intelligence | ✅ Done | Paper analysis + gap finding |
| Chat-driven reports | ✅ Done | XLSX/DOCX/PDF export |
| Workspace + RBAC | ✅ Done | Team-ready |
| Proactive insight on upload | ⚠️ Partial | Conflict scan exists, but passive |
| **Reasons to open app daily** | ❌ Missing | **The critical gap** |
| **Push / notify user when facts expire** | ❌ Missing | Temporal data exists, unused proactively |
| **Knowledge health scoring** | ❌ Missing | Quality layer never surfaced |
| **Active recall / learning loop** | ❌ Missing | Data is there, habit engine is not |

---

## The Market Gap You Must Own

After deep research across the KM market (NotebookLM, Notion AI, Glean, Guru, Confluence AI, Obsidian, Capacities):

**Every tool is reactive. You ask it something. It answers.**

The pattern every product is chasing but nobody has nailed yet for private knowledge bases is:

> **"Your knowledge base surfaces what you need before you need it."**

This is your Tier 4. Call it the **Proactive Intelligence Layer**.

---

## Tier 4 — The Proactive Intelligence Layer

Four sub-features. Pick them in order. Each one creates a daily pull-back habit loop.

---

### 🔴 Sub-Feature 1: Daily Knowledge Digest
**The single most impactful daily retention hook you can build**

#### What it is
Every morning (configurable time), KnowForge sends the user an in-app notification (and optionally email) containing a personalized "Knowledge Digest" built from their own wiki — summarizing what changed, what conflicts emerged, what facts are about to expire, and what the AI thinks they should re-read today based on their chat history patterns.

#### Why it creates daily habit
The research is clear: **external triggers → daily opens**. Duolingo built an empire on this. Every Slack workspace shows it. The trigger must feel *personal* — not a generic "You have 5 wiki pages." It must feel: *"Hey, your contract with Acme expires in 12 days and 3 pages conflict on the renewal clause."*

#### What you already have that makes this easy to build
- `WikiFactEvent` table — all temporal facts with `expiration_date` per page  
- `ContradictionStore` — open conflicts per workspace  
- `WikiPageVersion` — last modified timestamps  
- `ChatSession` — pattern of what topics user has been querying  
- `TemporalFactExtractor` — already extracts expiry dates

#### Implementation Plan
1. **Backend cron job** (APScheduler or `asyncio` background task, runs at configurable UTC time):
   - Query all `WikiFactEvent` rows where `expiration_date` is within next 30 days
   - Query open `contradictions` from JSON store
   - Query `WikiPageVersion` for pages modified in last 7 days
   - Query `ChatMessage` last 7 days to find most discussed topics/slugs
   - Pass all of the above to LLM with a `DAILY_DIGEST_PROMPT` → returns structured digest JSON with sections: `expiring_facts[]`, `new_conflicts[]`, `changed_pages[]`, `suggested_review_pages[]`, `insight_of_the_day`
2. **Notification Bell UI** — a bell icon in the topbar with unread count badge
3. **Digest modal** — opens showing cards for each section; each card links to the relevant page/conflict

#### Why it beats competitors
NotebookLM has zero proactive outreach. Notion AI sends generic "X pages updated." Nobody is composing a personalized reasoning digest *from the content itself.* This is KnowForge's moat applied proactively.

---

### 🟠 Sub-Feature 2: Knowledge Expiry Alerts + Fact Timeline
**Turn your temporal data into visible urgency**

#### What it is
A "Fact Timeline" view inside the wiki panel — a chronological list of all temporal facts across the workspace with a traffic light system: 🔴 Expired, 🟡 Expiring within 30 days, 🟢 Current. Each fact shows which wiki page it came from, the exact sentence, and a "Needs Review" action.

#### Why this is critical for real-world use
The #1 complaint in enterprise knowledge management research is **"I didn't know the document was outdated."** A legal team using KnowForge to manage contracts, compliance policies, or vendor agreements needs to see, at a glance, what has expired or will expire soon. This is the **anchor use case** that converts occasional users into daily users because the *cost of missing it is real*.

#### What you already have
`WikiFactEvent` — fact_type, subject, predicate, object_val, **effective_date**, **expiration_date**, source_quote, confidence, page_slug

This is live data. It is just not surfaced visually.

#### Implementation Plan
1. **New API endpoint**: `GET /api/v1/wiki/facts/timeline?days_ahead=90` — returns facts sorted by expiration proximity
2. **Frontend**: New "Timeline" tab inside the Wiki sidebar panel (between Wiki Pages and Factual Conflicts):
   - Segmented list: Expired | Expiring Soon | Current
   - Each row: fact subject, predicate, value, source page, expiry date, action buttons (Mark Reviewed / Go to Page)
3. **Inline warnings in chat**: When a user asks about a topic that has expired facts, inject a banner: *"⚠️ Note: 2 facts related to this topic have expired as of [date]. Review may be needed."*
4. **Digest integration**: Expiring facts show up in the Daily Digest (Sub-Feature 1)

---

### 🟡 Sub-Feature 3: Knowledge Health Score
**Give every workspace a score. Make quality visible. Create the "pull to improve" psychology.**

#### What it is
A workspace-level **Knowledge Health Score** (0–100) computed from:
- % of pages with recent versions (freshness)
- % of open vs. resolved contradictions (accuracy)
- % of pages with high confidence scores (completeness)
- % of pages with expiring temporal facts not yet reviewed (staleness)
- Contradiction severity weighted average (integrity)

Displayed as a number with a trend arrow (↑ improving, ↓ declining) and a breakdown panel.

#### Why this creates daily engagement
This is the **"streak" mechanic** for knowledge bases. Not gamification for its own sake — but because humans respond to visible progress. When a user resolves a conflict, resolves an expiry, or uploads a fresh document, their score goes up. The score creates a reason to do small maintenance tasks every day, which is exactly the micro-habit you need for daily retention.

Guru (the enterprise wiki tool) charges $18/user/month largely on the basis of their "Trusted" card status system. You can build a better version of this natively.

#### What you already have
- Contradiction severity and count — `ContradictionStore`
- Page versions and timestamps — `WikiPageVersion`
- Temporal fact expiry — `WikiFactEvent`
- Page confidence values — wiki page frontmatter

#### Implementation Plan
1. **Backend service** `KnowledgeHealthScorer`:
   - Runs on demand and caches result (invalidated when wiki is mutated)
   - Returns: `overall_score`, `freshness_score`, `accuracy_score`, `completeness_score`, `staleness_score`, `trend_vs_last_week`, `action_items[]`
2. **UI**: A "Health" card in the sidebar Wiki tab, above the upload zone:
   - Big number, colored ring (red → orange → green)
   - Trend indicator
   - "3 issues to fix" expandable list with one-click navigation to each issue
3. **API**: `GET /api/v1/wiki/health` — returns score breakdown

---

### 🟢 Sub-Feature 4: AI Flashcard Engine (Knowledge Reinforcement)
**The app that teaches you what you uploaded — creates a completely new and unique daily use loop**

#### What it is
KnowForge generates **AI-powered flashcards** from your wiki pages — question/answer pairs derived from your actual documents. User can review them daily (spaced repetition logic built in). Powered by a `FLASHCARD_GENERATION_PROMPT` that extracts: concept, question form, answer form, difficulty, source page, source quote.

#### Why this is the biggest differentiation play
This is a completely **unoccupied territory** in the knowledge management market. NotebookLM cannot do this. Notion AI cannot do this. Anki requires you to write the cards yourself. KnowForge can say: *"Upload your documents. We will make sure you actually remember them."* This is the feature that will make students, researchers, lawyers, medical professionals, and consultants use KnowForge every single day. Not occasionally when they need to find something — but *every morning for their review session.*

#### Spaced Repetition Logic (simple SM-2 algorithm)
- Each flashcard has: `ease_factor`, `interval_days`, `next_review_date`, `last_reviewed`, `result_history`
- After each review: Easy → interval ×2.5, Hard → interval ÷2, Again → reset to 1 day
- "Due today" cards shown first

#### Implementation Plan
1. **DB tables**: `FlashCard` (page_slug, question, answer, difficulty, source_quote), `FlashCardReview` (card_id, user_id, result, reviewed_at, next_due)
2. **Generation**: On page upsert → background task runs `FLASHCARD_GENERATION_PROMPT` → generates 5–10 cards per page → stored in DB
3. **API**:
   - `GET /api/v1/flashcards/due` — cards due today for this workspace
   - `POST /api/v1/flashcards/{id}/review` — submit result (easy/hard/again)
   - `GET /api/v1/flashcards/stats` — streak, total reviewed, mastery %
4. **UI**: New "Review" panel accessible from sidebar or a dedicated modal:
   - Card flip animation (question front, answer back)
   - Three response buttons: Again / Hard / Easy
   - Streak counter, "Cards due today: X" in sidebar

---

## Implementation Priority Order

```
Week 1–2  →  Sub-Feature 2 (Fact Timeline) — purely backend query + UI, no new models needed
Week 3–4  →  Sub-Feature 3 (Health Score) — computation engine + UI widget
Week 5–7  →  Sub-Feature 1 (Daily Digest) — cron job + digest prompt + notification UI
Week 8–12 →  Sub-Feature 4 (Flashcards) — new tables + generation pipeline + review UI
```

---

## Why This Tier Creates a Moat

| Competitor | Knowledge Digest | Expiry Alerts | Health Score | Flashcards |
|---|---|---|---|---|
| NotebookLM | ❌ | ❌ | ❌ | ❌ |
| Notion AI | ❌ | ❌ | ❌ | ❌ |
| Glean | ❌ | ❌ | ❌ | ❌ |
| Guru | ❌ | ❌ | Partial (Trust) | ❌ |
| **KnowForge Tier 4** | ✅ | ✅ | ✅ | ✅ |

---

## The Core Insight

You are not building a search tool. You are building a **knowledge operating system** that runs *for* the user, not *at the request of* the user.

The shift from Tier 3 → Tier 4 is the shift from **tool** → **habit**.

Tools are opened when needed. Habits are opened every day.

The Daily Digest, Expiry Alerts, Health Score, and Flashcards each create a different *reason to open KnowForge* that does not require the user to have a question. When four such reasons exist in parallel, you have a daily active user. That is the product worth building next.
