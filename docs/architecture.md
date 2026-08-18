# UNBIFY Discover — Architecture

```
Experience Layer        apps/web — cinematic prologue + interaction primitives
        ↓
Application Layer       apps/api — FastAPI modular monolith, /v1 contracts
        ↓
Signal / Human          signals.py — evidence accumulation, confidence,
Intelligence Layer      contradictions, corrections; profile_versions checkpoints
        ↓
ML + Policy Layer       policy.py (V0 rule-based, propensity-logged)
                        ml/ — datasets, LinUCB bandit, behavior models, registry
        ↓
Opportunity             opportunities.py + ranking.py — canonical catalog,
Intelligence            hard filters → retrieval → explainable ranking → diversity
        ↓
Activation              opportunity map → explore/save/start → outcomes
```

## The non-negotiable idea

**The LLM is not the intelligence system.** Evidence → state estimation →
prediction → policy → generation. `llm/gateway.py` is the single LLM boundary;
it expresses moments (reveals, syntheses, explanations) from structured facts
produced by the deterministic systems. It never scores humans, never ranks
opportunities, never controls state. Every capability has a validated schema,
bounded retries, a deterministic fallback, and a circuit breaker — the entire
journey completes with the LLM offline.

## State machine

PROLOGUE → SELF_DISCOVERY → REFLECTION → ALIGNMENT → TRANSFORMATION →
STORY_COMPLETE → OPPORTUNITY_MAP → ACTIVATION

Server-owned (`statemachine.py`); the Opportunity Map is unreachable before
STORY_COMPLETE (enforced + tested). Chapters complete on evidence + narrative
requirements, bounded by maximum length so nobody gets trapped.

## Learning loop

Every policy decision logs context, eligible actions, chosen action, propensity
and policy version (`policy_decisions`). Rewards accumulate as raw components
(completion, calibration, latency) under a versioned composite definition.
`ml/datasets/*` build reproducible snapshots; `ml/evaluation/policy_evaluation.py`
gates candidates via IPS before shadow; `model_registry` states are
candidate → evaluated → shadow → canary → production, promoted only explicitly.
