# UNBIFY Discover

A production-grade adaptive **Human Opportunity Engine** wrapped in a cinematic,
four-chapter self-discovery story.

```
PART ONE — DISCOVER (the finite story: MEANING)
PROLOGUE → SELF DISCOVERY → REFLECTION → ALIGNMENT → TRANSFORMATION
        → FINAL MIRROR → STORY COMPLETE

PART TWO — MATERIALIZATION (the bridge: VALUE)
position · capability map · leverage map · gaps · directions · experiments
        → evidence-gated UNBIFY product routing

PART THREE — MY UNBIFY (persistent workspace)
DISCOVER_WORKSPACE:  QUESTIONS (precision) · ACTIONS (progress, ranked)
```

**Materialization** (`app/materialization.py`) converts the story into objects
the user can save, test, compare and act on. The Final Mirror is the
Transformation closing — evidence decides which beats exist (what survived /
what we changed our mind about / what real life added / what you already have /
what we still would not claim); there are no mandatory personality slots, no
prescribed career, and no generic next-step advice. Only after an explicit
continue does MATERIALIZATION produce the professional position, capability
map, leverage map, gaps, ranked directions and — per direction — the cheapest
experiment that would resolve its real uncertainty (`app/experiments.py`).
Objects persist with a lifecycle (new → exploring → saved → testing → active →
dismissed → completed); dismissal is ranking feedback, and experiment outcomes
enter the evidence ledger as the strongest evidence the system receives.
UNBIFY products (`app/products.py`) appear only when the chain
need → evidence → gap → product capability is complete, are presented as
infrastructure for the user's own direction, and never gate exploring, saving
or testing.

The story only concludes after Chapter 4; the workspace (and the Opportunity
Map inside its Actions tab) is unreachable earlier — enforced by the
server-owned state machine and covered by tests. Chapter interactions are
grounded, instantly understandable behavior and trade-offs — never abstract
personality symbolism.

## Architecture (short version)

```
SIGNAL ENGINE → HUMAN STATE → PROFESSIONAL STATE → EXPERIENCE POLICY
      (what should happen next?)          ↓
                                  NARRATIVE DIRECTOR
                             (how should this moment feel?)
                                          ↓
                                    CONTENT / UI
        (LLM beside the loop: expression, never intelligence)
```

**The intelligence core** (`app/knowledge.py`, `app/interpretation.py`,
`app/thresholds.py`, `app/content_policy.py`) keeps four levels of knowledge
apart: explicit facts (stated by the user, stored with provenance), derived
facts (conservative normalizations), hypotheses (rows with supporting AND
contradicting evidence ids, versioned — never silently overwritten), and
actionable conclusions (gated behind strict, versioned thresholds). Free text
runs through two passes: fact extraction that names ambiguities without
resolving them ("I manage codes and softwares" → `works_with_software` + an
open ambiguity — never a management inference), then a clarification-value
decision that asks at most one easy question per chapter, and only when it
materially matters. The policy carries an overinterpretation-risk penalty and
a falsification bonus (anti-confirmation-bias); reveals abstain or soften when
the claim would outrun the evidence; corrections write `inference_feedback`
and cascade-invalidate downstream conclusions; and role-level analysis is
blocked at the validation layer until multiple independent evidence sources,
professional context, and confident features exist — before that the system
offers broad direction families, or says honestly that it doesn't know yet.
Dev inspector: `GET /v1/debug/sessions/{id}/intelligence`.

**The Narrative Director** (`app/narrative_director.py`) owns per-session
storytelling state, and a **ChapterClosingPlanner** (`app/closing_planner.py`)
selects each closing's architecture (belief_revision, callback_resolution,
unexpected_absence, professional_grounding, resonance_shift, reconstruction, …)
from actual `narrative_events` before any copy exists — never repeating the
previous chapter's structure, always recording why in `chapter_closing_plans`.
The director also owns (`narrative_states`): story beats with intents, narrative
threads (opened → developing → resolved), rolling copy memory, metaphor /
opening / sentence-shape usage. Every story sentence carries an intent
(`CONNECT_PREVIOUS_ANSWERS`, `INTRODUCE_CONTRADICTION`, `CALLBACK`, …) and is
generated from the actual event that just happened — then passes the
repetition pipeline (`app/repetition.py`: exact, normalized, semantic,
opening, shape, metaphor, verbal-tic checks). Rejected copy regenerates with
novelty constraints or falls back to context-derived composition; silence is a
valid outcome. Chapter closings (`app/closings.py`) use four distinct
grammars/layouts, each ending in a real unresolved thread and a manual CTA.
A `SurpriseEngine` (`app/surprise.py`) varies chapter-end surprises
(contradiction reveal, previous-answer return, prediction test, …).

**Public-figure resonance** (`app/resonance.py` + `app/figure_kb.py`) compares
narrow, documented PROFESSIONAL patterns — never personalities. The
`PublicFigureKnowledgeBase` is DB-backed (`public_figures`,
`public_figure_patterns`, `public_figure_evidence`, `public_figure_sources`,
embeddings, versions) and populated only through the ingestion pipeline
(source → extract → normalize → review → map to approved constructs → store →
embed → version); the LLM never invents figure facts at request time. Matching
is evidence-gated (weak evidence ⇒ NO match), chapter- and
professional-context-adaptive, diversity-enforced, and fame is not a ranking
feature. Users can challenge any match (`POST …/resonance/feedback`); a
rejected match stays suppressed until evidence materially changes. The dev
Story Inspector lives at `GET /v1/debug/sessions/{id}/story`.

See [docs/architecture.md](docs/architecture.md) and [docs/adr/0001-records.md](docs/adr/0001-records.md).

**Real-time recommendations.** Nothing is served from a pre-baked answer:
`POST /v1/discover/actions/analyze` loads the latest profile and professional
state, derives the intent, builds an impersonal market query scope, checks
freshness **per signal** (posting volume ages in a day, occupation definitions
in months — ontology and market age on different clocks), and triggers a
targeted refresh only for the slice that request actually needs. Existing
supported evidence returns immediately with a freshness state (CURRENT /
REFRESHING / PARTIAL / STALE_BUT_USABLE / INSUFFICIENT); the caller polls
`GET /v1/intelligence/refresh/{id}`, and a completed refresh produces a **new
analysis version** with a change summary rather than silently swapping the old
conclusion. Every analysis records the profile, market-snapshot, ranker and
scope versions that produced it.

**PostgreSQL is the entire operational backbone** — no Redis, no Celery, no
broker. `intelligence_jobs` is the queue, claimed with
`SELECT … FOR UPDATE SKIP LOCKED`; `intelligence_scope_cache` collapses
concurrent identical requests onto one refresh via a scope hash (20 users
asking the same question cause one Apify run, verified by test);
`domain_enrichment_requests` lets repeated demand from thin domains raise
enrichment priority; `source_health` tracks runs, failures, cost and which
sources actually change recommendations. A per-scope cooldown stops refresh
loops when a signal simply isn't obtainable from permitted sources — the
system says so instead of scraping forever. Workers:
`python -m app.world.worker weekly` (broad) and `… drain` (job execution).

**World Intelligence** (`app/world/`) — the opportunity layer is a living
graph, not a hardcoded career list. A canonical occupation ontology
(`occupations` + aliases + O*NET/ESCO external mappings — UNBIFY ids are its
own) spans trades, clinical, legal, financial, military, agricultural, retail
and knowledge work, each decomposed into capabilities with licensing,
pathway potentials (employment / specialization / contracting / business
ownership / consulting / training / part-time / …) and documented transitions.
A compliant ingestion layer (`world/ingestion.py`, source registry with
mandatory compliance records, Apify gateway behind `APIFY_TOKEN`, LinkedIn
adapter boundary DISABLED by default) turns raw records into
`source_observations`, aggregated into `market_signals` with confidence,
source diversity, recency decay and retained cross-source conflicts — one
community post is never market evidence. Matching (`world/matching.py`)
projects the user's OWN evidence into capability space (title decomposes via
the ontology; market popularity never alters the human profile), gates
regulated practice on eligibility, ranks across multi-factor scores with
explicit user intent, abstains with `insufficient_world_evidence` + a
privacy-scrubbed targeted-refresh queue when coverage is thin, and persists
reproducible `opportunity_market_snapshots`. Weekly refresh:
`python -m app.world.worker weekly`. Provenance:
`GET /v1/opportunities/{id}/evidence`; internal ops under
`/v1/internal/intelligence/*` (X-Internal-Token).

## Layout

```
apps/web        the experience layer — cinematic prologue + interaction primitives
apps/api        FastAPI modular monolith: sessions, state machine, signal engine,
                policy V0 (propensity-logged), interaction catalog, LLM gateway,
                opportunity catalog + explainable ranking, events, outcomes
packages/contracts   typed API contract (v1)
ml              feature builders, dataset builders, LinUCB bandit, behavior
                training, IPS offline evaluation, model registry conventions
infra           docker-compose for local Postgres(pgvector)
docs            architecture + ADRs
```

## Quote intelligence

Discover occasionally shows a documented principle from someone who produced
real results — but only because the user's *own* supported evidence pulled it.
The order is always: your evidence → what we observed → why it may matter →
an external example → back to you. Never the reverse.

Quotes live in PostgreSQL (`quotes`, `quote_people`, `quote_sources`) with
themes, mapped professional patterns and a primary-source citation. The LLM is
never asked to recall a quote — it may only write the sentence tying a
retrieved one to the user's evidence.

**Nothing displays until a human verifies it.** The seed corpus is inserted as
`review_needed`, and retrieval filters on `verification_status`, so an
unreviewed library shows no quotes rather than unchecked ones:

```bash
python3 scripts/verify_quotes.py status   # what is pending
python3 scripts/verify_quotes.py list     # each quote with its cited source
python3 scripts/verify_quotes.py verify <quote_id>
```

Changing a quote's wording or source automatically resets it to
`review_needed` — a sign-off applies to the text someone actually read, not to
whatever replaces it.

A person is never shown twice in one journey, themes are tracked to avoid a
single principle dominating, and there is at most one quote moment per chapter
— often none, because a forced quote is worse than no quote. Accomplishment
deliberately spans trades, craft, manufacturing, sport, science and engineering
as well as business: "successful" must not collapse into "tech founder".

The **same principle, different world** module pairs two people from different
fields who arrived at the same working principle, and states plainly that their
goals and circumstances had nothing else in common.

`pattern_value_relationships` is what turns an observation into economics —
pattern × context → the mechanism by which it pays. Quotes never touch Human
State, Professional State or ranking, so no circular inference is possible.

## Perceived latency

A pause after a selection must never read as unresponsiveness, and must never
pretend to be narrative.

The client acknowledges a tap **locally within a frame** (measured: ~3ms) — the
chosen thing settles, the rest softens, duplicate input locks — and the leave
choreography starts *alongside* the request rather than after it, so animation
and network overlap. The answered scene stays on screen while the backend works
instead of blanking, so processing has context.

Thinking states escalate only as far as the actual wait requires: nothing under
500ms, ambient motion (no words) to 2s, one plain line to 5s, explicit
transparency beyond that — each held long enough to read. There is no spinner
and no rotating copy pool.

The backend tells the client what genuinely changed (`processing.changed/kind/
note`), so "that answer changed something" appears only after a real
contradiction, correction, newly-learned fact or hypothesis promotion — never
on ordinary confidence drift, never twice running, and never more often than
once every five answers. Ordinary work gets motion; only real change gets words.

Failure is honest: the thinking state stops, "That didn't go through / Try
again" appears with the answer preserved, and the retry re-submits it.
Submission is idempotent, so a retry cannot double-count evidence or advance a
chapter twice. Phase timings are recorded per request
(`GET /v1/debug/latency` → p50/p75/p95/p99 against budgets), and the browser
console prints an acknowledgement/network/render/perceived breakdown in dev.

## Environment

Only three variables are required:

```
DATABASE_URL=   # PostgreSQL (quotes and special characters in the password are handled)
APIFY_TOKEN=    # world-intelligence acquisition
LITELLM_KEY=    # narrative expression only — the journey completes without it
```

Everything else is optional, and the system degrades honestly without it:

- **`APIFY_WEBHOOK_SECRET`** unset → inbound webhooks are refused (an unsigned
  caller is never trusted). Async Apify runs are instead completed by polling:
  `python -m app.world.worker drain` reconciles them. With a secret set, the
  webhook is used and polling remains a safety net for dropped deliveries.
- **`SESSION_SECRET`** unset → `/v1/internal/*` endpoints answer loopback
  callers only; set it to use them remotely. Required in production.
- **`APP_URL`** unset → CORS stays permissive for local development. Required
  in production.

**Database latency matters more than anything else here.** One interaction is
roughly 20 database round trips, so a database in a distant region dominates
response time (measured: ~194ms/round trip to `ap-northeast-1` ≈ 4–5s per
interaction; a nearby region at ~20ms gives ~0.5s). Put the database in the
region closest to your users.

## Run

```bash
cp .env.example .env          # fill LITELLM_KEY (optional), DATABASE_URL (prod)
pip install -r apps/api/requirements.txt
cd apps/api
python3 -m alembic upgrade head
python3 -m app.seed
python3 -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Anonymous sessions persist and resume; delete via
`DELETE /v1/discover/sessions/{id}`.

- **Database**: `DATABASE_URL` (PostgreSQL + pgvector in production; SQLite is a
  loud dev-only fallback). Production fails fast on missing env.
- **LLM**: `LITELLM_KEY` → https://litellm.gtor.app/v1, model `gpt-5.6-luna`,
  through one gateway with validation, cost logging, circuit breaker, and
  deterministic fallbacks. The journey completes with the LLM offline.
  The gateway calls the model in **streaming** mode: this deployment's
  non-streaming path returns upstream 500s while streaming works, and replies
  can carry a `LITELLM_NOPATCH` prefix, so JSON is extracted from the
  outermost braces rather than parsed whole. It is a reasoning model —
  completions land at 4–10s (final mirror ~7–13s), so per-capability timeouts
  are set from measured latency; too-tight limits silently cut working calls
  and fall back to deterministic copy. The breaker separates *slow* from
  *broken*: a hard failure rests immediately, timeouts only after three in a
  row. Under `APP_ENV=test` the gateway is off, so tests exercise UNBIFY's own
  intelligence and stay deterministic.

## Tests

```bash
cd apps/api && APP_ENV=test python3 -m pytest tests/
```

110 tests including the critical E2E: anonymous user → all four chapters →
story close → Opportunity Map (explainable, diverse) → activation; plus
no-early-map, stale-response safety, signal accumulation, correction weighting,
contradiction preservation, policy determinism/eligibility/bounded journeys;
plus full-journey narrative novelty (no repeated bridges, no verbal tics, four
distinct closing structures, varied resonance presentation) and resonance
guarantees (match evolution across users and professional context, honest
empty results on low confidence, pattern→evidence→source tracing that fails
closed, feedback persistence + suppression).

## ML pipeline

```bash
python3 ml/datasets/build_bandit_dataset.py     # propensity-logged decisions
python3 ml/datasets/build_behavior_dataset.py   # engagement labels
python3 ml/training/train_behavior.py <dataset> # refuses tiny datasets
python3 scripts/promote_model.py <id> <stage>   # explicit stage-by-stage promotion
```

`ml/policies/linucb.py` implements the contextual bandit behind the
`ExperiencePolicy` interface — **inactive** until propensity-logged data passes
IPS evaluation (`ml/evaluation/policy_evaluation.py`) and shadow review.

## Adding content

- **Interactions**: `apps/api/app/catalog.py` (versioned definitions with hidden
  per-option signals) → `python3 -m app.seed`.
- **Signal mappings**: option `signals` arrays; engine rules in `app/signals.py`.
- **Opportunities**: `apps/api/app/opportunities.py` seed list (canonical catalog,
  prerequisite/preferred features, disqualifiers) → `python3 -m app.seed`.

## Deployment notes

Single API deployable (uvicorn workers behind a proxy) + static web dir.
Set `APP_ENV=production`, `DATABASE_URL`, `SESSION_SECRET`, `APP_URL`.
Migrations via Alembic only — no schema hacks at startup in production.
