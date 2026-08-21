"""The "Improve where I am" action must reach employed users. The gate used to
read practical_context["career_stage"], a key nothing ever writes — al_status
stores current_status — so the action was dead for its entire audience."""
from app.models import DiscoverSession
from app.workspace import available_actions


def _session(status=None):
    s = DiscoverSession()
    s.dimensions = {}
    s.practical_context = {"current_status": status} if status else {}
    return s


def test_improve_appears_for_employed_statuses():
    for raw in ("employed_good", "employed_stale"):
        ids = [a["id"] for a in available_actions(_session(raw))]
        assert "improve" in ids, f"improve missing for {raw}"


def test_improve_absent_for_everyone_else():
    for raw in (None, "founder", "freelance", "student", "between"):
        ids = [a["id"] for a in available_actions(_session(raw))]
        assert "improve" not in ids, f"improve wrongly offered for {raw}"
