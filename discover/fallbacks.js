/* Curated fallback library. AI provides adaptation; these provide reliability.
   Every option carries hidden signals (never sent to the client). */

import { dimPhrase, topDims } from "./signals.js";

export const FALLBACK_INTERACTIONS = [

  /* ---------- visual pulls ---------- */
  {
    id: "vp_worlds", type: "visual_choice", chapters: ["self_discovery"],
    headline: "Don't think.",
    supportingText: "Which one pulls you?",
    options: [
      { id: "summit", motif: "mountain", label: "The far ridge",
        signals: [{ dim: "exploration", delta: .6, weight: .5 }, { dim: "autonomy", delta: .4, weight: .35 }, { dim: "mastery", delta: .3, weight: .25 }] },
      { id: "workshop", motif: "workshop", label: "The workshop at night",
        signals: [{ dim: "implementation_affinity", delta: .6, weight: .5 }, { dim: "mastery", delta: .5, weight: .4 }, { dim: "detail_orientation", delta: .3, weight: .25 }] },
      { id: "stage", motif: "stage", label: "The lit stage",
        signals: [{ dim: "persuasion", delta: .6, weight: .5 }, { dim: "leadership", delta: .4, weight: .35 }, { dim: "storytelling", delta: .4, weight: .3 }] },
      { id: "library", motif: "library", label: "The quiet archive",
        signals: [{ dim: "analytical", delta: .6, weight: .5 }, { dim: "abstraction", delta: .4, weight: .35 }, { dim: "facilitation", delta: -.25, weight: .2 }] },
      { id: "market", motif: "market", label: "The morning market",
        signals: [{ dim: "relationship_building", delta: .55, weight: .5 }, { dim: "sales_comfort", delta: .4, weight: .35 }, { dim: "empathy", delta: .3, weight: .25 }] },
    ],
  },
  {
    id: "vp_disappear", type: "visual_choice", chapters: ["self_discovery", "reflection"],
    headline: "Where would you rather disappear for a day?",
    supportingText: null,
    options: [
      { id: "sea", motif: "sea", label: "Open water",
        signals: [{ dim: "autonomy", delta: .5, weight: .4 }, { dim: "ambiguity_tolerance", delta: .35, weight: .3 }] },
      { id: "city", motif: "city", label: "A city you've never read about",
        signals: [{ dim: "exploration", delta: .6, weight: .5 }, { dim: "adaptability", delta: .35, weight: .3 }] },
      { id: "studio", motif: "studio", label: "A studio with every tool",
        signals: [{ dim: "originality", delta: .5, weight: .45 }, { dim: "implementation_affinity", delta: .45, weight: .35 }] },
      { id: "garden", motif: "garden", label: "A garden someone tended for years",
        signals: [{ dim: "stability", delta: .5, weight: .4 }, { dim: "persistence", delta: .35, weight: .3 }, { dim: "aesthetic_sensitivity", delta: .3, weight: .25 }] },
    ],
  },

  /* ---------- tiny trade-offs ---------- */
  {
    id: "tt_freedom", type: "binary_tension", chapters: ["self_discovery"],
    headline: "Somewhere between these is you.",
    supportingText: "Drag to where you actually live.",
    left: { label: "Freedom", dim: "autonomy" },
    right: { label: "Certainty", dim: "stability" },
  },
  {
    id: "tt_master", type: "binary_tension", chapters: ["self_discovery", "reflection"],
    headline: "Ten years from now.",
    supportingText: "Which side would you rather be on?",
    left: { label: "Master one thing", dim: "mastery" },
    right: { label: "Keep discovering", dim: "exploration" },
  },
  {
    id: "tt_build_sell", type: "binary_tension", chapters: ["self_discovery", "alignment"],
    headline: "The thing exists. Now what?",
    supportingText: null,
    left: { label: "Build it better", dim: "implementation_affinity" },
    right: { label: "Get it into hands", dim: "sales_comfort" },
  },
  {
    id: "tt_room", type: "binary_tension", chapters: ["self_discovery", "reflection"],
    headline: "The room is full. The decision is big.",
    supportingText: null,
    left: { label: "Lead the room", dim: "leadership" },
    right: { label: "Shape it quietly", dim: "facilitation" },
  },
  {
    id: "tt_create", type: "binary_tension", chapters: ["self_discovery"],
    headline: "Given the choice:",
    supportingText: null,
    left: { label: "Create from nothing", dim: "originality" },
    right: { label: "Perfect what exists", dim: "detail_orientation" },
  },

  /* ---------- micro scenarios ---------- */
  {
    id: "sc_stuck", type: "scenario_choice", chapters: ["self_discovery"],
    headline: "Everyone is stuck. Nobody knows what happens next.",
    supportingText: "What do you naturally do first?",
    options: [
      { id: "problem", label: "Find the real problem",
        signals: [{ dim: "systems_thinking", delta: .55, weight: .5 }, { dim: "analytical", delta: .4, weight: .35 }] },
      { id: "moving", label: "Get everyone moving",
        signals: [{ dim: "leadership", delta: .55, weight: .5 }, { dim: "initiative", delta: .4, weight: .35 }] },
      { id: "wild", label: "Try something nobody considered",
        signals: [{ dim: "originality", delta: .55, weight: .5 }, { dim: "experimentation", delta: .45, weight: .4 }] },
      { id: "person", label: "Find the person who knows",
        signals: [{ dim: "network", delta: .5, weight: .45 }, { dim: "relationship_building", delta: .4, weight: .35 }] },
    ],
  },
  {
    id: "sc_gift", type: "scenario_choice", chapters: ["self_discovery", "reflection"],
    headline: "A free afternoon appears out of nowhere.",
    supportingText: "Honestly — where does it go?",
    options: [
      { id: "make", label: "Making something",
        signals: [{ dim: "implementation_affinity", delta: .5, weight: .45 }, { dim: "originality", delta: .3, weight: .25 }] },
      { id: "learn", label: "Falling down a rabbit hole",
        signals: [{ dim: "exploration", delta: .5, weight: .45 }, { dim: "abstraction", delta: .35, weight: .3 }] },
      { id: "people", label: "Calling someone interesting",
        signals: [{ dim: "relationship_building", delta: .5, weight: .45 }, { dim: "empathy", delta: .3, weight: .25 }] },
      { id: "order", label: "Clearing the decks",
        signals: [{ dim: "planning", delta: .5, weight: .45 }, { dim: "detail_orientation", delta: .35, weight: .3 }] },
    ],
  },
  {
    id: "sc_praise", type: "scenario_choice", chapters: ["reflection"],
    headline: "Which compliment lands deepest?",
    supportingText: "Not which one you'd say — which one you'd feel.",
    options: [
      { id: "trusted", label: "“I'd trust you with anything.”",
        signals: [{ dim: "persistence", delta: .45, weight: .4 }, { dim: "stability", delta: .3, weight: .25 }] },
      { id: "seen", label: "“Nobody thinks like you.”",
        signals: [{ dim: "originality", delta: .5, weight: .45 }] },
      { id: "moved", label: "“You changed how I see it.”",
        signals: [{ dim: "persuasion", delta: .45, weight: .4 }, { dim: "teaching", delta: .35, weight: .3 }] },
      { id: "made", label: "“You actually made it happen.”",
        signals: [{ dim: "initiative", delta: .45, weight: .4 }, { dim: "velocity", delta: .35, weight: .3 }] },
    ],
  },

  /* ---------- forced rank ---------- */
  {
    id: "fr_protect", type: "forced_rank", chapters: ["self_discovery", "reflection"],
    headline: "You can protect only three.",
    supportingText: "The rest you release — for now.",
    maxSelect: 3,
    options: [
      { id: "freedom", label: "Freedom", signals: [{ dim: "autonomy", delta: .6, weight: .55 }] },
      { id: "mastery", label: "Mastery", signals: [{ dim: "mastery", delta: .6, weight: .55 }] },
      { id: "income", label: "Income", signals: [{ dim: "income_urgency", delta: .55, weight: .5 }, { dim: "revenue_ambition", delta: .3, weight: .25 }] },
      { id: "belonging", label: "Belonging", signals: [{ dim: "relationship_building", delta: .55, weight: .5 }] },
      { id: "impact", label: "Impact", signals: [{ dim: "impact", delta: .6, weight: .55 }] },
      { id: "stability", label: "Stability", signals: [{ dim: "stability", delta: .6, weight: .55 }] },
      { id: "recognition", label: "Recognition", signals: [{ dim: "reputation", delta: .5, weight: .45 }, { dim: "audience", delta: .3, weight: .25 }] },
      { id: "time", label: "Time", signals: [{ dim: "time_availability", delta: .5, weight: .45 }, { dim: "autonomy", delta: .25, weight: .2 }] },
    ],
  },

  /* ---------- playful construction ---------- */
  {
    id: "os_day", type: "object_sort", chapters: ["self_discovery"],
    headline: "Build a day you'd actually enjoy.",
    supportingText: "Pick four pieces.",
    maxSelect: 4,
    options: [
      { id: "deepwork", label: "Deep work", signals: [{ dim: "mastery", delta: .4, weight: .35 }, { dim: "facilitation", delta: -.2, weight: .15 }] },
      { id: "people", label: "People", signals: [{ dim: "relationship_building", delta: .4, weight: .35 }, { dim: "empathy", delta: .25, weight: .2 }] },
      { id: "movement", label: "Movement", signals: [{ dim: "velocity", delta: .3, weight: .25 }] },
      { id: "ideas", label: "Ideas", signals: [{ dim: "abstraction", delta: .4, weight: .35 }] },
      { id: "creating", label: "Creating", signals: [{ dim: "originality", delta: .4, weight: .35 }, { dim: "implementation_affinity", delta: .3, weight: .25 }] },
      { id: "selling", label: "Selling", signals: [{ dim: "sales_comfort", delta: .5, weight: .45 }] },
      { id: "learning", label: "Learning", signals: [{ dim: "exploration", delta: .35, weight: .3 }] },
      { id: "leading", label: "Leading", signals: [{ dim: "leadership", delta: .45, weight: .4 }] },
      { id: "quiet", label: "Quiet", signals: [{ dim: "facilitation", delta: -.3, weight: .25 }, { dim: "stability", delta: .25, weight: .2 }] },
      { id: "competition", label: "Competition", signals: [{ dim: "risk_tolerance", delta: .4, weight: .35 }, { dim: "revenue_ambition", delta: .3, weight: .25 }] },
    ],
  },

  /* ---------- micro reflections ---------- */
  {
    id: "mr_cometo", type: "micro_reflection", chapters: ["reflection"],
    headline: "One sentence.",
    supportingText: "What do people naturally come to you for?",
    placeholder: "They come to me when…",
  },
  {
    id: "mr_smaller", type: "micro_reflection", chapters: ["reflection"],
    headline: "Finish this quietly.",
    supportingText: "What part of your life feels smaller than it should?",
    placeholder: "One honest line…",
  },
  {
    id: "mr_unusual", type: "micro_reflection", chapters: ["reflection", "alignment"],
    headline: "Almost done noticing.",
    supportingText: "What are you unusually good at that you rarely think about?",
    placeholder: "It sounds small, but…",
  },

  /* ---------- alignment practical (conversational) ---------- */
  {
    id: "al_work", type: "scenario_choice", chapters: ["alignment"], practicalKey: "career_stage",
    headline: "Let's put this version of you into the real world.",
    supportingText: "Right now, work looks like…",
    options: [
      { id: "employed_good", label: "A role that mostly works", signals: [{ dim: "stability", delta: .2, weight: .2 }] },
      { id: "employed_stale", label: "A role I've outgrown", signals: [{ dim: "exploration", delta: .3, weight: .25 }] },
      { id: "independent", label: "Already independent", signals: [{ dim: "autonomy", delta: .35, weight: .3 }, { dim: "risk_tolerance", delta: .25, weight: .2 }] },
      { id: "between", label: "Between chapters", signals: [{ dim: "ambiguity_tolerance", delta: .2, weight: .15 }] },
      { id: "studying", label: "Still studying", signals: [] },
    ],
  },
  {
    id: "al_hours", type: "spectrum", chapters: ["alignment"], practicalKey: "hours_per_week",
    headline: "Honestly — how much time could you give something new?",
    supportingText: "Not ideally. Actually.",
    left: { label: "Stolen hours", dim: "time_availability", dir: -1 },
    right: { label: "Real, serious time", dim: "time_availability", dir: 1 },
  },
  {
    id: "al_money", type: "spectrum", chapters: ["alignment"], practicalKey: "money_pressure",
    headline: "And money, right now?",
    supportingText: "This changes what's wise — not what's possible.",
    left: { label: "Breathing room", dim: "income_urgency", dir: -1 },
    right: { label: "Real pressure", dim: "income_urgency", dir: 1 },
  },
  {
    id: "al_risk", type: "scenario_choice", chapters: ["alignment"], practicalKey: "risk_appetite",
    headline: "A door opens. Good odds, real downside.",
    supportingText: "Your honest move:",
    options: [
      { id: "walk", label: "Walk through it", signals: [{ dim: "risk_tolerance", delta: .55, weight: .5 }] },
      { id: "test", label: "Test it from the doorway", signals: [{ dim: "experimentation", delta: .45, weight: .4 }, { dim: "risk_tolerance", delta: .1, weight: .1 }] },
      { id: "prepare", label: "Prepare, then decide", signals: [{ dim: "planning", delta: .45, weight: .4 }, { dim: "risk_tolerance", delta: -.2, weight: .2 }] },
      { id: "hold", label: "Not this season", signals: [{ dim: "risk_tolerance", delta: -.45, weight: .4 }, { dim: "stability", delta: .3, weight: .25 }] },
    ],
  },
  {
    id: "al_assets", type: "object_sort", chapters: ["alignment"], practicalKey: "assets",
    headline: "What do you already carry?",
    supportingText: "Pick everything that's true.",
    maxSelect: 8, minSelect: 1,
    options: [
      { id: "deep_field", label: "Deep knowledge of a field", signals: [{ dim: "domain_expertise", delta: .6, weight: .55 }] },
      { id: "network", label: "People who'd take my call", signals: [{ dim: "network", delta: .55, weight: .5 }] },
      { id: "audience", label: "An audience, even small", signals: [{ dim: "audience", delta: .55, weight: .5 }] },
      { id: "credentials", label: "Credentials that open doors", signals: [{ dim: "credentials", delta: .5, weight: .45 }] },
      { id: "savings", label: "A financial cushion", signals: [{ dim: "capital_availability", delta: .55, weight: .5 }] },
      { id: "craft", label: "A craft people pay for", signals: [{ dim: "implementation_affinity", delta: .45, weight: .4 }] },
      { id: "reputation", label: "A good name where it counts", signals: [{ dim: "reputation", delta: .5, weight: .45 }] },
      { id: "tools", label: "Comfort with new AI tools", signals: [{ dim: "ai_leverage", delta: .55, weight: .5 }, { dim: "adaptability", delta: .35, weight: .3 }] },
    ],
  },
  {
    id: "al_geo", type: "scenario_choice", chapters: ["alignment"], practicalKey: "geography",
    headline: "Where does your life actually happen?",
    supportingText: null,
    options: [
      { id: "anchored", label: "Anchored to one place", signals: [{ dim: "geographic_access", delta: -.2, weight: .2 }] },
      { id: "hub", label: "In or near a major hub", signals: [{ dim: "geographic_access", delta: .5, weight: .45 }] },
      { id: "flexible", label: "Genuinely flexible", signals: [{ dim: "adaptability", delta: .3, weight: .25 }] },
      { id: "online", label: "Mostly online anyway", signals: [{ dim: "ai_leverage", delta: .25, weight: .2 }, { dim: "audience", delta: .15, weight: .1 }] },
    ],
  },
  {
    id: "al_solo", type: "binary_tension", chapters: ["alignment"], practicalKey: "solo_or_team",
    headline: "Your best work tends to happen…",
    supportingText: null,
    left: { label: "Alone, deep", dim: "facilitation", dir: -1 },
    right: { label: "With a small crew", dim: "facilitation", dir: 1 },
  },
];

/* motifs the client can render */
export const MOTIFS = ["mountain", "sea", "city", "library", "workshop", "stage", "garden", "market", "studio", "night", "path", "harbor"];

/* ---------- deterministic reveal composition ---------- */

export function composeReveal(state, kind = "early") {
  const tops = topDims(state, 3, { minConfidence: 0.2 });
  if (tops.length === 0) {
    return {
      lines: ["Interesting.", "You don't reach for the obvious option.", "Let's keep going — something is taking shape."],
      insight: { summary: "resists obvious choices", dims: [] },
    };
  }
  const a = tops[0];
  const contradiction = state.contradictions.find(c => !c.explored);
  if (kind !== "early" && contradiction) {
    const c = state.dimensions[contradiction.dim];
    return {
      lines: [
        "There are two versions of you showing up.",
        `One keeps choosing ${dimPhrase(contradiction.dim, 1)}.`,
        `The other quietly protects ${dimPhrase(contradiction.dim, -1)}.`,
        "That's not noise. That's usually where the interesting part lives.",
      ],
      insight: { summary: `mixed signals on ${contradiction.dim}`, dims: [{ dim: contradiction.dim, dir: Math.sign(c.score) || 1 }], contradiction: contradiction.dim },
    };
  }
  const b = tops[1];
  const lines = ["Interesting.", `You keep choosing ${dimPhrase(a.dim, a.score)}…`];
  if (b) lines.push(`…but never at the cost of ${dimPhrase(b.dim, b.score)}.`);
  else lines.push("…and you don't seem to hesitate about it.");
  return {
    lines,
    insight: { summary: `leans ${a.dim}${b ? " balanced by " + b.dim : ""}`, dims: [{ dim: a.dim, dir: Math.sign(a.score) || 1 }, ...(b ? [{ dim: b.dim, dir: Math.sign(b.score) || 1 }] : [])] },
  };
}

/* ---------- possible lives (deterministic composer) ---------- */

export function composePossibleLives(state) {
  const d = id => state.dimensions[id]?.score || 0;
  const conf = id => state.dimensions[id]?.confidence || 0;
  const builderFit = d("originality") * .3 + d("implementation_affinity") * .3 + d("risk_tolerance") * .2 + d("initiative") * .2;
  const operatorFit = d("systems_thinking") * .3 + d("planning") * .25 + d("stability") * .25 + d("leadership") * .2;
  const independentFit = d("domain_expertise") * .35 + d("autonomy") * .3 + d("sales_comfort") * .2 + d("network") * .15;

  const lives = [
    {
      key: "builder", name: "The Builder", essence: "Create something that didn't exist.",
      fit: builderFit,
      whyYou: "You keep choosing origination — starting from nothing pulls you more than polishing what exists.",
      whyNow: "Small, AI-leveraged products need fewer hands than they ever have.",
      uses: "Your instinct to experiment, your tolerance for the unfinished.",
      requires: "Shipping something rough in public, and surviving the quiet weeks after.",
      friction: "The gap between idea energy and distribution patience.",
      risk: "medium-high", timeToValue: "months, not weeks",
      firstExperiment: "Build the smallest version of one idea in 14 days and put it in front of ten strangers.",
    },
    {
      key: "operator", name: "The Operator", essence: "Become unusually valuable inside something that already moves.",
      fit: operatorFit,
      whyYou: "You see systems — how the pieces connect and where they quietly fail.",
      whyNow: "Organizations are refitting everything around new tools; people who can bridge old process and new leverage are scarce.",
      uses: "Your pattern recognition, your steadiness under other people's chaos.",
      requires: "Choosing one organization or domain and going deep instead of wide.",
      friction: "Autonomy — you'd be trading some of it for compounding position.",
      risk: "low", timeToValue: "weeks",
      firstExperiment: "Identify one broken process where you already work and fix it end-to-end without being asked.",
    },
    {
      key: "independent", name: "The Independent", essence: "Turn what you already know into leverage you own.",
      fit: independentFit,
      whyYou: "You carry expertise people already borrow — you've just never priced it.",
      whyNow: "Distribution costs almost nothing; a small reputation compounds fast.",
      uses: "Your judgment, your network, the pattern of people already coming to you.",
      requires: "Getting comfortable asking for money for what you'd give away.",
      friction: "Selling yourself may feel louder than you like to live.",
      risk: "medium", timeToValue: "first paid engagement can be near-term",
      firstExperiment: "Offer one person a small paid version of the help you already give free.",
    },
  ];
  lives.sort((a, b) => b.fit - a.fit);
  return lives.map(l => ({ ...l, confidence: Math.round(40 + 45 * Math.max(0, Math.min(1, (l.fit + 1) / 2))) }));
}

/* ---------- final synthesis (deterministic composer) ---------- */

export function composeFinal(state) {
  const tops = topDims(state, 5, { minConfidence: 0.15 });
  const protectDims = topDims(state, 3, { minConfidence: 0.15, families: ["energy", "economic"] });
  const leverage = topDims(state, 2, { minConfidence: 0.15, families: ["leverage", "ai_era"] });
  const contradiction = state.contradictions[0];
  const p = state.practicalContext || {};

  const mirror = [
    { label: "Your natural energy", text: tops[0] ? `You move toward ${dimPhrase(tops[0].dim, tops[0].score)} — it shows up in almost everything you chose.` : "You choose carefully, and not by template." },
    { label: "How you create value", text: tops[1] ? `Your value concentrates where ${dimPhrase(tops[1].dim, tops[1].score)} matters more than speed or polish.` : "You create value by noticing what others walk past." },
    { label: "What you protect", text: protectDims[0] ? `When things get real, you protect ${dimPhrase(protectDims[0].dim, protectDims[0].score)} before anything else.` : "You protect optionality — the right to change your mind." },
    { label: "Your unusual edge", text: leverage[0] ? `You underrate ${dimPhrase(leverage[0].dim, leverage[0].score)} — it appeared quietly and repeatedly.` : "Your edge is honesty about what you don't know — rarer than it sounds." },
    { label: "What may be holding you back", text: contradiction ? `The tug between ${dimPhrase(contradiction.dim, 1)} and ${dimPhrase(contradiction.dim, -1)} — you've been treating it as a flaw. It's a constraint to design around.` : "Waiting for certainty that this kind of choice never provides." },
  ];
  if (p.money_pressure !== undefined || p.hours_per_week !== undefined) {
    mirror.splice(4, 0, { label: "Your current reality", text: "Your time and pressure aren't obstacles to the plan. They are the plan's shape." });
  }

  const lives = state.possibleLives?.length ? state.possibleLives : composePossibleLives(state);
  const chosen = state.practicalContext?.resonantLife;
  const first = lives.find(l => l.key === chosen) || lives[0];

  return {
    opening: [
      "At the beginning, you answered by instinct.",
      "Later, you corrected the picture yourself.",
      "At first, some of it looked contradictory.",
      "It isn't.",
    ],
    mirror,
    map: lives,
    nextAction: {
      headline: "One small next step",
      text: first.firstExperiment,
      note: "Not a life plan. Just the next honest experiment.",
    },
  };
}
