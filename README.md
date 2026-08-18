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

## Wiring destinations

Set real URLs in the `LINKS` block at the top of `main.js` (menu, journey map, and each chapter's experience scene). Left as `null`, built-in overlays and placeholder scenes are used.
