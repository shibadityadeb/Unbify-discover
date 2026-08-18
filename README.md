# UNBIFY Discover

A cinematic, four-chapter self-discovery journey — one continuous interactive story built with plain HTML, CSS, and JavaScript. No frameworks, no build step.

**The journey:**

| Scene | Motion language | Question |
|---|---|---|
| Intro — orbit system | Possibility | — |
| Chapter I — Self Discovery (Swami Vivekananda) | Reveal | *Who am I?* |
| Chapter II — Reflection (Marcus Aurelius) | Stillness | *What has shaped me?* |
| Chapter III — Alignment (Lao Tzu) | Flow | *What truly fits?* |
| Chapter IV — Transformation (Gautama Buddha) | Expansion | *What am I ready to become?* |

Each chapter uses its exact art-directed frame (`assets/ch*.png` masters, served as gentle 2× derivatives) with all typography, navigation, hotspots, and animation layered above the untouched artwork. Scenes transform into each other — portal light into portrait, inner path into Roman road, straight lines into flowing river, convergence into sunrise — with GPU-composited transitions throughout.

## Run

```bash
python3 -m http.server 4573
```

Then open http://localhost:4573. Advance with scroll, swipe, arrow keys, the chapter cues, or the menu / journey-map overlays.


## The Discover Experience (adaptive phase)

After each chapter opener, the artwork becomes a doorway into an adaptive, AI-directed
experience — instinctive choices, tiny trade-offs, scenarios, prioritization, reveals
and calibration that gradually build a living Opportunity Profile. It is **not** a
questionnaire: an Experience Orchestrator decides every next moment.

```text
SESSION STATE → EXPERIENCE ORCHESTRATOR → safe interaction primitive
→ AI generates contextual content → server validates → frontend renders
→ user response → SIGNAL ENGINE → updated state ↺
```

- `server.js` — zero-dependency Node server (static site + `/api/discover/*`)
- `discover/orchestrator.js` — pacing, chapter objectives, evidence thresholds, repetition limits
- `discover/signals.js` — evidence accumulation, confidence, contradiction detection
- `discover/ai.js` — the Experience Director (LiteLLM, server-side key, strict output validation, circuit breaker)
- `discover/fallbacks.js` — curated interaction library; the full journey works with no model at all
- `discover.js` / `discover.css` — client renderers for every interaction primitive

### Run the full experience

```bash
node server.js
```

Open http://localhost:4574. Set `LITELLM_KEY` in `.env` (never exposed to the browser)
to enable the AI director; without it the curated library drives the journey.
Sessions persist in `data/` — returning users continue where they left off.

## Wiring destinations

Set real URLs in the `LINKS` block at the top of `main.js` (menu, journey map, and each chapter's experience scene). Left as `null`, built-in overlays and placeholder scenes are used.
