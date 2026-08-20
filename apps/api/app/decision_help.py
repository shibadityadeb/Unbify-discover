"""Help for someone stuck on a question.

Stalling on a choice is not a failure to understand the instructions — it is
usually the choice genuinely being close. "Go with your gut" answers a question
nobody asked; what actually unsticks a person is seeing the choice happen
somewhere real, with both sides costing something.

So the help is a scene, not encouragement: an ordinary moment they could be
standing in, what each option would mean there, and permission to pick the one
they'd actually do. There is no skip — the way out is deciding, and a decision
made from a concrete picture is better evidence than one made from boredom.

LLM shapes it when available; the deterministic build below always works, so
help never depends on a network call landing.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dimensions import DIMENSIONS
from .llm import gateway
from .models import DiscoverSession, InteractionInstance

# Concrete scenes per dimension family. These are the fallback voice: ordinary,
# physical, dated — the opposite of "somewhere between these is you".
FAMILY_SCENES = {
    "energy": "It's Monday. The week ahead is already full, and someone just "
              "asked if you can take one more thing on.",
    "cognitive": "A problem lands on you at 4pm. Nobody's sure what's causing "
                 "it, and everyone's waiting to hear what you think.",
    "social": "Six people in a room, all talking past each other. The meeting "
              "was supposed to end ten minutes ago.",
    "execution": "The thing is nearly done. It works. There's a version of it "
                 "that's better, and it would cost you the weekend.",
    "creative": "Blank page, real deadline. There's a safe version you've done "
                "before, and one you haven't.",
    "economic": "The number is on the table. Saying yes means committing money "
                "you'd rather not lose.",
    "leverage": "Someone you worked with three years ago just messaged you out "
                "of nowhere with an opportunity.",
    "ai_era": "A tool just did in ten minutes what used to take you a day. It's "
              "80% right.",
}

DEFAULT_SCENE = ("It's an ordinary Tuesday and this decision is sitting in front "
                 "of you, waiting.")


def _scene_for(dims: list[str]) -> str:
    for dim in dims:
        fam = DIMENSIONS.get(dim, {}).get("family")
        if fam in FAMILY_SCENES:
            return FAMILY_SCENES[fam]
    return DEFAULT_SCENE


def _options_of(public: dict, private: dict) -> list[dict]:
    """Normalise every interaction shape into {label, dim, dir}.

    Labels come from what the user can see; the dimensions come from the
    server-side content, since `_public_content` deliberately strips the hidden
    signals before anything reaches the client. Reading only the public copy
    left every option with the same generic line.
    """
    out = []
    priv_opts = {o.get("id"): o for o in (private.get("options") or [])}
    for opt in public.get("options") or []:
        src = priv_opts.get(opt.get("id"), {})
        signals = sorted(src.get("signals") or [],
                         key=lambda sg: -abs(sg.get("weight", 0)))
        top = signals[0] if signals else {}
        out.append({"label": opt.get("label", ""), "dim": top.get("dim"),
                    "dir": 1 if top.get("delta", 1) >= 0 else -1})
    for side in ("left", "right"):
        pub_side, priv_side = public.get(side), private.get(side) or {}
        if isinstance(pub_side, dict) and pub_side.get("label"):
            out.append({"label": pub_side["label"], "dim": priv_side.get("dim"),
                        "dir": priv_side.get("dir", 1)})
    return [o for o in out if o["label"]]


def _means(dim: str | None, direction: int = 1) -> str:
    """What picking this costs, in the scene — never what it says about them."""
    if not dim or dim not in DIMENSIONS:
        return "You'd find out what this one costs by living it."
    meta = DIMENSIONS[dim]
    gain, give = (meta["pos"], meta["neg"]) if direction >= 0 else (meta["neg"], meta["pos"])
    # "choosing X over Y" rather than "you get X, you give up Y": several poles
    # are phrased as absences ("not knowing what comes next", "nobody listening
    # yet"), and "give up not knowing what comes next" is a double negative
    # nobody can parse at reading speed.
    return f"You'd be choosing {gain} over {give}."


def build(db: Session | None, session: DiscoverSession,
          instance: InteractionInstance) -> dict:
    """Decision help for one pending interaction. Always returns something."""
    public = instance.public_content or {}
    options = _options_of(public, instance.content or {})
    dims = [o["dim"] for o in options if o.get("dim")]

    fallback = {
        "moment": _scene_for(dims),
        "options": [{"label": o["label"], "means": _means(o.get("dim"), o.get("dir", 1))}
                    for o in options],
        "close": "There's no right one. Pick the one you'd actually do.",
        "source": "built",
    }
    if not options:
        # free-text questions have nothing to weigh up; help is a nudge at what
        # to look at, not a menu
        return {"moment": _scene_for(dims), "options": [],
                "close": public.get("help")
                or "Answer it the way you'd say it out loud. First version is fine.",
                "source": "built"}

    out = gateway.generate(db, "decision_help_v1", {
        "question": public.get("headline", ""),
        "supportingText": public.get("supportingText") or "",
        "options": [o["label"] for o in options],
    })
    if not out:
        return fallback
    moment = str(out.get("moment") or "").strip()
    close = str(out.get("close") or "").strip()
    generated = {str(o.get("label", "")).strip(): str(o.get("means", "")).strip()
                 for o in (out.get("options") or []) if isinstance(o, dict)}
    # the model must cover every option; a partial menu is worse than none, and
    # silently dropping an option would hide a real choice from the user
    if not moment or len(moment) > 400 or not all(o["label"] in generated for o in options):
        return fallback
    from . import content_policy
    shaped = {
        "moment": moment,
        "options": [{"label": o["label"], "means": generated[o["label"]]}
                    for o in options],
        "close": close or fallback["close"],
        "source": "generated",
    }
    for text in [shaped["moment"], shaped["close"], *(o["means"] for o in shaped["options"])]:
        if not content_policy.validate(text):
            return fallback
    return shaped
