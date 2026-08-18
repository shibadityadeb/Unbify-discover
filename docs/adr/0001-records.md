# Architecture Decision Records

## ADR-1 · Modular monolith (FastAPI)
One deployable with strong module boundaries (`app/{signals,policy,ranking,...}`).
Microservices are premature before real load or team scale.

## ADR-2 · PostgreSQL as system of record
All authoritative state in Postgres via `DATABASE_URL`. Redis (optional,
`REDIS_URL`) only for ephemeral state. Dev fallback is SQLite, loudly non-prod.

## ADR-3 · pgvector
Embeddings stored as JSON everywhere plus native `vector` columns + ivfflat
index created by a postgres-only migration. Retrieval degrades to in-process
cosine on small catalogs.

## ADR-4 · Server-authoritative session state
Frontend renders; the server owns progression. Transitions are validated;
refresh/duplicate/tab races re-serve the authoritative current step.

## ADR-5 · Signal Engine over LLM scoring
Responses map to weak, versioned construct updates. Corrections outweigh
inference; contradictions are preserved, not averaged away.

## ADR-6 · Contextual-bandit progression
Policy V0 is deterministic + information-gain driven. LinUCB exists offline,
inactive until propensity-logged data passes IPS evaluation and shadow review.

## ADR-7 · LLM gateway boundary
One module, capability-based, versioned prompt registry, schema validation,
cost logging, circuit breaker, deterministic fallbacks.

## ADR-8 · Model versioning & propensity logging
Every decision carries policy version + propensity; every model is registered
with dataset/feature versions and promoted one stage at a time.

## ADR-9 · Experience layer kept as hand-built static app
The cinematic prologue predates this build and its quality is part of the
product. It stays a framework-free static app served by the API; a Next.js
migration is deliberate future work, not a prerequisite — the frontend already
holds zero authoritative intelligence.
