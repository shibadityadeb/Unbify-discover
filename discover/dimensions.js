/* Profile dimension registry. Scores run -1..1; each dimension carries human
   phrases used by fallback reveal composition (never shown as raw scores). */

export const DIMENSIONS = {
  /* energy */
  autonomy:            { family: "energy", pos: "room to move on your own terms", neg: "clear structure around you" },
  purpose:             { family: "energy", pos: "work that means something beyond itself", neg: "work that simply works" },
  mastery:             { family: "energy", pos: "getting unreasonably good at one thing", neg: "staying wide and adaptable" },
  stability:           { family: "energy", pos: "solid ground under your feet", neg: "open, unsettled horizons" },
  exploration:         { family: "energy", pos: "the unfamiliar", neg: "the familiar, made deeper" },
  impact:              { family: "energy", pos: "visible effect on other people", neg: "quiet, self-contained work" },
  income_urgency:      { family: "energy", pos: "money pressure that is real right now", neg: "financial breathing room" },
  /* cognitive */
  systems_thinking:    { family: "cognitive", pos: "seeing how the pieces connect", neg: "taking things one at a time" },
  pattern_recognition: { family: "cognitive", pos: "noticing what repeats", neg: "treating each case fresh" },
  analytical:          { family: "cognitive", pos: "taking things apart to understand them", neg: "trusting the feel of things" },
  abstraction:         { family: "cognitive", pos: "ideas and models", neg: "the concrete and tangible" },
  ambiguity_tolerance: { family: "cognitive", pos: "moving before the picture is complete", neg: "waiting for clarity first" },
  /* social */
  persuasion:          { family: "social", pos: "moving people toward a view", neg: "letting the work speak" },
  empathy:             { family: "social", pos: "reading what people actually feel", neg: "focusing on what people do" },
  teaching:            { family: "social", pos: "making things click for others", neg: "keeping your process private" },
  facilitation:        { family: "social", pos: "making a room work", neg: "working best solo" },
  leadership:          { family: "social", pos: "taking the front when it matters", neg: "shaping things from the side" },
  relationship_building:{ family: "social", pos: "long threads with people", neg: "clean, bounded collaborations" },
  /* execution */
  initiative:          { family: "execution", pos: "starting before being asked", neg: "moving when the moment is right" },
  persistence:         { family: "execution", pos: "staying long after it stops being fun", neg: "knowing when to fold" },
  planning:            { family: "execution", pos: "the map before the road", neg: "the road revealing the map" },
  velocity:            { family: "execution", pos: "fast, rough, and real", neg: "slow, considered, and right" },
  detail_orientation:  { family: "execution", pos: "the last five percent", neg: "the big strokes" },
  /* creative */
  originality:         { family: "creative", pos: "what nobody has tried", neg: "what is proven to work" },
  storytelling:        { family: "creative", pos: "giving things a narrative", neg: "letting facts stand alone" },
  synthesis:           { family: "creative", pos: "combining far-apart things", neg: "perfecting one lane" },
  experimentation:     { family: "creative", pos: "testing to find out", neg: "deciding before acting" },
  aesthetic_sensitivity:{ family: "creative", pos: "how things look and feel", neg: "whether things function" },
  /* economic */
  risk_tolerance:      { family: "economic", pos: "bets with real downside", neg: "protected moves" },
  sales_comfort:       { family: "economic", pos: "asking for the money", neg: "letting value be discovered" },
  revenue_ambition:    { family: "economic", pos: "building something that pays seriously", neg: "enough, sustainably" },
  capital_availability:{ family: "economic", pos: "resources ready to deploy", neg: "starting lean" },
  time_availability:   { family: "economic", pos: "real hours to invest", neg: "stolen margins of time" },
  /* leverage */
  domain_expertise:    { family: "leverage", pos: "deep knowledge of a field", neg: "beginner's eyes" },
  network:             { family: "leverage", pos: "people who would pick up the call", neg: "building connections from scratch" },
  credentials:         { family: "leverage", pos: "formal proof of ability", neg: "proof by doing" },
  audience:            { family: "leverage", pos: "people already listening", neg: "no stage yet" },
  reputation:          { family: "leverage", pos: "a name that precedes you", neg: "a clean slate" },
  geographic_access:   { family: "leverage", pos: "being where things happen", neg: "working from anywhere" },
  /* ai-era */
  adaptability:        { family: "ai_era", pos: "rebuilding your toolkit as the ground moves", neg: "compounding one stable craft" },
  ai_leverage:         { family: "ai_era", pos: "multiplying yourself with new tools", neg: "value that stays deeply human" },
  implementation_affinity:{ family: "ai_era", pos: "actually shipping the thing", neg: "designing the idea of the thing" },
  automation_exposure: { family: "ai_era", pos: "work a machine could soon do", neg: "work machines struggle with" },
};

export const FAMILIES = [...new Set(Object.values(DIMENSIONS).map(d => d.family))];

export function isDim(id) { return Object.prototype.hasOwnProperty.call(DIMENSIONS, id); }

/* chapter -> families most worth exploring */
export const CHAPTER_FOCUS = {
  self_discovery: ["energy", "creative", "social", "cognitive"],
  reflection: ["cognitive", "execution", "social", "energy"],
  alignment: ["economic", "leverage", "ai_era", "execution"],
  transformation: [],
};
