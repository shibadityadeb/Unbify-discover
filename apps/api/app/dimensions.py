"""Interpretable human-state taxonomy. Scores run -1..1. Phrases feed the
deterministic reveal composer — never shown as raw scores."""

DIMENSIONS: dict[str, dict] = {
    # energy
    "autonomy": {"family": "energy", "pos": "room to move on your own terms", "neg": "clear structure around you"},
    "purpose": {"family": "energy", "pos": "work that means something beyond itself", "neg": "work that simply works"},
    "mastery": {"family": "energy", "pos": "getting unreasonably good at one thing", "neg": "staying wide and adaptable"},
    "stability": {"family": "energy", "pos": "solid ground under your feet", "neg": "open, unsettled horizons"},
    "exploration": {"family": "energy", "pos": "the unfamiliar", "neg": "the familiar, made deeper"},
    "impact": {"family": "energy", "pos": "visible effect on other people", "neg": "quiet, self-contained work"},
    "income_urgency": {"family": "energy", "pos": "money pressure that is real right now", "neg": "financial breathing room"},
    # cognitive
    "systems_thinking": {"family": "cognitive", "pos": "seeing how the pieces connect", "neg": "taking things one at a time"},
    "pattern_recognition": {"family": "cognitive", "pos": "noticing what repeats", "neg": "treating each case fresh"},
    "analytical": {"family": "cognitive", "pos": "taking things apart to understand them", "neg": "trusting the feel of things"},
    "abstraction": {"family": "cognitive", "pos": "ideas and models", "neg": "the concrete and tangible"},
    "ambiguity_tolerance": {"family": "cognitive", "pos": "moving before the picture is complete", "neg": "waiting for clarity first"},
    # social
    "persuasion": {"family": "social", "pos": "moving people toward a view", "neg": "letting the work speak"},
    "empathy": {"family": "social", "pos": "reading what people actually feel", "neg": "focusing on what people do"},
    "teaching": {"family": "social", "pos": "making things click for others", "neg": "keeping your process private"},
    "facilitation": {"family": "social", "pos": "making a room work", "neg": "working best solo"},
    "leadership": {"family": "social", "pos": "taking the front when it matters", "neg": "shaping things from the side"},
    "relationship_building": {"family": "social", "pos": "long threads with people", "neg": "clean, bounded collaborations"},
    # execution
    "initiative": {"family": "execution", "pos": "starting before being asked", "neg": "moving when the moment is right"},
    "persistence": {"family": "execution", "pos": "staying long after it stops being fun", "neg": "knowing when to fold"},
    "planning": {"family": "execution", "pos": "the map before the road", "neg": "the road revealing the map"},
    "velocity": {"family": "execution", "pos": "fast, rough, and real", "neg": "slow, considered, and right"},
    "detail_orientation": {"family": "execution", "pos": "the last five percent", "neg": "the big strokes"},
    # creative
    "originality": {"family": "creative", "pos": "what nobody has tried", "neg": "what is proven to work"},
    "storytelling": {"family": "creative", "pos": "giving things a narrative", "neg": "letting facts stand alone"},
    "synthesis": {"family": "creative", "pos": "combining far-apart things", "neg": "perfecting one lane"},
    "experimentation": {"family": "creative", "pos": "testing to find out", "neg": "deciding before acting"},
    "aesthetic_sensitivity": {"family": "creative", "pos": "how things look and feel", "neg": "whether things function"},
    # economic
    "risk_tolerance": {"family": "economic", "pos": "bets with real downside", "neg": "protected moves"},
    "sales_comfort": {"family": "economic", "pos": "asking for the money", "neg": "letting value be discovered"},
    "revenue_ambition": {"family": "economic", "pos": "building something that pays seriously", "neg": "enough, sustainably"},
    "capital_availability": {"family": "economic", "pos": "resources ready to deploy", "neg": "starting lean"},
    "time_availability": {"family": "economic", "pos": "real hours to invest", "neg": "stolen margins of time"},
    # leverage
    "domain_expertise": {"family": "leverage", "pos": "deep knowledge of a field", "neg": "beginner's eyes"},
    "network": {"family": "leverage", "pos": "people who would pick up the call", "neg": "building connections from scratch"},
    "credentials": {"family": "leverage", "pos": "formal proof of ability", "neg": "proof by doing"},
    "audience": {"family": "leverage", "pos": "people already listening", "neg": "no stage yet"},
    "reputation": {"family": "leverage", "pos": "a name that precedes you", "neg": "a clean slate"},
    "geographic_access": {"family": "leverage", "pos": "being where things happen", "neg": "working from anywhere"},
    # ai-era
    "adaptability": {"family": "ai_era", "pos": "rebuilding your toolkit as the ground moves", "neg": "compounding one stable craft"},
    "ai_leverage": {"family": "ai_era", "pos": "multiplying yourself with new tools", "neg": "value that stays deeply human"},
    "implementation_affinity": {"family": "ai_era", "pos": "actually shipping the thing", "neg": "designing the idea of the thing"},
    "automation_exposure": {"family": "ai_era", "pos": "work a machine could soon do", "neg": "work machines struggle with"},
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
    "autonomy": ("room to move", "solid rails"), "purpose": ("meaning", "what works"),
    "mastery": ("mastery", "range"), "stability": ("solid ground", "open horizon"),
    "exploration": ("the unfamiliar", "the familiar"), "impact": ("visible effect", "quiet work"),
    "income_urgency": ("real pressure", "breathing room"),
    "systems_thinking": ("the connections", "one thing at a time"),
    "pattern_recognition": ("what repeats", "fresh eyes"), "analytical": ("taking apart", "feel"),
    "abstraction": ("ideas", "the tangible"), "ambiguity_tolerance": ("moving early", "clarity first"),
    "persuasion": ("moving people", "the work speaks"), "empathy": ("what people feel", "what people do"),
    "teaching": ("making it click", "private process"), "facilitation": ("the room", "solo depth"),
    "leadership": ("the front", "the side"), "relationship_building": ("long threads", "clean bounds"),
    "initiative": ("starting first", "right moment"), "persistence": ("staying", "folding well"),
    "planning": ("the map", "the road"), "velocity": ("fast and real", "slow and right"),
    "detail_orientation": ("the last 5%", "big strokes"),
    "originality": ("untried things", "proven things"), "storytelling": ("narrative", "plain facts"),
    "synthesis": ("combining", "one lane"), "experimentation": ("testing", "deciding"),
    "aesthetic_sensitivity": ("how it feels", "that it works"),
    "risk_tolerance": ("real bets", "protected moves"), "sales_comfort": ("the ask", "discovered value"),
    "revenue_ambition": ("real wealth", "enough"), "capital_availability": ("resources", "lean start"),
    "time_availability": ("real hours", "stolen margins"),
    "domain_expertise": ("deep knowledge", "beginner's eyes"), "network": ("people who answer", "new doors"),
    "credentials": ("proof on paper", "proof by doing"), "audience": ("people listening", "no stage yet"),
    "reputation": ("a known name", "clean slate"), "geographic_access": ("where it happens", "anywhere"),
    "adaptability": ("retooling", "compounding"), "ai_leverage": ("multiplied", "deeply human"),
    "implementation_affinity": ("shipping", "designing"), "automation_exposure": ("exposed", "durable"),
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
