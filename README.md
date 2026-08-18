# UNBIFY Discover

A production-grade adaptive **Human Opportunity Engine** wrapped in a cinematic,
four-chapter self-discovery story.

```
PART ONE — DISCOVER (finite story)
INTRO / PROLOGUE → SELF DISCOVERY → REFLECTION → ALIGNMENT → TRANSFORMATION → STORY CLOSE

PART TWO — MY UNBIFY (persistent workspace)
DISCOVER_WORKSPACE:  QUESTIONS (adaptive deepening) · ACTIONS (Opportunity Map,
best next move, experiments, gaps, AI leverage, compare paths…)
```

The story only concludes after Chapter 4; the workspace (and the Opportunity
Map inside its Actions tab) is unreachable earlier — enforced by the
server-owned state machine and covered by tests. Chapter interactions are
grounded, instantly understandable behavior and trade-offs — never abstract
personality symbolism.

## Architecture (short version)

```
USER → EXPERIENCE → SIGNAL ENGINE → HUMAN STATE → POLICY → NEXT EXPERIENCE ↺
                            (LLM beside the loop: expression, never intelligence)
```

See [docs/architecture.md](docs/architecture.md) and [docs/adr/0001-records.md](docs/adr/0001-records.md).

## Layout

```
apps/web        the experience layer — cinematic prologue + interaction primitives
apps/api        FastAPI modular monolith: sessions, state machine, signal engine,
                policy V0 (propensity-logged), interaction catalog, LLM gateway,
                opportunity catalog + explainable ranking, events, outcomes
packages/contracts   typed API contract (v1)
ml              feature builders, dataset builders, LinUCB bandit, behavior
                training, IPS offline evaluation, model registry conventions
infra           docker-compose for local Postgres(pgvector) + Redis
docs            architecture + ADRs
```

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
- **Redis**: `REDIS_URL` optional locally; used for ephemeral state only.

## Tests

```bash
cd apps/api && APP_ENV=test python3 -m pytest tests/
```

19 tests including the critical E2E: anonymous user → all four chapters →
story close → Opportunity Map (explainable, diverse) → activation; plus
no-early-map, stale-response safety, signal accumulation, correction weighting,
contradiction preservation, policy determinism/eligibility/bounded journeys.

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
