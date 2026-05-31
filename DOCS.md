# KnowForge — Comprehensive Implementation Docs

Everything implemented in the project, organized by subsystem.

---

## 1. Authentication & User Management

### Backend (`app/services/auth.py`, `app/api/v1/routes/auth.py`)
- **Register** — hashes password with bcrypt, creates `User`, sends 6-digit email verification code via SMTP (or logs to console if SMTP unconfigured)
- **Email Verification** — validates code against `EmailVerificationCode` table; marks `user.is_verified = True`; resend-code endpoint regenerates with a new expiry
- **Login** — checks `is_verified` gate; issues signed JWT (`HS256`, configurable expiry)
- **`/me`** — returns current user profile; also triggers `ensure_personal_workspace()` so the user always has an active workspace

### Models (`app/db/models.py`)
- `User` — id, name, email, password_hash, is_verified, active_workspace_id, llm_active_provider
- `EmailVerificationCode` — expires_at, consumed_at; unique constraint on (user_id, code)
- `UserLlmKey` — encrypted_key, provider, model; unique constraint on (user_id, provider)

---

## 2. Workspace & RBAC (`app/services/workspace.py`, `app/api/v1/routes/workspaces.py`)

### Roles
`owner > admin > editor > viewer` — enforced via `require_role()` on every mutating endpoint.

### Lifecycle
- **Personal workspace** auto-created on first login; old `storage/users/{uid}/` storage migrated to `storage/workspaces/{wid}/`
- **Team workspaces** — create, rename, delete (cascades wiki, chat, research, reports)
- **Invites** — email-based, 7-day TTL, role-scoped; invite consumption auto-creates `WorkspaceMember`
- **Workspace switcher** — user's `active_workspace_id` updated server-side; all APIs read from active workspace

### Models
- `Workspace` — id, name, slug, is_personal
- `WorkspaceMember` — workspace_id, user_id, role
- `WorkspaceInvite` — email, role, code, expires_at, consumed

---

## 3. PDF Ingestion Pipeline (`app/llmwiki/ingest.py`)

### Stage 1 — Extraction
- Uses `pypdf` to extract raw text page-by-page
- Special regex passes to preserve table rows (`_MULTI_NUMBER_RE`) and numbered section headings (`_NUMBERED_SECTION_RE`)
- Addendum/Schedule/Annexure headings detected and kept as separate sections

### Stage 2 — Chunking & Chunk Notes
- Text split into configurable chunks; each chunk sent to LLM for `chunk_notes` (key facts, entities, summary)
- Uses a dedicated `compile_llm` with higher token budget and longer timeout

### Stage 3 — Wiki Synthesis
- All chunk notes + raw text passed to `SYNTHESIZE_WIKI_PROMPT` (or `COMPILE_PROMPT` for re-compilation)
- LLM writes a comprehensive, structured Markdown wiki page with title, tags, summary, entities, and full content

### Stage 4 — Post-Processing
- Knowledge graph entities and related_slugs computed (`KnowledgeGraphBuilder`)
- Related pages section appended to content
- `WikiVersionLedger.record_version()` writes immutable DB version row
- `TemporalFactExtractor.extract_and_store()` extracts time-sensitive facts
- `SupersessionDetector` checks if the new page supersedes an existing one (title similarity + entity overlap + content similarity, threshold 0.65)
- `ContradictionScanner.scan()` runs pairwise LLM check on related pages after ingest
- If `force_research=True`, `ResearchPaperAnalyzer.run_pipeline()` is also triggered

---

## 4. Wiki Storage (`app/llmwiki/storage.py`)

### File Layout
```
storage/workspaces/{workspace_id}/
  pages/          ← markdown wiki pages (one .md per slug)
  compact/        ← LLM-compressed versions of oversized pages
  sources/        ← original uploaded PDFs
  events/         ← contradictions.json
  reports/        ← generated report files
```

### WikiStore
- `upsert_page()` — atomic write (write to temp, rename), invalidates BM25 index, triggers Pinecone upsert
- `read_page()` — parses frontmatter YAML + body; `prefer_compact=True` returns compact version if available
- `list_pages()` — returns `WikiPageListItem[]` from frontmatter metadata
- `delete_page()` — removes .md file + compact file; deletes Pinecone vectors
- `mutation_revision` counter — incremented on every write/delete; used to invalidate in-memory indexes

---

## 5. Hybrid Retrieval Engine (`app/llmwiki/indexer.py`)

### BM25PageIndex
- In-memory multi-field inverted index (title, summary, tags, entities, content)
- Field weights: title=3.5, summary=2.0, tags=2.0, entities=2.5, content=1.0
- Rebuilt from disk when `mutation_revision` changes or age > 60s
- Thread-safe rebuild lock

### Pinecone Vector Search (`app/llmwiki/vector_store.py`)
- `all-MiniLM-L6-v2` embeddings via `sentence-transformers` (384-dim)
- One Pinecone index, namespaced by workspace_id
- Each page indexed as header block + overlapping content chunks (512 chars, 80-char overlap)
- Graceful no-op if `PINECONE_API_KEY` not set

### Hybrid RRF Fusion
- Both BM25 ranked list and Pinecone ranked list merged via Reciprocal Rank Fusion
- Configurable weight split (BM25 vs. semantic)
- Final ranked list used for routing and context assembly

### Routing (`indexer.route()`)
- Calibrated BM25 score thresholds determine `wiki`, `fallback`, or `direct` route
- `RouteDecision` — route, page_slugs, confidence (0–1), reason, difficulty (easy/hard)

---

## 6. AI Harness (`app/llmwiki/harness.py`)

The deterministic control layer that wraps every chat request before LLM answer generation.

### Multi-Query Expansion (in order)
1. **Context-aware rewrite** — resolves pronouns/anaphora from history (`QUERY_REWRITE_PROMPT`)
2. **Step-back + keyword expansion** — generates 2 alternative phrasings (`QUERY_EXPANSION_PROMPT`)
3. **HyDE** — generates a hypothetical wiki passage and uses it as additional BM25 query (`HYDE_PROMPT`); bridges vocabulary gap between user phrasing and wiki terminology
4. **Memory expansion** — for profile/background questions, appends wiki page titles/summaries/tags as extra queries

### Harness Overrides
- Explicit page slug named in question → always routes to wiki (fast path)
- Memory/wiki-intent + direct route → force-fetch wiki candidates
- Document-intent terms (salary, contract, benefits) + direct route → reroute to wiki
- `intent="direct"` → skip retrieval entirely

### Knowledge Graph + Planner Multi-Hop
- `WikiKnowledgeGraph.expand()` follows entity links from seed pages (configurable hop count)
- Hard difficulty + LLM available → `PLANNER_PROMPT` generates sub-questions, each triggers a BM25 search to find additional pages
- All traces logged as `AgentTrace[]` for observability

### Contradiction Injection
- Before returning context, `ContradictionScanner.context_warnings_for_slugs()` prepends open conflicts as a warning block so the LLM flags them to the user

---

## 7. Chat Service (`app/llmwiki/chat.py`)

### Flow
1. `ConversationCompactor.compact()` — trims/summarizes history to token budget
2. Gratitude/smalltalk → handled locally (no LLM round-trip)
3. `AIHarness.plan()` → routing + context assembly
4. `build_chat_flow_graph()` (LangGraph DAG) → answer generation
5. If `difficulty="hard"` → CoT scaffold injected into `ANSWER_PROMPT`
6. `_rerank_candidates()` → LLM re-ranks BM25 candidates; rebuilds context in re-ranked slug order
7. `_verify()` → `VERIFIER_PROMPT` grades answer as fully/partially/unsupported
8. Returns `ChatResponse` with answer, citations, used_pages, knowledge_gap_created, agent_trace

### Interaction Types
- `interaction="message"` — normal chat
- `interaction="reply"` — threaded reply; parent message injected into history
- `interaction="comment"` — inline comment on a message

---

## 8. Version Ledger (`app/llmwiki/temporal.py`)

### WikiVersionLedger
- `record_version()` — computes SHA-256 content hash; skips write if identical to last version; stores `WikiPageVersion` with version number, content, summary, tags, entities, source_ids
- `get_versions()` — returns all version snapshots for a slug
- Versions are **immutable** — never updated, only appended

### Semantic Diff (`compute_semantic_diff`)
- Line-level diff via `difflib.SequenceMatcher` → hunks (equal/insert/delete/replace)
- LLM `SEMANTIC_DIFF_PROMPT` → semantic_summary, changed_facts[], risk_level (low/medium/high)

### Supersession Detection (`SupersessionDetector`)
- Weighted score = 0.5×title_similarity + 0.3×entity_overlap + 0.2×content_similarity
- Threshold 0.65 → creates `WikiSupersessionLink` and marks old page as `superseded`

### Temporal Fact Extraction (`TemporalFactExtractor`)
- `TEMPORAL_FACT_PROMPT` extracts up to 20 facts per page: fact_type, subject, predicate, object_val, effective_date, expiration_date, source_quote, confidence
- Regex fallback if LLM unavailable (date pattern matching)
- Stored as `WikiFactEvent` rows; old facts deleted and re-extracted on each page update

---

## 9. Contradiction Detection (`app/llmwiki/contradictions.py`)

### ContradictionStore
- Persists to `storage/workspaces/{id}/events/contradictions.json`
- Tracks `pair_fingerprints` (SHA-256 of each page) — skips re-scan if pages unchanged
- `replace_pair_results()` — atomically replaces all contradictions for a page pair
- Status transitions: `open` → `resolved` / `ignored`

### ContradictionScanner
- `candidate_pairs()` — finds pairs via `related_slugs` + entity-title overlap; caps at `contradiction_max_pairs_per_scan`
- `_scan_pair()` — sends excerpts of both pages to `CONTRADICTION_PROMPT`; LLM returns topic, claim_a, claim_b, severity (low/medium/high), rationale
- `context_warnings_for_slugs()` — builds inline warning string prepended to chat context

---

## 10. Knowledge Graph (`app/llmwiki/knowledge_graph.py`)

### Entity Extraction
- Sources: LLM chunk_notes `key_entities`, page title, tags, Markdown headings (H1–H3), proper nouns from content (first 12k chars)
- Deduped by normalized form; sorted by frequency then length; capped at `kg_max_entities_per_page`

### Related Slug Resolution
- For each entity, checks all pages for title/slug/alias match (prefix and substring matching)
- Builds bidirectional adjacency `related_slugs` list per page

### WikiKnowledgeGraph (in-memory runtime)
- Rebuilt when `mutation_revision` changes or age > 120s
- `expand()` — BFS from seed slugs, follows `related_slugs` edges, adds entity-matched slugs from query terms
- Configurable `max_hops` and `max_pages_in_context`

---

## 11. Compaction (`app/llmwiki/compaction.py`)

### WikiCompactor
- Triggered at ingest if page length exceeds `wiki_page_soft_char_limit`
- `COMPACT_PROMPT` asks LLM to preserve all facts, dates, names but reduce verbosity
- Compact version stored separately; `read_page(prefer_compact=True)` used at retrieval time

### ConversationCompactor
- Keeps last N messages verbatim; older messages LLM-summarized to a compact prior
- Fallback to keyword extraction if LLM unavailable

---

## 12. Research Intelligence (`app/llmwiki/research.py`, `app/api/v1/routes/research.py`)

### ResearchPaperAnalyzer pipeline
1. `CLASSIFY_PAPER_PROMPT` on first 3 pages → determines if document is a research paper; extracts title, authors, venue, DOI, year, abstract
2. If not research paper and `force_research=False` → returns False (normal wiki ingest proceeds)
3. `EXTRACT_RESEARCH_DETAILS_PROMPT` on full content → extracts methods[], claims[]
4. Sections extracted by heading pattern matching
5. All stored as `ResearchPaper`, `ResearchPaperSection`, `ResearchMethod`, `ResearchClaim`
6. `ResearchAnalysisJob` tracks status (pending → processing → done/failed)

### API Endpoints
- `GET /api/v1/research/papers` — list all papers with job status
- `GET /api/v1/research/papers/{id}` — full paper details (sections, methods, claims)
- `DELETE /api/v1/research/papers/{id}` — delete paper + all linked data
- `POST /api/v1/research/compare` — LLM comparison matrix across all workspace papers
- `POST /api/v1/research/gaps` — LLM literature gap analysis from all workspace claims
- `GET /api/v1/research/graph` — citation/relation edges for graph visualization

### Frontend Features
- Upload zone in Research sidebar tab (forces `force_research=True`)
- Auto-polling every 5 seconds for papers in "Processing" state
- Research modal with 4 sub-tabs: Paper Details, Citation Graph, Comparison Matrix, Literature Gaps
- Export/copy buttons on Comparison Matrix and Literature Gaps results

---

## 13. Report Generation (`app/llmwiki/reports.py`, `app/api/v1/routes/reports.py`)

### Chat-Driven Flow
1. User types a report request in chat
2. `detect_report_intent()` in chat router identifies the request
3. `generate_report_from_chat()` called:
   - BM25 pre-selects relevant pages (or all pages if global keywords detected)
   - `ANALYZE_CHAT_REPORT_PROMPT` → LLM produces name, description, columns[], export_format, scope_slugs
   - `ReportTemplate` created dynamically (persisted to DB for download link to work)
   - `ReportJob` created and immediately run
4. `ReportRunner.run()`:
   - For each scoped wiki page, calls `ReportExtractor.extract_page()` → column values extracted via LLM
   - Results assembled into `ExtractedRow[]`
   - Exported as XLSX/DOCX/PDF and saved to `storage/workspaces/{id}/reports/`
5. Assistant returns a download link in Markdown
6. Frontend intercepts link click → authenticated fetch → blob download

### Export Formats
- **XLSX**: `openpyxl`, one row per page, one column per extraction field
- **DOCX**: `python-docx`, one section per page with Markdown-to-DOCX rendering
- **PDF**: `WeasyPrint`, full HTML → PDF with branded stylesheet; custom `markdown_to_html()` parser for lists/tables/headings

---

## 14. LLM Provider System (`app/services/llm_factory.py`, `app/api/v1/routes/llm_keys.py`)

- Users can store encrypted API keys per provider (OpenRouter, OpenAI, Anthropic, Gemini)
- `build_user_llm()` decrypts the key and returns a provider-specific client
- Falls back to system Groq key if no user key configured
- Provider + model selection persisted in `UserLlmKey`; model can be customized per user

---

## 15. Frontend UI (`app/web/static/`)

### Layout
- **Auth screen** — Login / Register / Verify Email tabs
- **App shell** — collapsible sidebar (resizable via drag handle) + main chat area
- **Sidebar tabs**: Chats | Wiki | Research (state persisted in localStorage)
- **Workspace switcher** — dropdown in sidebar header

### Sidebar — Chats Tab
- New Chat button
- Session list: click to load, hover to show rename/delete menu
- Empty state

### Sidebar — Wiki Tab
- PDF upload zone (drag & drop or click); animated progress during upload
- Wiki pages list: click to open insight modal, hover for edit/delete/versions menu
- Compact Wiki button
- Factual Conflicts section: Scan button, conflicts list with severity badges and resolve/ignore actions

### Sidebar — Research Tab
- Dedicated research PDF upload zone with spinner animation during processing
- Auto-refresh polling for processing papers
- Paper list: click to open research modal
- Action buttons: ⚡ Graph, 📊 Compare, 🔍 Gaps

### Chat Area
- Message cards: role, author, timestamp, interaction label
- Per-message actions: Copy, Thread (reply), Save to Wiki
- Report mode toggle button in composer — changes placeholder text, sends report intent flag
- Reply banner shows active thread context
- Markdown rendering (headers, bold, italic, code blocks, tables, lists)
- Download link interception for report files (authenticated fetch → blob)
- Agent trace chips (citations, used pages)

### Modals
- **Wiki Insight Modal** — full page content: AI analysis sections at top, raw document content below (formatted)
- **Research Modal** — 4 sub-tabs: Paper Details, Citation Graph, Comparison Matrix, Literature Gaps
- **Version History Modal** — list of all versions; click any two to see semantic diff + line diff hunks
- **Save to Wiki Modal** — title, tags, optional target slug for appending
- **LLM Settings Modal** — provider, API key, model selection with provider logo
- **Delete Workspace Modal** — requires typing "delete" to confirm
- **New Workspace Modal** — name input

### Design System (`styles.css`, ~2500 lines)
- CSS custom properties for all colors, spacing, typography
- Dark terracotta-toned theme: `--accent: #cc5a37`, `--bg`, `--text`, `--muted`, `--line`
- Typography: Plus Jakarta Sans (UI) + Newsreader (serif accents) from Google Fonts
- Micro-animations: hover lifts, spinner, thinking animation, toast fade
- Glassmorphism card borders
- Responsive sidebar (collapses below threshold)

---

## 16. Database Schema Summary

| Table | Purpose |
|---|---|
| `users` | User accounts + LLM provider preference |
| `email_verification_codes` | Registration verification codes |
| `user_llm_keys` | Encrypted provider API keys |
| `workspaces` | Team/personal workspaces |
| `workspace_members` | RBAC membership (owner/admin/editor/viewer) |
| `workspace_invites` | Pending email invites |
| `chat_sessions` | Chat thread metadata (title, summary) |
| `chat_messages` | Individual messages (role, content, parent_id, interaction) |
| `wiki_page_records` | Canonical page identity per workspace |
| `wiki_page_versions` | Immutable content snapshots |
| `wiki_supersession_links` | Old→new page supersession relationships |
| `wiki_fact_events` | Temporal facts extracted per page |
| `wiki_promotions` | Chat answers staged for wiki inclusion |
| `report_templates` | Column definitions + scope slugs |
| `report_jobs` | Extraction run status + file path |
| `research_papers` | Detected academic papers |
| `research_paper_sections` | Structured paper sections |
| `research_methods` | Extracted methodologies + datasets |
| `research_claims` | Findings, limitations, hypotheses, gaps |
| `research_paper_edges` | Citation/relation graph edges |
| `research_insights` | Cached comparison matrix / gap analysis results |
| `research_analysis_jobs` | Async analysis job status tracker |

---

## 17. Key LLM Prompts (`app/llmwiki/prompts.py`)

| Prompt | Purpose |
|---|---|
| `SYNTHESIZE_WIKI_PROMPT` | Compile PDF chunks into structured wiki page |
| `COMPILE_PROMPT` | Re-compile existing wiki from raw source |
| `CHUNK_NOTES_PROMPT` | Extract key facts/entities from a text chunk |
| `ANSWER_PROMPT` | Generate RAG answer from wiki context |
| `DIRECT_CHAT_PROMPT` | Answer without wiki context |
| `VERIFIER_PROMPT` | Grade answer grounding level |
| `RERANK_PROMPT` | Re-rank BM25 candidates by relevance |
| `QUERY_REWRITE_PROMPT` | Resolve pronouns/anaphora for retrieval |
| `QUERY_EXPANSION_PROMPT` | Generate step-back + keyword variants |
| `HYDE_PROMPT` | Generate hypothetical wiki passage |
| `PLANNER_PROMPT` | Decompose hard question into sub-questions |
| `CONTRADICTION_PROMPT` | Detect factual conflicts between two pages |
| `COMPACT_PROMPT` | Compress a long wiki page |
| `ANALYZE_CHAT_REPORT_PROMPT` | Parse user's chat message into report schema |

---

## 18. API Surface

### Auth
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/resend-code`
- `POST /api/v1/auth/login`
- `GET  /api/v1/auth/me`

### Sources / Wiki
- `POST /api/v1/sources/upload` — upload PDF (`force_research` query param)
- `GET  /api/v1/wiki/pages`
- `GET  /api/v1/wiki/pages/{slug}`
- `PUT  /api/v1/wiki/pages/{slug}`
- `DELETE /api/v1/wiki/pages/{slug}`
- `POST /api/v1/wiki/compact`
- `GET  /api/v1/wiki/contradictions`
- `POST /api/v1/wiki/contradictions/scan`
- `PATCH /api/v1/wiki/contradictions/{id}`

### Chat
- `POST /api/v1/chat`
- `GET  /api/v1/chat/sessions`
- `GET  /api/v1/chat/sessions/{id}`
- `PATCH /api/v1/chat/sessions/{id}`
- `DELETE /api/v1/chat/sessions/{id}`

### Versions
- `GET  /api/v1/versions/{slug}`
- `GET  /api/v1/versions/{slug}/{version_number}`
- `POST /api/v1/versions/{slug}/diff`
- `POST /api/v1/versions/{slug}/restore/{version_number}`

### Research
- `GET  /api/v1/research/papers`
- `GET  /api/v1/research/papers/{id}`
- `DELETE /api/v1/research/papers/{id}`
- `POST /api/v1/research/compare`
- `POST /api/v1/research/gaps`
- `GET  /api/v1/research/graph`

### Reports
- `GET  /api/v1/reports` — list jobs
- `GET  /api/v1/reports/{id}` — single job
- `GET  /api/v1/reports/{id}/download` — download file
- `GET  /api/v1/reports/templates`
- `POST /api/v1/reports/templates`
- `PUT  /api/v1/reports/templates/{id}`
- `DELETE /api/v1/reports/templates/{id}`
- `POST /api/v1/reports/generate`

### Workspaces
- `GET  /api/v1/workspaces`
- `POST /api/v1/workspaces`
- `PATCH /api/v1/workspaces/{id}`
- `DELETE /api/v1/workspaces/{id}`
- `POST /api/v1/workspaces/{id}/switch`
- `GET  /api/v1/workspaces/{id}/members`
- `POST /api/v1/workspaces/{id}/invite`
- `POST /api/v1/workspaces/invites/{code}/accept`

### Promotions
- `GET  /api/v1/promotions`
- `POST /api/v1/promotions`
- `PATCH /api/v1/promotions/{id}`

### LLM Keys
- `GET  /api/v1/llm/keys`
- `POST /api/v1/llm/keys`
- `DELETE /api/v1/llm/keys/{provider}`
- `POST /api/v1/llm/keys/test`
- `PATCH /api/v1/llm/keys/{provider}/activate`
