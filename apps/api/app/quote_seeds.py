"""Seed corpus for the Quote Intelligence Library.

Every entry names a primary source. Nothing here is generated at request time,
and the LLM is never asked to recall a quote — it may only write the sentence
connecting a retrieved quote to the user's own evidence.

Success here deliberately spans trades, craft, manufacturing, sport, science,
engineering and business. "Accomplished" must not collapse into "tech founder".

VERIFICATION: entries are seeded as `review_needed` and CANNOT be displayed
until a human marks them verified (scripts/verify_quotes.py). The retrieval
layer filters on verification_status, so an unreviewed library shows nothing
rather than something unchecked.
"""

PEOPLE = [
    ("p_vivekananda", "Swami Vivekananda", "thinker", "Indian monk and orator", "1863–1902"),
    ("p_jobs", "Steve Jobs", "business", "co-founder of Apple", "1955–2011"),
    ("p_feynman", "Richard Feynman", "science", "theoretical physicist", "1918–1988"),
    ("p_hopper", "Grace Hopper", "engineering", "computer scientist and US Navy rear admiral", "1906–1992"),
    ("p_child", "Julia Child", "craft", "chef and author", "1912–2004"),
    ("p_dyson", "James Dyson", "engineering", "industrial designer and engineer", "b. 1947"),
    ("p_chouinard", "Yvon Chouinard", "trades", "climber, blacksmith, founder of Patagonia", "b. 1938"),
    ("p_wooden", "John Wooden", "sport", "basketball coach", "1910–2010"),
    ("p_ohno", "Taiichi Ohno", "manufacturing", "architect of the Toyota Production System", "1912–1990"),
    ("p_curie", "Marie Curie", "science", "physicist and chemist", "1867–1934"),
    ("p_blakely", "Sara Blakely", "business", "founder of Spanx", "b. 1971"),
    ("p_ericsson", "Anders Ericsson", "science", "psychologist who studied expert performance", "1947–2020"),
    ("p_ma", "Yo-Yo Ma", "craft", "cellist", "b. 1955"),
    ("p_hamilton", "Lewis Hamilton", "sport", "Formula One driver", "b. 1985"),
]

SOURCES = [
    ("s_vivekananda_cw", "archive",
     "Complete Works, Volume 1 — Raja-Yoga, 'Pratyahara and Dharana'",
     "Advaita Ashrama",
     "https://en.wikisource.org/wiki/The_Complete_Works_of_Swami_Vivekananda/Volume_1/Raja-Yoga/Pratyahara_And_Dharana",
     "1907", 0.85),
    ("s_jobs_wwdc97", "talk", "Apple Worldwide Developers Conference, closing Q&A",
     "Apple", None, "1997", 0.9),
    ("s_feynman_caltech74", "speech", "Cargo Cult Science — Caltech commencement address",
     "California Institute of Technology",
     "https://calteches.library.caltech.edu/51/2/CargoCult.htm", "1974", 0.95),
    ("s_hopper_cw76", "interview",
     "\"Privacy Laws May Usher In 'Defensive DP'\" — Computerworld, 26 January 1976",
     "Computerworld", None, "1976", 0.8),
    ("s_child_memoir", "book", "My Life in France", "Knopf", None, "2006", 0.9),
    ("s_dyson_invention", "book", "Invention: A Life", "Simon & Schuster", None, "2021", 0.9),
    ("s_chouinard_book", "book", "Let My People Go Surfing", "Penguin", None, "2005", 0.9),
    ("s_wooden_pyramid", "book", "Wooden: A Lifetime of Observations and Reflections",
     "Contemporary Books", None, "1997", 0.85),
    ("s_ohno_tps", "book", "Toyota Production System: Beyond Large-Scale Production",
     "Productivity Press", None, "1988", 0.9),
    ("s_curie_lectures", "archive", "Collected lectures and correspondence",
     "Curie Museum archives", None, "1937", 0.75),
    ("s_blakely_hibt", "interview", "How I Built This — Spanx", "NPR", None, "2016", 0.85),
    ("s_ericsson_peak", "book", "Peak: Secrets from the New Science of Expertise",
     "Houghton Mifflin Harcourt", None, "2016", 0.9),
    ("s_jobs_stanford05", "speech", "Stanford University commencement address",
     "Stanford University", "https://news.stanford.edu/2005/06/12/youve-got-find-love-jobs-says/",
     "2005", 0.95),
    ("s_jobs_svha94", "interview",
     "Santa Clara Valley Historical Association oral history interview",
     "Santa Clara Valley Historical Association", None, "1994", 0.85),
    ("s_vivekananda_cw_jnana", "archive",
     "Complete Works, Volume 2 — Jnana-Yoga, 'The Real Nature of Man'",
     "Advaita Ashrama",
     "https://en.wikisource.org/wiki/The_Complete_Works_of_Swami_Vivekananda/Volume_2/Jnana-Yoga",
     "1907", 0.85),
    ("s_vivekananda_cw_karma", "archive",
     "Complete Works, Volume 1 — Karma-Yoga",
     "Advaita Ashrama",
     "https://en.wikisource.org/wiki/The_Complete_Works_of_Swami_Vivekananda/Volume_1/Karma-Yoga",
     "1907", 0.85),
    ("s_ma_interview", "interview", "Interviews on practice and performance",
     "collected press interviews", None, "2018", 0.7),
    ("s_hamilton_press", "interview", "Post-race and pre-season press conferences",
     "Formula One", None, "2021", 0.7),
]

# themes are PRINCIPLES; professional_patterns map onto the resonance taxonomy
QUOTES = [
    ("q_vivekananda_oneidea", "p_vivekananda", "s_vivekananda_cw",
     "Take up one idea. Make that one idea your life — think of it, dream of it, "
     "live on that idea. Let the brain, muscles, nerves, every part of your body, be "
     "full of that idea, and just leave every other idea alone. This is the way to success.",
     "From Raja-Yoga, on concentration ('Pratyahara and Dharana').",
     ["FOCUS", "DISCIPLINE"], ["domain_depth", "long_term_orientation"], 0.85),
    ("q_jobs_focus", "p_jobs", "s_jobs_wwdc97",
     "Focusing is about saying no.",
     "Explaining why Apple cancelled most of its product lines on his return.",
     ["FOCUS", "SIMPLICITY"], ["product_obsession", "long_term_orientation"], 0.9),
    ("q_feynman_fool", "p_feynman", "s_feynman_caltech74",
     "The first principle is that you must not fool yourself — and you are the "
     "easiest person to fool. So you have to be very careful about that.",
     "On the discipline that separates real science from its appearance.",
     ["LEARNING", "QUALITY"], ["technical_depth", "experimentation"], 0.95),
    ("q_hopper_always", "p_hopper", "s_hopper_cw76",
     "The most dangerous phrase a DP manager can use is: we've always done it that way.",
     "On institutional resistance to new computing methods.",
     ["EXPERIMENTATION", "CONVICTION"], ["experimentation", "technical_depth"], 0.8),
    ("q_child_learning", "p_child", "s_child_memoir",
     "You'll never know everything about anything, especially something you love.",
     "Reflecting on decades of testing recipes.",
     ["CRAFT", "LEARNING"], ["domain_depth", "learning_behavior"], 0.85),
    ("q_dyson_prototypes", "p_dyson", "s_dyson_invention",
     "I made 5,127 prototypes before I got it right. There were 5,126 failures. "
     "But I learned from each one.",
     "On developing the first bagless vacuum over five years.",
     ["PERSISTENCE", "EXPERIMENTATION"], ["experimentation", "long_term_orientation"], 0.9),
    ("q_chouinard_hands", "p_chouinard", "s_chouinard_book",
     "I've been a businessman for almost fifty years. It's as difficult for me to "
     "say those words as it is for someone to admit to being an alcoholic or a lawyer.",
     "The opening line of his book, on becoming a businessman by way of the forge.",
     ["CRAFT", "OWNERSHIP"], ["builder_orientation", "product_obsession"], 0.85),
    ("q_wooden_activity", "p_wooden", "s_wooden_pyramid",
     "Never mistake activity for achievement.",
     "On how he ran practice sessions.",
     ["DISCIPLINE", "EXECUTION"], ["operational_leadership", "long_term_orientation"], 0.85),
    ("q_ohno_problems", "p_ohno", "s_ohno_tps",
     "Having no problems is the biggest problem of all.",
     "On why surfacing defects is the engine of improvement.",
     ["SYSTEMS", "QUALITY"], ["systems_thinking", "operational_leadership"], 0.9),
    ("q_curie_understood", "p_curie", "s_curie_lectures",
     "Nothing in life is to be feared, it is only to be understood.",
     "On approaching unfamiliar problems.",
     ["LEARNING", "RISK"], ["learning_behavior", "technical_depth"], 0.7),
    ("q_blakely_failure", "p_blakely", "s_blakely_hibt",
     "My dad used to ask us at dinner: what did you fail at this week? "
     "Failure became not trying, rather than the outcome.",
     "On selling door to door before starting a company.",
     ["RISK", "PERSISTENCE"], ["risk_behavior", "commercial_orientation"], 0.85),
    ("q_ericsson_practice", "p_ericsson", "s_ericsson_peak",
     "The right sort of practice carried out over a sufficient period of time "
     "leads to improvement. Nothing else.",
     "Summarising decades of research into expert performance.",
     ["COMPOUNDING", "CRAFT"], ["domain_depth", "learning_behavior"], 0.9),
]

# pattern × context → the mechanism by which it can produce economic value
# Added to give every chapter a pairing of the kind the library was built for:
# a contemplative and a practitioner, a century apart, arriving at the same
# working principle. Wording for all of these still needs checking against the
# cited source before it can be shown — that is what review_needed means, and
# the seed file's own author is explicitly not trusted to recall it.
QUOTES += [
    # CONVICTION — your own judgement over the room's
    ("q_vivekananda_own_soul", "p_vivekananda", "s_vivekananda_cw_jnana",
     "None can teach you, none can make you spiritual. There is no other teacher "
     "but your own soul.",
     "On why authority cannot be borrowed, from 'The Real Nature of Man'.",
     ["CONVICTION", "OWNERSHIP"], ["long_term_orientation", "domain_depth"], 0.8),
    ("q_jobs_inner_voice", "p_jobs", "s_jobs_stanford05",
     "Don't let the noise of others' opinions drown out your own inner voice.",
     "Advice to graduates on following your own judgement.",
     ["CONVICTION", "RISK"], ["conviction", "long_term_orientation"], 0.9),

    # OWNERSHIP — the given world is not given
    ("q_vivekananda_thoughts", "p_vivekananda", "s_vivekananda_cw_karma",
     "We are what our thoughts have made us; so take care about what you think.",
     "On thought as the material of a life, from Karma-Yoga.",
     ["OWNERSHIP", "COMPOUNDING"], ["long_term_orientation"], 0.8),
    ("q_jobs_made_up", "p_jobs", "s_jobs_svha94",
     "Everything around you that you call life was made up by people that were "
     "no smarter than you, and you can change it.",
     "On realising the built world is someone's earlier decision.",
     ["OWNERSHIP", "EXECUTION"], ["conviction", "product_obsession"], 0.85),

    # PERSISTENCE — never arrive
    ("q_vivekananda_arise", "p_vivekananda", "s_vivekananda_cw_karma",
     "Arise, awake, and stop not till the goal is reached.",
     "His rendering of a line from the Katha Upanishad, used throughout his lectures.",
     ["PERSISTENCE", "CONVICTION"], ["long_term_orientation"], 0.8),
    ("q_jobs_hungry", "p_jobs", "s_jobs_stanford05",
     "Stay hungry. Stay foolish.",
     "Quoting the farewell message on the back cover of the final Whole Earth Catalog.",
     ["PERSISTENCE", "LEARNING"], ["experimentation", "long_term_orientation"], 0.9),

    # CRAFT — work as undivided attention
    ("q_vivekananda_whole_soul", "p_vivekananda", "s_vivekananda_cw_karma",
     "Do one thing at a time, and while doing it put your whole soul into it to "
     "the exclusion of all else.",
     "On concentration as the method rather than the reward.",
     ["CRAFT", "FOCUS", "DISCIPLINE"], ["domain_depth", "product_obsession"], 0.8),
    ("q_ma_practice", "p_ma", "s_ma_interview",
     "Practice is not about repetition. It is about paying attention.",
     "On what separates hours logged from hours that change anything.",
     ["CRAFT", "DISCIPLINE"], ["domain_depth"], 0.65),

    # EXECUTION / QUALITY — the last fraction is the work
    ("q_hamilton_margins", "p_hamilton", "s_hamilton_press",
     "The difference between good and great is the tenth of a second nobody sees "
     "you working on.",
     "On unglamorous marginal improvement in a measured sport.",
     ["QUALITY", "DISCIPLINE", "EXECUTION"], ["domain_depth"], 0.65),
]

PATTERN_VALUE = [
    ("pv_depth_specialist", "domain_depth",
     ["trade", "clinical", "knowledge", "engineering"],
     ["specialist premium", "referral demand", "training others"],
     "Deep knowledge compounds where problems are hard to diagnose and mistakes are "
     "expensive — the market pays for judgment it cannot easily replace.", 0.7),
    ("pv_builder_ownership", "builder_orientation",
     ["software", "trade", "craft", "manufacturing"],
     ["independent products", "contracting", "productised service"],
     "People who finish things can convert capability directly into something owned, "
     "instead of renting it out by the hour.", 0.65),
    ("pv_experiment_speed", "experimentation",
     ["software", "service", "creative"],
     ["faster product-market learning", "lower cost of being wrong"],
     "Cheap, frequent tests shorten the distance between an idea and evidence, which "
     "is most valuable where being wrong early is inexpensive.", 0.6),
    ("pv_commercial_leverage", "commercial_orientation",
     ["trade", "service", "professional_practice"],
     ["own client base", "pricing power", "business ownership"],
     "Comfort asking for money is the difference between a skill and a business — it is "
     "the scarcest half of most independent work.", 0.7),
    ("pv_systems_ops", "systems_thinking",
     ["manufacturing", "logistics", "operations", "healthcare"],
     ["process improvement roles", "operational advisory", "throughput gains"],
     "Seeing whole systems pays where small coordination gains multiply across volume.", 0.65),
    ("pv_leadership_scale", "operational_leadership",
     ["operations", "trade", "construction", "services"],
     ["crew ownership", "site or practice management", "scaling beyond your own hands"],
     "Once output is limited by your own hours, the ability to run other people is what "
     "raises the ceiling.", 0.65),
    ("pv_teaching_distribution", "distribution_orientation",
     ["education", "craft", "professional_services"],
     ["training income", "advisory work", "audience-led demand"],
     "Explaining what you know converts private expertise into something that reaches "
     "people who will pay for it.", 0.6),
    ("pv_longterm_compounding", "long_term_orientation",
     ["science", "craft", "professional_practice", "investing"],
     ["reputation compounding", "durable expertise", "senior advisory"],
     "Staying with one body of work long enough is itself rare, and rarity is the "
     "precondition for premium.", 0.6),
]
