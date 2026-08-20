"""Interpretable human-state taxonomy. Scores run -1..1. Phrases feed the
deterministic reveal composer — never shown as raw scores.

The phrases are written to be understood at a glance by someone who has never
thought about any of this before. They get slotted into generated sentences
("you chose X", "you get X and give up Y"), so each one is a plain noun phrase
a person would actually say out loud — not an image, not a metaphor.
"""

DIMENSIONS: dict[str, dict] = {
    # energy
    "autonomy": {"family": "energy", "pos": "setting your own hours and rules", "neg": "being told what the plan is"},
    "purpose": {"family": "energy", "pos": "work that helps someone", "neg": "work that just pays well"},
    "mastery": {"family": "energy", "pos": "getting very good at one thing", "neg": "being able to do lots of things"},
    "stability": {"family": "energy", "pos": "money you can count on every month", "neg": "not knowing what comes next"},
    "exploration": {"family": "energy", "pos": "trying things you've never done", "neg": "getting deeper into what you know"},
    "impact": {"family": "energy", "pos": "seeing your work change something for people", "neg": "work that stays between you and the task"},
    "income_urgency": {"family": "energy", "pos": "needing money soon", "neg": "having time before money matters"},
    # cognitive
    "systems_thinking": {"family": "cognitive", "pos": "seeing how the pieces connect", "neg": "taking things one at a time"},
    "pattern_recognition": {"family": "cognitive", "pos": "noticing what keeps happening", "neg": "treating each case as new"},
    "analytical": {"family": "cognitive", "pos": "taking things apart to understand them", "neg": "going with what feels right"},
    "abstraction": {"family": "cognitive", "pos": "ideas and plans", "neg": "things you can see and touch"},
    "ambiguity_tolerance": {"family": "cognitive", "pos": "starting before you know everything", "neg": "waiting until it's clear"},
    # social
    "persuasion": {"family": "social", "pos": "talking people round", "neg": "letting the work speak for itself"},
    "empathy": {"family": "social", "pos": "reading how people actually feel", "neg": "going on what people actually do"},
    "teaching": {"family": "social", "pos": "explaining things until they click", "neg": "just getting on with it yourself"},
    "facilitation": {"family": "social", "pos": "getting a group working properly", "neg": "working best on your own"},
    "leadership": {"family": "social", "pos": "being the one who decides", "neg": "having a say without running it"},
    "relationship_building": {"family": "social", "pos": "people you stay in touch with for years", "neg": "clean working relationships that end when the job does"},
    # execution
    "initiative": {"family": "execution", "pos": "starting before anyone asks", "neg": "waiting for the right moment"},
    "persistence": {"family": "execution", "pos": "sticking with it after it stops being fun", "neg": "knowing when to walk away"},
    "planning": {"family": "execution", "pos": "planning it out before you start", "neg": "working it out as you go"},
    "velocity": {"family": "execution", "pos": "getting it done fast and rough", "neg": "taking the time to get it right"},
    "detail_orientation": {"family": "execution", "pos": "getting the last five percent right", "neg": "getting the main thing done"},
    # creative
    "originality": {"family": "creative", "pos": "trying what nobody has tried", "neg": "doing what already works"},
    "storytelling": {"family": "creative", "pos": "telling the story around the work", "neg": "just giving people the facts"},
    "synthesis": {"family": "creative", "pos": "putting ideas together from different places", "neg": "getting one thing really right"},
    "experimentation": {"family": "creative", "pos": "testing it to find out", "neg": "deciding first, then doing it"},
    "aesthetic_sensitivity": {"family": "creative", "pos": "how something looks and feels", "neg": "whether it does the job"},
    # economic
    "risk_tolerance": {"family": "economic", "pos": "bets you could actually lose on", "neg": "moves where you can't lose much"},
    "sales_comfort": {"family": "economic", "pos": "asking people for the money", "neg": "hoping people work out what it's worth"},
    "revenue_ambition": {"family": "economic", "pos": "building something that makes real money", "neg": "earning enough, steadily"},
    "capital_availability": {"family": "economic", "pos": "money you could put in tomorrow", "neg": "starting with almost nothing"},
    "time_availability": {"family": "economic", "pos": "real hours free each week", "neg": "scraps of time between everything else"},
    # leverage
    "domain_expertise": {"family": "leverage", "pos": "knowing your field inside out", "neg": "coming at it fresh"},
    "network": {"family": "leverage", "pos": "people who'd take your call", "neg": "starting your contacts from scratch"},
    "credentials": {"family": "leverage", "pos": "qualifications on paper", "neg": "proof from work you've actually done"},
    "audience": {"family": "leverage", "pos": "people who already follow you", "neg": "nobody listening yet"},
    "reputation": {"family": "leverage", "pos": "a name people already know", "neg": "starting where nobody knows you"},
    "geographic_access": {"family": "leverage", "pos": "living where the work happens", "neg": "being able to work from anywhere"},
    # ai-era
    "adaptability": {"family": "ai_era", "pos": "picking up new tools as things change", "neg": "getting better at one steady craft"},
    "ai_leverage": {"family": "ai_era", "pos": "doing far more with new tools", "neg": "work that still needs a person"},
    "implementation_affinity": {"family": "ai_era", "pos": "building the thing and shipping it", "neg": "working out how it should work"},
    "automation_exposure": {"family": "ai_era", "pos": "work a machine could soon do", "neg": "work machines are bad at"},
}

FAMILIES = sorted({d["family"] for d in DIMENSIONS.values()})

CHAPTER_FOCUS = {
    "SELF_DISCOVERY": ["energy", "creative", "social", "cognitive"],
    "REFLECTION": ["cognitive", "execution", "social", "energy"],
    "ALIGNMENT": ["economic", "leverage", "ai_era", "execution"],
    "TRANSFORMATION": [],
}


def is_dim(dim: str) -> bool:
    return dim in DIMENSIONS


# short memory-fragment words (screen memory, never analytics tags)
FRAGMENTS = {
    "autonomy": ("your own hours", "a clear plan"), "purpose": ("work that helps", "work that pays"),
    "mastery": ("being great at one thing", "being able to do lots"),
    "stability": ("steady money", "not knowing what's next"),
    "exploration": ("new things", "going deeper"), "impact": ("seeing it help someone", "quiet work"),
    "income_urgency": ("needing money soon", "having time"),
    "systems_thinking": ("how it all connects", "one thing at a time"),
    "pattern_recognition": ("what keeps happening", "a fresh look"),
    "analytical": ("taking it apart", "going on feel"),
    "abstraction": ("ideas", "things you can touch"),
    "ambiguity_tolerance": ("starting early", "waiting for clarity"),
    "persuasion": ("talking people round", "letting work speak"),
    "empathy": ("how people feel", "what people do"),
    "teaching": ("making it click", "just doing it"), "facilitation": ("running the room", "working alone"),
    "leadership": ("being in charge", "having a say"),
    "relationship_building": ("people you keep", "clean handovers"),
    "initiative": ("starting first", "waiting for the moment"),
    "persistence": ("sticking with it", "knowing when to stop"),
    "planning": ("planning first", "working it out live"),
    "velocity": ("fast and rough", "slow and right"),
    "detail_orientation": ("the last five percent", "the main thing done"),
    "originality": ("what nobody's tried", "what already works"),
    "storytelling": ("the story", "the facts"),
    "synthesis": ("mixing ideas", "one thing done right"),
    "experimentation": ("testing it", "deciding first"),
    "aesthetic_sensitivity": ("how it looks", "that it works"),
    "risk_tolerance": ("real bets", "safe moves"),
    "sales_comfort": ("asking for money", "hoping they notice"),
    "revenue_ambition": ("real money", "enough, steadily"),
    "capital_availability": ("money to put in", "starting with nothing"),
    "time_availability": ("real hours free", "scraps of time"),
    "domain_expertise": ("knowing it inside out", "fresh eyes"),
    "network": ("people who'd take your call", "starting from scratch"),
    "credentials": ("qualifications", "proof from doing"),
    "audience": ("people following you", "nobody listening yet"),
    "reputation": ("a name people know", "nobody knows you yet"),
    "geographic_access": ("where the work is", "anywhere"),
    "adaptability": ("picking up new tools", "one steady craft"),
    "ai_leverage": ("doing more with tools", "work that needs a person"),
    "implementation_affinity": ("building it", "designing it"),
    "automation_exposure": ("a machine could do it", "machines are bad at it"),
}


def dim_fragment(dim: str, score: float) -> str:
    pair = FRAGMENTS.get(dim)
    if not pair:
        return dim.replace("_", " ")
    return pair[0] if score >= 0 else pair[1]


def dim_phrase(dim: str, score: float) -> str:
    meta = DIMENSIONS.get(dim)
    if not meta:
        return dim
    return meta["pos"] if score >= 0 else meta["neg"]
