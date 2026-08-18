# Discover API Contract (v1)

All journey state is server-authoritative. Base path: `/v1`.

## Session
- `POST /v1/discover/sessions` `{sessionId?}` → `{sessionId, state, interaction, estimatedProgress}`
  Creates an anonymous session or resumes an existing one.
- `GET /v1/discover/sessions/{id}` → session status
- `GET /v1/discover/sessions/{id}/next` → current step (idempotent; re-serves pending interaction)
- `DELETE /v1/discover/sessions/{id}` → privacy delete

## Journey
- `POST /v1/discover/sessions/{id}/responses` `{interactionId, response, elapsedMs}`
  Stale/duplicate submissions return `{stale: true}` plus the authoritative current step.
- `POST /v1/discover/sessions/{id}/advance` `{to}` — acknowledge a server-offered transition.
  Illegal jumps (e.g. SELF_DISCOVERY → OPPORTUNITY_MAP) return 409.
- `GET /v1/discover/sessions/{id}/profile` — the user's own mirror (transparency + correction rights)

## Interaction payload types
`binary_tension | spectrum | scenario_choice | forced_rank | object_sort |
micro_reflection | reveal | possible_lives | final | chapter_transition | story_close |
workspace`

Response payloads by type:
- choices → `{optionId}`
- sliders → `{value: -1..1}`
- sorts → `{optionIds: []}`
- micro_reflection → `{text}` or `{skipped: true}`
- reveal → `{optionId: yes|kind_of|no|first|second|depends}`

## Workspace (PART TWO — after STORY_COMPLETE only; 409 earlier)
- `GET /v1/workspace/{sid}` → `{clarity, questions: {available, invite}, actions: []}`
- `POST /v1/workspace/{sid}/questions/next` → one highest-value adaptive question
  (answered through the standard `/responses` endpoint)
- `GET /v1/workspace/{sid}/actions/{actionId}` → intelligence-generated module content
  (`explore` returns the Opportunity Map with `whyThis` factor contributions)

## Opportunities
- `POST /v1/opportunities/{id}/explore` `{sessionId}`
- `POST /v1/opportunities/{id}/save` `{sessionId}`
- `POST /v1/discover/sessions/{id}/activate` `{action, opportunityId}` — records the chosen
  path; the workspace persists (no state change)
- `POST /v1/outcomes` `{sessionId?, opportunityId?, kind, payload}`

Hidden option signals, policy internals, and factor math never appear in public payloads
except as the explicit `whyThis` factor summaries on the Opportunity Map.
