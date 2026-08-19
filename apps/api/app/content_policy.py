"""Content-policy validation — the schema-level guard that no prompt wording
can bypass. Blocks prescriptive role conclusions during the story, generated
horoscopes, and false precision. Applied to every reveal, closing beat, and
LLM narrative output before display."""
from __future__ import annotations

import re

# prescriptive career language: never valid during the Discover story (PART 96)
PRESCRIPTIVE_PATTERNS = [
    r"\byou should become\b", r"\byour ideal (career|role|job|path)\b",
    r"\byour (best|perfect) career\b", r"\bperfect career\b",
    r"\bborn to\b", r"\bdestined (to|for)\b", r"\byou are definitely\b",
    r"\byou need to move into\b", r"\bmove into a career\b",
    r"\byou are suited to\b", r"\byou('d| would) make a great\b",
    r"\byou should (be|pursue|switch to)\b", r"\byour calling\b",
]

# generated-horoscope language: generic praise with no evidence link (PART 77)
HOROSCOPE_PATTERNS = [
    r"\bvisionary\b", r"\brare combination\b", r"\bnaturally (gifted|talented)\b",
    r"\bthrives? on innovation\b", r"\byou possess\b", r"\bexceptional\b",
    r"\btruly (unique|special)\b", r"\bone of a kind\b", r"\bdestiny\b",
]

# false precision toward the user (PART 89)
FALSE_PRECISION = [r"\b\d{2}%\s*(match|entrepreneur|leader|fit|similar)\b"]

# role titles the story may not prescribe (mentioning a user's OWN stated role
# is fine — the check requires a prescriptive verb near the title)
ROLE_TITLES = [
    "operations lead", "product manager", "engineering manager", "founder",
    "consultant", "data scientist", "designer", "researcher", "operations manager",
    "project manager", "team lead", "cto", "ceo",
]
PRESCRIPTIVE_VERBS = r"(become|be an?|move into|transition to|pursue|suited (to|for)|ideal|perfect|great)"


def violations(text: str, during_story: bool = True) -> list[str]:
    t = (text or "").lower()
    found: list[str] = []
    for pat in PRESCRIPTIVE_PATTERNS:
        if re.search(pat, t):
            found.append(f"prescriptive:{pat}")
    for pat in HOROSCOPE_PATTERNS:
        if re.search(pat, t):
            found.append(f"horoscope:{pat}")
    for pat in FALSE_PRECISION:
        if re.search(pat, t):
            found.append(f"false_precision:{pat}")
    if during_story:
        for title in ROLE_TITLES:
            if title in t and re.search(PRESCRIPTIVE_VERBS + r"[^.]{0,40}" + re.escape(title), t):
                found.append(f"role_prescription:{title}")
    return found


def validate(text: str, during_story: bool = True) -> bool:
    return not violations(text, during_story)
